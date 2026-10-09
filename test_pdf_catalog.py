#!/usr/bin/env python3
"""Tests for GET /api/products/catalog.pdf and catalog PDF generation."""

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

# Isolated DB for this suite
_TMP = tempfile.TemporaryDirectory(prefix="ak-pdf-")
_DATA = Path(_TMP.name)
os.environ["ADMIN_PASSWORD"] = "pdf-test-pass"
os.environ["ADMIN_SECRET"] = "pdf-test-secret-0123456789ab"
# Point CRM at temp db before importing server/crm_store
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
from pdf_export.catalog import build_catalog_pdf  # noqa: E402


def assert_eq(a, b, msg=""):
    if a != b:
        raise AssertionError(f"{msg}: {a!r} != {b!r}")


def assert_true(cond, msg=""):
    if not cond:
        raise AssertionError(msg or "expected true")


def _tiny_png():
    # 1x1 PNG
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


def _login_session(port):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/login",
        data=json.dumps({"password": "pdf-test-pass"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        cookie = resp.headers.get("Set-Cookie") or ""
    assert_true("session=" in cookie, "session cookie")
    return cookie.split("session=")[1].split(";")[0]


def _req(port, path, *, method="GET", headers=None, body=None, raw=False):
    headers = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers=headers,
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


def _seed_products():
    server.init_orders_db()
    # wipe products
    with crm_store.DB_WRITE_LOCK:
        conn = crm_store.db_connect()
        try:
            conn.execute("DELETE FROM products")
            conn.commit()
        finally:
            conn.close()

    png = _tiny_png()
    long_desc = ("Сипаттама ә ғ қ ң ө ұ ү һ і. " * 40).strip()

    server.insert_product(
        {
            "id": "prod-with-photo",
            "name": "Товар с фото",
            "price": 25000,
            "currency": "kzt",
            "kind": "product",
            "description": "Короткое описание",
            "image": "assets/products/prod-with-photo.png",
            "_image_blob": png,
            "_image_mime": "image/png",
        }
    )
    server.insert_product(
        {
            "id": "prod-no-photo",
            "name": "Без фото ә",
            "price": "",
            "currency": "kzt",
            "kind": "product",
            "description": long_desc,
            "image": "assets/products/prod-no-photo.png",
        }
    )
    server.insert_product(
        {
            "id": "svc-one",
            "name": "Қызмет үлгісі",
            "price": 15000,
            "currency": "kzt",
            "kind": "service",
            "description": "Қазақша мәтін: ә ғ қ ң ө ұ ү һ і",
            "image": "assets/products/svc-one.png",
            "_image_blob": png,
            "_image_mime": "image/png",
        }
    )


def test_catalog_unauthorized():
    server.init_orders_db()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        status, data, _ = _req(port, "/api/products/catalog.pdf")
        assert_eq(status, 401, "no session → 401")
        assert_true(isinstance(data, dict) and "error" in data, "json error")
    finally:
        httpd.shutdown()


def test_catalog_pdf_http():
    _seed_products()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        session = _login_session(port)
        cookie = {"Cookie": f"session={session}"}

        status, body, headers = _req(
            port, "/api/products/catalog.pdf?lang=ru", headers=cookie, raw=True
        )
        assert_eq(status, 200, "catalog 200")
        ctype = headers.get("Content-Type") or ""
        assert_true("application/pdf" in ctype, f"content-type {ctype}")
        assert_true(body.startswith(b"%PDF"), "PDF magic")
        disp = headers.get("Content-Disposition") or ""
        assert_true("Catalog_" in disp and ".pdf" in disp, "filename")
        assert_true("no-store" in (headers.get("Cache-Control") or ""), "cache")

        # selected ids
        status, body2, _ = _req(
            port,
            "/api/products/catalog.pdf?lang=kz&ids=svc-one,missing-id",
            headers=cookie,
            raw=True,
        )
        assert_eq(status, 200, "ids filter")
        assert_true(body2.startswith(b"%PDF"), "pdf with ids")

        # nonexistent only → empty catalog still PDF
        status, body3, _ = _req(
            port,
            "/api/products/catalog.pdf?ids=nope1,nope2",
            headers=cookie,
            raw=True,
        )
        assert_eq(status, 200, "missing ids")
        assert_true(body3.startswith(b"%PDF"), "empty selection pdf")
    finally:
        httpd.shutdown()


def test_catalog_empty_db():
    server.init_orders_db()
    with crm_store.DB_WRITE_LOCK:
        conn = crm_store.db_connect()
        try:
            conn.execute("DELETE FROM products")
            conn.commit()
        finally:
            conn.close()
    pdf = build_catalog_pdf([], lang="ru", get_image=None)
    assert_true(pdf.startswith(b"%PDF"), "empty catalog pdf")


def test_catalog_edge_products():
    _seed_products()
    products = server.load_products()
    pdf = build_catalog_pdf(
        products, lang="kz", get_image=crm_store.get_product_image_bytes
    )
    assert_true(pdf.startswith(b"%PDF"), "edge products pdf")
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    for ch in "әғқңөұүһі":
        assert_true(ch in text, f"kazakh letter {ch!r} in PDF text")


def test_catalog_all_products_order():
    _seed_products()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        session = _login_session(port)
        status, body, _ = _req(
            port,
            "/api/products/catalog.pdf",
            headers={"Cookie": f"session={session}"},
            raw=True,
        )
        assert_eq(status, 200, "all products")
        assert_true(len(body) > 500, "non-trivial size")
    finally:
        httpd.shutdown()


def main():
    tests = [
        ("catalog_unauthorized", test_catalog_unauthorized),
        ("catalog_pdf_http", test_catalog_pdf_http),
        ("catalog_empty_db", test_catalog_empty_db),
        ("catalog_edge_products", test_catalog_edge_products),
        ("catalog_all_products_order", test_catalog_all_products_order),
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
