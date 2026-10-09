#!/usr/bin/env python3
"""Проверки CRM: заказы, клиенты, доступ, статика. Запуск: python3 test_crm_reliability.py"""

import json
import os
import sqlite3
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

import server  # noqa: E402


class TestFailure(Exception):
    pass


def assert_true(cond, msg):
    if not cond:
        raise TestFailure(msg)


def assert_eq(a, b, msg):
    if a != b:
        raise TestFailure(f"{msg}: expected {b!r}, got {a!r}")


def assert_raises(exc_type, fn, msg):
    try:
        fn()
    except exc_type:
        return
    raise TestFailure(f"{msg}: expected {exc_type.__name__}")


def test_phone_normalization():
    assert_eq(server.clean_client_phone("87001234567"), "+77001234567", "8→+7")
    assert_eq(server.clean_client_phone("7001234567"), "+77001234567", "10 digits")
    assert_eq(
        server.normalize_phone_key("+7 700 123 45 67"),
        "77001234567",
        "phone_key",
    )
    assert_raises(
        ValueError,
        lambda: server.clean_client_phone("123"),
        "short phone rejected",
    )


def test_message_fallback():
    name, phone = server.parse_client_from_message(
        "Заявка\n\nИмя: Айна\nТелефон: 8 700 111 22 33"
    )
    assert_eq(name, "Айна", "parse name")
    assert_eq(phone, "+77001112233", "parse phone")


def test_create_order_requires_contacts():
    assert_raises(
        ValueError,
        lambda: server.create_order(
            {
                "source": "service",
                "serviceName": "Test",
                "message": "Hi",
                "clientName": "",
                "clientPhone": "+77001234567",
            }
        ),
        "empty name",
    )
    assert_raises(
        ValueError,
        lambda: server.create_order(
            {
                "source": "service",
                "serviceName": "Test",
                "message": "Hi",
                "clientName": "Test",
                "clientPhone": "123",
            }
        ),
        "bad phone",
    )


def test_catalog_price_is_server_truth():
    forged = server.create_order(
        {
            "source": "service",
            "serviceId": "ai.photo",
            "serviceName": "AI-фотосессия",
            "message": "forge price",
            "clientName": "Test User",
            "clientPhone": "7001234888",
            "priceFrom": 1,
            "currency": "usd",
            "lang": "ru",
        }
    )
    assert_eq(forged["priceFrom"], 25000, "service price from catalog")
    assert_eq(forged["currency"], "kzt", "service currency forced to kzt")
    assert_eq(forged["serviceId"], "ai.photo", "canonical service id")
    server.delete_order(forged["id"])

    legacy = server.create_order(
        {
            "source": "chat",
            "serviceId": "photo",
            "serviceName": "Чат-консультант",
            "message": "legacy id",
            "clientName": "Test User",
            "clientPhone": "7001234889",
            "lang": "ru",
        }
    )
    assert_eq(legacy["serviceId"], "ai.photo", "legacy photo → ai.photo")
    assert_eq(legacy["priceFrom"], 25000, "chat price from catalog")
    assert_true(legacy["serviceName"] != "Чат-консультант", "catalog name fills default")
    server.delete_order(legacy["id"])


def test_products_sqlite_roundtrip():
    server.init_orders_db()
    original = server.load_products()
    # Preserve blobs from live catalog while rewriting rows for the probe.
    original_full = []
    with server.DB_LOCK:
        conn = server.db_connect()
        try:
            for row in conn.execute("SELECT * FROM products").fetchall():
                item = server.product_row_to_dict(row)
                if row["image_blob"] is not None:
                    item["_image_blob"] = bytes(row["image_blob"])
                    item["_image_mime"] = row["image_mime"] or ""
                original_full.append(item)
        finally:
            conn.close()
    probe_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    probe = {
        "id": "testprod01",
        "name": "SQLite Probe",
        "price": 100,
        "currency": "kzt",
        "kind": "product",
        "description": "desc",
        "image": "assets/products/testprod01.png",
        "_image_blob": probe_bytes,
        "_image_mime": "image/png",
    }
    try:
        server.save_products([probe])
        loaded = server.load_products()
        assert_eq(len(loaded), 1, "products rewritten")
        assert_eq(loaded[0]["id"], "testprod01", "product id kept")
        assert_eq(loaded[0]["price"], 100, "product price")

        from crm_store import get_product_image_bytes, product_id_from_image_url

        assert_eq(
            product_id_from_image_url("/assets/products/testprod01.png"),
            "testprod01",
            "image url parse",
        )
        stored = get_product_image_bytes("testprod01")
        assert_true(stored is not None, "image blob stored")
        assert_eq(stored[0], probe_bytes, "image blob bytes")
        assert_eq(stored[1], "image/png", "image mime")

        updated = dict(probe, name="Renamed", price="")
        updated.pop("_image_blob", None)
        updated.pop("_image_mime", None)
        saved = server.update_product_record(updated)
        assert_eq(saved["name"], "Renamed", "product update name")
        assert_eq(saved["price"], "", "empty price = on request")
        stored_after = get_product_image_bytes("testprod01")
        assert_true(stored_after is not None, "blob kept after metadata update")

        got = server.get_product("testprod01")
        assert_eq(got["name"], "Renamed", "get_product")

        removed = server.delete_product("testprod01")
        assert_eq(removed["id"], "testprod01", "delete returns row")
        assert_true(server.get_product("testprod01") is None, "deleted")
        assert_true(
            get_product_image_bytes("testprod01") is None, "blob deleted with product"
        )
    finally:
        server.save_products(original_full or original)


