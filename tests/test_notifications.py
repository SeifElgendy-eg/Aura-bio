import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from core import app as core_app
from core import notifications, public_demo
from core.store import Store


def sub(endpoint="https://fcm.googleapis.com/fcm/send/test"):
    enc = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    key = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"endpoint": endpoint, "keys": {"p256dh": enc(key), "auth": enc(b"a" * 16)},
            "expirationTime": None}


def alert(level="amber", name="cardio"):
    return {"id": name, "signal": None, "name": name, "level": level, "fired": {"x": {"value": 1}}}


def test_store_new_escalation_dedup_and_ids_survive_reset(tmp_path):
    store = Store(str(tmp_path / "events.db"))
    assert store.sync_alerts("cm1", [alert()], "2026-11-14T10:00:00+00:00")
    assert store.sync_alerts("cm1", [alert()], "2026-11-14T11:00:00+00:00") == []
    assert store.sync_alerts("cm1", [alert("red")], "2026-11-14T12:00:00+00:00") == []
    assert [e["kind"] for e in store.notifications()[0]] == ["new", "escalated"]
    store.clear("cm1")
    store.sync_alerts("cm1", [alert()], "2026-11-15T10:00:00+00:00")
    assert [e["id"] for e in store.notifications()[0]] == [1, 2, 3]


def test_subscription_validation_rejects_ssrf_and_bad_keys():
    with pytest.raises(notifications.SubscriptionError):
        notifications.validate_subscription(sub("https://127.0.0.1/push"))
    with pytest.raises(notifications.SubscriptionError):
        notifications.validate_subscription(sub("http://fcm.googleapis.com/push"))
    bad = sub()
    bad["keys"]["auth"] = "short"
    with pytest.raises(notifications.SubscriptionError):
        notifications.validate_subscription(bad)


def test_payload_encodes_crew_and_has_no_secrets():
    payload = notifications.notification_payload({"id": 4, "crew_id": "crew/A", "level": "red"})
    assert payload == {"title": "AURA-Bio crew alert",
                       "body": "crew/A: Red alert. Open the console to review. Simulated data.",
                       "url": "/?crew=crew%2FA#health", "event_id": 4, "crew_id": "crew/A", "level": "red"}


