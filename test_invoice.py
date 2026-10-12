#!/usr/bin/env python3
"""Tests for GET /api/orders/<id>/invoice.pdf and money helpers."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

_TMP = tempfile.TemporaryDirectory(prefix="ak-inv-")
_DATA = Path(_TMP.name)
os.environ["ADMIN_PASSWORD"] = "inv-test-pass"
os.environ["ADMIN_SECRET"] = "inv-test-secret-0123456789ab"
# Real-looking test requisites (not production placeholders used as silent defaults).
os.environ["SELLER_NAME"] = "ИП Тестов Тест"
os.environ["SELLER_BIN"] = "123456789012"
os.environ["SELLER_ADDRESS"] = "г. Алматы, ул. Тестовая, д. 10"
os.environ["SELLER_BANK"] = "АО «Народный Банк Казахстана»"
os.environ["SELLER_IIK"] = "KZ86125KZT1001300300"
os.environ["SELLER_BIK"] = "HSBKKZKX"
os.environ["SELLER_KBE"] = "19"
os.environ["SELLER_PHONE"] = "+7 700 000 00 00"
os.environ["SELLER_TELEGRAM"] = "@test"
os.environ["SELLER_DIRECTOR"] = "Тестов Т. Т."
os.environ["SELLER_VAT_RATE"] = "0"

import crm_store  # noqa: E402

crm_store.DATA = _DATA
crm_store.ORDERS_DB = _DATA / "crm.db"
crm_store.BACKUPS_DIR = _DATA / "backups"
crm_store.UPLOADS = _DATA / "uploads"
crm_store.PRODUCTS_FILE = _DATA / "products.json"
crm_store.PRODUCTS_MIGRATED = _DATA / "products.json.migrated"
crm_store.CONFIG_FILE = _DATA / "config.json"
_DATA.mkdir(parents=True, exist_ok=True)

import server  # noqa: E402
from pdf_export.invoice import build_invoice_pdf  # noqa: E402
from pdf_export.money_words import (  # noqa: E402
    amount_in_words,
    amount_words_en,
    amount_words_kz,
    amount_words_ru,
    split_vat_from_gross,
)
from pdf_export import config as pdf_config  # noqa: E402


def assert_eq(a, b, msg=""):
    if a != b:
        raise AssertionError(f"{msg}: {a!r} != {b!r}")


def assert_true(cond, msg=""):
    if not cond:
        raise AssertionError(msg or "expected true")


def _login(port):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/login",
        data=json.dumps({"password": "inv-test-pass"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        cookie = resp.headers.get("Set-Cookie") or ""
    return cookie.split("session=")[1].split(";")[0]


def _req(port, path, *, method="GET", headers=None, body=None, raw=False):
    headers = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            payload = resp.read()
            if raw:
                return resp.status, payload, resp.headers
            try:
                return resp.status, json.loads(payload.decode("utf-8")), resp.headers
            except json.JSONDecodeError:
                return resp.status, payload, resp.headers
    except urllib.error.HTTPError as err:
        payload = err.read()
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError:
            parsed = payload
        return err.code, parsed, err.headers


def _make_order(**kwargs):
    server.init_orders_db()
    payload = {
        "source": "service",
        "serviceId": "ai.photo",
        "serviceName": "AI-фотосессия әғқ",
        "message": "тест",
        "clientName": "Тест Клиент",
        "clientPhone": "+77001112233",
        "priceFrom": 25000,
        "currency": "kzt",
        "lang": "ru",
        "idempotencyKey": "inv-" + str(time.time()) + str(kwargs.get("tag", "")),
    }
    payload.update(kwargs)
    return server.create_order(payload)


def test_money_words():
    cases = {
        1000: "Одна тысяча тенге 00 тиын",
        1500: "Одна тысяча пятьсот тенге 00 тиын",
        21000: "Двадцать одна тысяча тенге 00 тиын",
        25000: "Двадцать пять тысяч тенге 00 тиын",
        1_000_000: "Один миллион тенге 00 тиын",
    }
    for amount, expected in cases.items():
        got = amount_words_ru(amount)
        assert_eq(got, expected, f"words({amount})")


def test_currency_and_large_amounts():
    assert_eq(amount_in_words(100, "ru", "usd"), "Сто долларов 00 центов")
    assert_eq(amount_in_words(1, "ru", "usd"), "Один доллар 00 центов")
    assert_eq(amount_in_words(2, "ru", "usd"), "Два доллара 00 центов")
    assert_eq(amount_in_words(5, "ru", "rub"), "Пять рублей 00 копеек")
    assert_eq(amount_in_words(1, "ru", "rub"), "Один рубль 00 копеек")
    assert_eq(amount_in_words(1.01, "ru", "rub"), "Один рубль 01 копейка")
    assert_eq(amount_words_ru(1_000_000_000), "Один миллиард тенге 00 тиын")
    assert_eq(amount_words_en(1_000_000_000), "One billion tenge 00 tiyin")
    assert_eq(amount_words_kz(1000), "Бір мың теңге 00 тиын")
    for bad in (-1, float("nan"), float("inf")):
        for fn in (amount_words_ru, amount_words_kz, amount_words_en):
            try:
                fn(bad)
            except ValueError:
                continue
            raise AssertionError(f"{fn.__name__}({bad}) should raise ValueError")


def test_long_service_stays_inside_page():
    service = (
        "Индивидуальный проект: генерация серии портретов в национальном стиле "
        "с ретушью и цветокоррекцией для каталога"
    )
    order = {
        "id": "abcdef1234567890",
        "createdAt": 1760000000,
        "serviceName": service,
        "clientName": "А" * 80,
        "clientPhone": "+77001112233",
        "priceFrom": 999_999_999,
        "currency": "usd",
        "notes": "SECRET_NOTE_XYZ",
        "message": "SECRET_MESSAGE_ABC",
    }
    pdf = build_invoice_pdf(order, lang="ru")
    from pypdf import PdfReader

    text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages)
    assert_true("национальном стиле" in text, "long service kept")
    assert_true("SECRET_NOTE_XYZ" not in text, "notes hidden")
    assert_true("доллар" in text, "usd words")
    assert_true("тенге" not in text, "usd must not say tenge")


def test_vat_math():
    net, vat, gross = split_vat_from_gross(25000, 0)
    assert_eq(net, 25000.0)
    assert_eq(vat, 0.0)
    assert_eq(gross, 25000.0)
    net, vat, gross = split_vat_from_gross(11600, 16)
    assert_eq(gross, 11600.0)
    assert_eq(vat, 1600.0)
    assert_eq(net, 10000.0)
    net, vat, gross = split_vat_from_gross(25000, 16)
    # 25000 * 16 / 116 ≈ 3448.27586 → 3448.28
    assert_eq(vat, 3448.28)
    assert_eq(net, 21551.72)
    assert_eq(gross, 25000.0)


def test_invoice_http():
    order = _make_order(tag="http")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        status, data, _ = _req(port, f"/api/orders/{order['id']}/invoice.pdf")
        assert_eq(status, 401, "no auth")

        session = _login(port)
        cookie = {"Cookie": f"session={session}"}

        status, body, headers = _req(
            port,
            f"/api/orders/{order['id']}/invoice.pdf?lang=ru",
            headers=cookie,
            raw=True,
        )
        assert_eq(status, 200, "invoice 200")
        assert_true(body.startswith(b"%PDF"), "pdf magic")
        assert_true("application/pdf" in (headers.get("Content-Type") or ""), "ctype")
        disp = headers.get("Content-Disposition") or ""
        assert_true("Schet-faktura_" in disp, "filename")

        status, data, _ = _req(
            port, "/api/orders/doesnotexist/invoice.pdf", headers=cookie
        )
        assert_eq(status, 404, "missing order")
    finally:
        httpd.shutdown()
        try:
            server.delete_order(order["id"])
        except Exception:
            pass


def test_invoice_no_price_and_notes_and_kz():
    order = _make_order(priceFrom=None, tag="noprice")
    # Force null price in DB if create overwrote from catalog
    with crm_store.DB_WRITE_LOCK:
        conn = crm_store.db_connect()
        try:
            conn.execute(
                "UPDATE orders SET price_from = NULL, notes = ? WHERE id = ?",
                ("SECRET_NOTE_XYZ", order["id"]),
            )
            conn.commit()
        finally:
            conn.close()
    order = server.get_order(order["id"])
    assert_true(order["priceFrom"] is None, "price cleared")

    pdf = build_invoice_pdf(order, lang="ru")
    assert_true(pdf.startswith(b"%PDF"))
    from pypdf import PdfReader

    text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages)
    assert_true("SECRET_NOTE_XYZ" not in text, "notes must not appear")
    assert_true("по договорённости" in text or "договорённости" in text, "no price")

    order2 = _make_order(tag="kz", lang="kz", priceFrom=25000)
    with crm_store.DB_WRITE_LOCK:
        conn = crm_store.db_connect()
        try:
            conn.execute(
                "UPDATE orders SET service_name = ? WHERE id = ?",
                ("AI-фотосессия ә ғ қ ң ө ұ ү һ і", order2["id"]),
            )
            conn.commit()
        finally:
            conn.close()
    order2 = server.get_order(order2["id"])
    pdf_kz = build_invoice_pdf(order2, lang="kz")
    text_kz = "\n".join(
        (p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf_kz)).pages
    )
    for ch in "әғқңөұүһі":
        assert_true(ch in text_kz, f"kz letter {ch}")
    try:
        server.delete_order(order["id"])
        server.delete_order(order2["id"])
    except Exception:
        pass


def test_invoice_vat_rates():
    order = _make_order(tag="vat", priceFrom=25000)
    old = os.environ.get("SELLER_VAT_RATE", "0")
    try:
        os.environ["SELLER_VAT_RATE"] = "0"
        pdf0 = build_invoice_pdf(order, lang="ru")
        text0 = "\n".join(
            (p.extract_text() or "")
            for p in __import__("pypdf").PdfReader(io.BytesIO(pdf0)).pages
        )
        assert_true("Без НДС" in text0, "no vat label")

        os.environ["SELLER_VAT_RATE"] = "16"
        pdf16 = build_invoice_pdf(order, lang="ru")
        text16 = "\n".join(
            (p.extract_text() or "")
            for p in __import__("pypdf").PdfReader(io.BytesIO(pdf16)).pages
        )
        assert_true("16%" in text16, "vat rate")
        assert_true("3 448,28" in text16 or "3448,28" in text16 or "3 448.28" in text16, "vat amount")
        assert_true("21 551,72" in text16, "unit price excl VAT")
        assert_true("Двадцать пять тысяч тенге" in text16, "amount due stays gross")
    finally:
        os.environ["SELLER_VAT_RATE"] = old
        try:
            server.delete_order(order["id"])
        except Exception:
            pass


def test_invoice_missing_seller_requisites():
    order = {
        "id": "missingreq01",
        "createdAt": time.time(),
        "serviceName": "Тест",
        "clientName": "Клиент",
        "clientPhone": "+77001112233",
        "priceFrom": 1000,
        "currency": "kzt",
    }
    saved_bin = os.environ.pop("SELLER_BIN", None)
    try:
        try:
            build_invoice_pdf(order, lang="ru")
            raise AssertionError("expected SellerConfigError")
        except pdf_config.SellerConfigError as exc:
            assert_true("SELLER_BIN" in str(exc), "mentions missing field")
            assert_true("bin" in exc.missing, "missing list")
    finally:
        if saved_bin is not None:
            os.environ["SELLER_BIN"] = saved_bin


def test_invoice_missing_vat_rate_is_error():
    """Empty SELLER_VAT_RATE must not silently become 0% / 12%."""
    order = {
        "id": "missingvat01",
        "createdAt": time.time(),
        "serviceName": "Тест",
        "clientName": "Клиент",
        "clientPhone": "+77001112233",
        "priceFrom": 1000,
        "currency": "kzt",
    }
    saved = os.environ.pop("SELLER_VAT_RATE", None)
    try:
        try:
            build_invoice_pdf(order, lang="ru")
            raise AssertionError("expected SellerConfigError for empty VAT")
        except pdf_config.SellerConfigError as exc:
            assert_true("vat_rate" in exc.missing, "vat_rate listed")
            assert_true("SELLER_VAT_RATE" in str(exc), "message names env")
    finally:
        if saved is not None:
            os.environ["SELLER_VAT_RATE"] = saved
        else:
            os.environ["SELLER_VAT_RATE"] = "0"


def main():
    tests = [
        ("money_words", test_money_words),
        ("currency_and_large", test_currency_and_large_amounts),
        ("long_service_inside_page", test_long_service_stays_inside_page),
        ("vat_math", test_vat_math),
        ("invoice_http", test_invoice_http),
        ("invoice_no_price_notes_kz", test_invoice_no_price_and_notes_and_kz),
        ("invoice_vat_rates", test_invoice_vat_rates),
        ("invoice_missing_seller", test_invoice_missing_seller_requisites),
        ("invoice_missing_vat", test_invoice_missing_vat_rate_is_error),
    ]
    failed = []
    for name, fn in tests:
        try:
            fn()
            print(f"OK  {name}")
        except Exception as exc:
            print(f"FAIL {name}: {exc}")
            failed.append(name)
    if failed:
        print(f"\n{len(failed)} failed: {', '.join(failed)}")
        sys.exit(1)
    print(f"\nAll {len(tests)} checks passed.")


if __name__ == "__main__":
    main()