def test_settings_in_sqlite():
    server.init_orders_db()
    from crm_store import load_admin_config_from_db, save_admin_config_to_db

    before = load_admin_config_from_db()
    save_admin_config_to_db("probe-pass", "probe-secret-0123456789abcdef")
    stored = load_admin_config_from_db()
    assert_eq(stored["password"], "probe-pass", "settings password")
    assert_eq(stored["secret"], "probe-secret-0123456789abcdef", "settings secret")
    if before:
        save_admin_config_to_db(before["password"], before["secret"])
    health = server.health_status()
    assert_eq(health.get("storage"), "sqlite", "health storage")
    assert_true(health.get("settings", 0) >= 1, "health settings count")


def test_order_idempotency_and_dedupe():
    server.init_orders_db()
    key = "test-idem-" + server.secrets.token_hex(8)
    payload = {
        "source": "service",
        "serviceId": "ai.photo",
        "serviceName": "AI-фотосессия",
        "message": "idempotency check",
        "clientName": "Idem User",
        "clientPhone": "7001234001",
        "lang": "ru",
        "idempotencyKey": key,
    }
    first = server.create_order(payload)
    assert_true(getattr(server._CREATE_ORDER_META, "created", False), "first create")
    second = server.create_order(payload)
    assert_true(not getattr(server._CREATE_ORDER_META, "created", True), "replay")
    assert_eq(first["id"], second["id"], "same key → same order id")

    # Soft dedupe: different key, same phone+service within window → same order.
    third = server.create_order(
        {
            **payload,
            "idempotencyKey": "other-" + server.secrets.token_hex(8),
            "message": "retry without shared key",
        }
    )
    assert_eq(first["id"], third["id"], "soft dedupe same phone+service")
    assert_true(not getattr(server._CREATE_ORDER_META, "created", True), "dedupe replay")

    # Different phone → new order.
    other = server.create_order(
        {
            **payload,
            "clientPhone": "7001234002",
            "idempotencyKey": "phone-" + server.secrets.token_hex(8),
        }
    )
    assert_true(other["id"] != first["id"], "different phone is new order")
    assert_true(getattr(server._CREATE_ORDER_META, "created", False), "new phone created")

    server.delete_order(first["id"])
    server.delete_order(other["id"])


def test_order_lifecycle():
    order = server.create_order(
        {
            "source": "service",
            "serviceName": "Reliability test",
            "message": "CRM test",
            "clientName": "Test User",
            "clientPhone": "7001234999",
            "lang": "ru",
        }
    )
    assert_true(order["id"], "order id")
    assert_eq(order["clientPhone"], "+77001234999", "stored phone")
    assert_eq(order["status"], "new", "default status")

    updated = server.update_order(order["id"], {"status": "in_progress", "notes": "ok"})
    assert_eq(updated["status"], "in_progress", "status update")
    assert_eq(updated["notes"], "ok", "notes update")

    clients = server.list_clients()
    key = server.normalize_phone_key(order["clientPhone"])
    match = [c for c in clients if c["phoneKey"] == key]
    assert_true(match, "client appears after order")
    assert_true(match[0]["orderCount"] >= 1, "order count")

    server.delete_order(order["id"])
    row = None
    with server.DB_LOCK:
        conn = server.db_connect()
        try:
            row = conn.execute(
                "SELECT id FROM orders WHERE id = ?", (order["id"],)
            ).fetchone()
        finally:
            conn.close()
    assert_true(row is None, "order deleted")