@pytest.fixture
def public_client(tmp_path, monkeypatch):
    monkeypatch.setenv("AURA_PUBLIC_DEMO", "1")
    monkeypatch.delenv("AURA_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("AURA_DB", str(tmp_path / "public.db"))
    monkeypatch.setenv("AURA_MQTT_PORT", "1")
    monkeypatch.setattr(core_app.model_client, "URL", "http://127.0.0.1:1")
    monkeypatch.setattr(core_app.model_client, "_down_until", 0.0)
    public_demo.reset_cooldowns()
    with TestClient(core_app.app) as client:
        yield client


def test_public_subscription_opt_in_out_and_secret_free_gets(public_client):
    subscription = sub()
    response = public_client.post("/notifications/subscriptions", json=subscription, headers={"Origin": "http://testserver"})
    assert response.status_code == 200 and response.json() == {"subscribed": True}
    assert "public_key" in public_client.get("/notifications/config").json()
    assert "endpoint" not in public_client.get("/notifications").text
    assert public_client.request("DELETE", "/notifications/subscriptions", json=subscription,
                                 headers={"Origin": "http://testserver"}).json() == {"removed": True}


def test_public_subscription_requires_origin_and_other_mutations_stay_protected(public_client):
    assert public_client.post("/notifications/subscriptions", json=sub()).status_code == 403
    assert public_client.post("/checkin", json={}).status_code == 401


def test_vapid_key_is_adjacent_private_and_stable(tmp_path, monkeypatch):
    monkeypatch.setenv("AURA_DB", str(tmp_path / "core.db"))
    store = Store(str(tmp_path / "core.db"))
    first = notifications.NotificationService(store, str(tmp_path / "core.db"))
    second = notifications.NotificationService(store, str(tmp_path / "core.db"))
    key = Path(tmp_path / "core.db.vapid.pem")
    assert first.public_key == second.public_key and key.exists() and key.stat().st_mode & 0o077 == 0
    assert "BEGIN" in key.read_text()


@pytest.mark.parametrize("endpoint", ["https://fcm.googleapis.com:bad/push", "https://[broken/push",
    "https://fcm.googleapis.com/push\n", "https://fcm.googleapis.com.attacker.test/push"])
def test_malformed_subscription_url(endpoint):
    with pytest.raises(notifications.SubscriptionError):
        notifications.validate_subscription(sub(endpoint))


def test_invalid_curve_key_and_expiration():
    bad = sub()
    bad["keys"]["p256dh"] = base64.urlsafe_b64encode(b"\x04" + b"x" * 64).decode()
    with pytest.raises(notifications.SubscriptionError):
        notifications.validate_subscription(bad)
    bad = sub()
    bad["expirationTime"] = float("nan")
    with pytest.raises(notifications.SubscriptionError):
        notifications.validate_subscription(bad)


def test_cross_origin_enrollment_rejected(public_client):
    assert public_client.post("/notifications/subscriptions", json=sub(),
                             headers={"Origin": "https://attacker.test"}).status_code == 403
    assert public_client.post("/notifications/subscriptions", content="{}", headers={
        "Origin": "http://testserver", "Content-Type": "text/plain"}).status_code == 415


def test_all_enrolled_devices_receive_same_event_and_late_devices_do_not(tmp_path, monkeypatch):
    import asyncio
    import pywebpush
    store = Store(str(tmp_path / "devices.db"))
    service = notifications.NotificationService(store, str(tmp_path / "devices.db"))
    first, second, late = [sub(f"https://fcm.googleapis.com/fcm/send/{i}") for i in range(3)]
    for subscription in (first, second):
        store.add_subscription(subscription, 1, 200)
    store.add_subscription(late, 3, 200)
    sent = []
    # Exercise real encryption; only the provider network transport is replaced.
    def capture(subscription, data, **kwargs):
        assert pywebpush.WebPusher(subscription).encode(data.encode("utf-8"))
        sent.append((subscription["endpoint"], json.loads(data)))
    monkeypatch.setattr(pywebpush, "webpush", capture)
    asyncio.run(service.deliver({"id": 8, "crew_id": "other_crew", "level": "red", "created_at": 2}))
    assert {endpoint for endpoint, _ in sent} == {first["endpoint"], second["endpoint"]}
    assert all(payload["event_id"] == 8 and payload["crew_id"] == "other_crew" for _, payload in sent)


def test_expired_subscription_pruned_and_transient_retry_bounded(tmp_path, monkeypatch):
    import time
    import pywebpush
    from requests import Response
    store = Store(str(tmp_path / "prune.db"))
    service = notifications.NotificationService(store, str(tmp_path / "prune.db"))
    subscription = sub()
    service.subscribe(subscription)
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        response = Response()
        response.status_code = 410
        raise pywebpush.WebPushException("expired", response)
    monkeypatch.setattr(pywebpush, "webpush", fail)
    service._send_one(subscription, {"event_id": 1})
    assert calls == [1] and store.subscriptions_for(time.time()) == []
    def retry(*args, **kwargs):
        calls.append(1)
        response = Response()
        response.status_code = 503
        response.headers["Retry-After"] = "0"
        raise pywebpush.WebPushException("temporarily unavailable", response)
    monkeypatch.setattr(pywebpush, "webpush", retry)
    service._send_one(subscription, {"event_id": 1})
    assert len(calls) == 3


def test_two_console_connections_receive_same_crew_wide_event(public_client):
    with public_client.websocket_connect("/ws?notifications=1") as first:
        with public_client.websocket_connect("/ws?notifications=1") as second:
            core_app.store.sync_alerts("other_crew", [alert("red")], "2026-11-14T10:00:00+00:00")
            a, b = first.receive_json(), second.receive_json()
            assert a == b and a["type"] == "notification"
            assert a["notification"]["crew_id"] == "other_crew"


def test_briefing_download_and_root_worker_headers(public_client):
    response = public_client.get("/briefing")
    assert response.status_code == 200 and 0 < len(response.content) < 50_000
    assert int(response.headers["content-length"]) == len(response.content)
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers["cache-control"] == "no-store"
    assert 'filename="aura-bio-briefing.txt"' in response.headers["content-disposition"]
    assert "SIMULATION: YES" in response.content.decode("utf-8")
    worker = public_client.get("/notifications-sw.js")
    assert worker.status_code == 200 and worker.headers["service-worker-allowed"] == "/"
    assert worker.headers["cache-control"] == "no-cache"
    assert "addEventListener('push'" in worker.text


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_malformed_subscription_json(public_client, method):
    response = public_client.request(method, "/notifications/subscriptions", content="{", headers={
        "Origin": "http://testserver", "Content-Type": "application/json"})
    assert response.status_code == 422 and response.json()["detail"] == "invalid subscription JSON"