def test_list_clients_legacy_message():
    oid = None
    try:
        now = time.time()
        oid = "legacy" + server.secrets.token_hex(4)
        with server.DB_LOCK:
            conn = server.db_connect()
            try:
                conn.execute(
                    """
                    INSERT INTO orders (
                        id, created_at, updated_at, source, service_id, service_name,
                        message, price_from, currency, lang, status, notes,
                        visitor_id, page_path, client_name, client_phone
                    ) VALUES (?, ?, ?, 'service', '', 'Legacy svc', ?, NULL, 'kzt', 'ru',
                              'new', '', '', '', '', '')
                    """,
                    (
                        oid,
                        now,
                        now,
                        "Текст\nИмя: Legacy Client\nТелефон: 7001234888",
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        clients = server.list_clients()
        key = "77001234888"
        match = [c for c in clients if c["phoneKey"] == key]
        assert_true(match, "legacy message groups into clients")
        assert_eq(match[0]["name"], "Legacy Client", "legacy name")
    finally:
        if oid:
            try:
                server.delete_order(oid)
            except ValueError:
                pass


def test_safe_file_blocks_secrets():
    blocked = [
        "data/crm.db",
        "crm.db",
        ".env",
        "server.py",
        "data/products.json",
        "test-results/_probe.png",
        "playwright-report/index.html",
    ]
    probe = server.ROOT / "test-results" / "_probe.png"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
    try:
        for path in blocked:
            assert_true(server.safe_file("/" + path) is None, f"blocked: {path}")
            assert_true(
                server.is_private_url_path("/" + path),
                f"private url: {path}",
            )
    finally:
        probe.unlink(missing_ok=True)
    ok = server.safe_file("/index.html")
    assert_true(ok and ok.name == "index.html", "index.html allowed")


def test_rate_limit():
    ip = "test-rate-" + server.secrets.token_hex(4)
    server.ORDER_RATE.pop(ip, None)
    for _ in range(server.ORDER_RATE_LIMIT):
        assert_true(server.order_allowed(ip), "under limit")
    assert_true(not server.order_allowed(ip), "over limit")


def test_health_and_backup():
    health = server.health_status()
    assert_true(health.get("ok"), "health ok")
    assert_true("orders" in health, "health orders field")
    path = server.backup_crm_db("test")
    assert_true(path and path.is_file(), "backup file created")
    assert_true(path.parent == server.BACKUPS_DIR, "backup dir")
    path.unlink(missing_ok=True)


def run_http_checks():
    """Поднимает сервер на случайном порту и проверяет HTTP-доступ."""
    os.environ["ADMIN_PASSWORD"] = "test-pass"
    os.environ["ADMIN_SECRET"] = "test-secret-" + server.secrets.token_hex(8)
    os.environ["CRM_BACKUP_ON_START"] = "0"
    server.load_config()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.15)

    def req(path, method="GET", body=None, headers=None):
        headers = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        r = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}", data=data, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8")), resp.headers
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"raw": raw}
            return e.code, payload, e.headers

    status, health, _ = req("/api/health")
    assert_eq(status, 200, "health")
    assert_true(health.get("ok"), "health payload")

    status, data, _ = req("/api/orders")
    assert_eq(status, 401, "GET orders without auth")

    status, data, _ = req("/api/clients")
    assert_eq(status, 401, "GET clients without auth")

    status, data, headers = req("/api/login", method="POST", body={"password": "test-pass"})
    assert_eq(status, 200, "login")
    cookie = headers.get("Set-Cookie") or ""
    assert_true("session=" in cookie, "session cookie")
    session = cookie.split("session=")[1].split(";")[0]

    status, data, _ = req(
        "/api/orders",
        headers={"Cookie": f"session={session}"},
    )
    assert_eq(status, 200, "GET orders with auth")
    assert_true("orders" in data and "stats" in data, "orders payload")

    status, created, _ = req(
        "/api/orders",
        method="POST",
        body={
            "source": "contact",
            "serviceName": "HTTP test",
            "message": "from test",
            "clientName": "HTTP User",
            "clientPhone": "7001234777",
        },
    )
    assert_eq(status, 201, "POST order public")
    assert_eq(created.get("clientPhone"), "+77001234777", "HTTP order phone")
    oid = created.get("id")
    assert_true(oid, "HTTP order id")

    status, _, _ = req(
        f"/api/orders/{oid}",
        method="DELETE",
        headers={"Cookie": f"session={session}"},
    )
    assert_eq(status, 200, "DELETE order with auth")

    status, _, _ = req("/data/crm.db")
    assert_eq(status, 404, "crm.db not served")

    httpd.shutdown()


def main():
    tests = [
        ("phone_normalization", test_phone_normalization),
        ("message_fallback", test_message_fallback),
        ("create_order_requires_contacts", test_create_order_requires_contacts),
        ("catalog_price_is_server_truth", test_catalog_price_is_server_truth),
        ("products_sqlite_roundtrip", test_products_sqlite_roundtrip),
        ("settings_in_sqlite", test_settings_in_sqlite),
        ("order_idempotency_and_dedupe", test_order_idempotency_and_dedupe),
        ("order_lifecycle", test_order_lifecycle),
        ("list_clients_legacy_message", test_list_clients_legacy_message),
        ("safe_file_blocks_secrets", test_safe_file_blocks_secrets),
        ("rate_limit", test_rate_limit),
        ("health_and_backup", test_health_and_backup),
        ("http_integration", run_http_checks),
    ]
    failed = []
    for name, fn in tests:
        try:
            fn()
            print(f"OK  {name}")
        except Exception as e:
            print(f"FAIL {name}: {e}")
            failed.append(name)
    if failed:
        print(f"\n{len(failed)} failed: {', '.join(failed)}")
        sys.exit(1)
    print(f"\nAll {len(tests)} checks passed.")


if __name__ == "__main__":
    main()
