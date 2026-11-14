"""Crew-wide browser notifications and Web Push delivery."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import os
import stat
import time
from pathlib import Path
from urllib.parse import urlsplit, quote

log = logging.getLogger("aura.notifications")

MAX_SUBSCRIBERS = 200
MAX_ENDPOINT_LENGTH = 2048
MAX_KEY_LENGTH = 256
DEFAULT_SUBJECT = "https://github.com/SeifElgendy-eg/Aura-bio"
PUSH_TIMEOUT_SECONDS = 8.0


class SubscriptionError(ValueError):
    pass


def _decode(value: str, field: str) -> bytes:
    if not isinstance(value, str) or not value or len(value) > MAX_KEY_LENGTH:
        raise SubscriptionError(f"invalid subscription {field}")
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except Exception as exc:  # noqa: BLE001
        raise SubscriptionError(f"invalid subscription {field}") from exc
    if not decoded or len(decoded) > MAX_KEY_LENGTH:
        raise SubscriptionError(f"invalid subscription {field}")
    return decoded


def _allowed_host(host: str) -> bool:
    return (host == "fcm.googleapis.com" or
            host == "push.services.mozilla.com" or host.endswith(".push.services.mozilla.com") or
            host == "web.push.apple.com" or host == "notify.windows.com" or host.endswith(".notify.windows.com"))


def validate_subscription(value: object) -> dict[str, object]:
    """Validate native PushSubscription JSON without resolving or contacting its endpoint."""
    if not isinstance(value, dict):
        raise SubscriptionError("subscription must be an object")
    endpoint = value.get("endpoint")
    keys = value.get("keys")
    if (not isinstance(endpoint, str) or len(endpoint) > MAX_ENDPOINT_LENGTH or
            any(ord(character) <= 32 for character in endpoint)):
        raise SubscriptionError("invalid subscription endpoint")
    try:
        parsed = urlsplit(endpoint)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        raise SubscriptionError("subscription endpoint is not an approved push service") from None
    if (parsed.scheme != "https" or not host or not _allowed_host(host) or
            parsed.username or parsed.password or parsed.fragment or
            parsed.query or (port not in (None, 443)) or not parsed.path):
        raise SubscriptionError("subscription endpoint is not an approved push service")
    if not isinstance(keys, dict):
        raise SubscriptionError("subscription keys are required")
    p256dh = _decode(keys.get("p256dh"), "p256dh")
    auth = _decode(keys.get("auth"), "auth")
    if len(p256dh) != 65 or p256dh[0] != 4 or len(auth) != 16:
        raise SubscriptionError("invalid subscription key lengths")
    from cryptography.hazmat.primitives.asymmetric import ec
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), p256dh)
    except ValueError:
        raise SubscriptionError("invalid subscription P-256 public key") from None
    expiration = value.get("expirationTime")
    if expiration is not None and (isinstance(expiration, bool) or
                                    not isinstance(expiration, (int, float)) or
                                    not math.isfinite(expiration) or expiration < 0):
        raise SubscriptionError("invalid subscription expirationTime")
    return {"endpoint": endpoint, "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]}}


def notification_payload(event: dict) -> dict[str, object]:
    crew_id = str(event["crew_id"])
    level = str(event["level"]).capitalize()
    return {
        "title": "AURA-Bio crew alert",
        "body": f"{crew_id}: {level} alert. Open the console to review. Simulated data.",
        "url": f"/?crew={quote(crew_id, safe='')}#health",
        "event_id": int(event["id"]),
        "crew_id": crew_id,
        "level": event["level"],
    }


def vapid_path(db_path: str | os.PathLike[str]) -> Path:
    path = Path(db_path)
    return path.with_name(path.name + ".vapid.pem")


def _ensure_vapid_key(path: Path) -> None:
    if path.exists():
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        return
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    path.parent.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    data = key.private_bytes(serialization.Encoding.PEM,
                             serialization.PrivateFormat.TraditionalOpenSSL,
                             serialization.NoEncryption())
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        return
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    path.chmod(0o600)


def vapid_public_key(path: Path) -> str:
    from cryptography.hazmat.primitives import serialization
    _ensure_vapid_key(path)
    private = serialization.load_pem_private_key(path.read_bytes(), password=None)
    public = private.public_key().public_bytes(serialization.Encoding.X962,
                                                serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(public).rstrip(b"=").decode("ascii")


class NotificationService:
    def __init__(self, store, db_path: str):
        self.store = store
        self.key_path = vapid_path(db_path)
        self.subject = os.environ.get("AURA_VAPID_SUBJECT", DEFAULT_SUBJECT)
        self.enabled = os.environ.get("AURA_NOTIFICATIONS", "1") != "0"
        self._send_slots = asyncio.Semaphore(8)
        self.public_key = vapid_public_key(self.key_path) if self.enabled else None

    def config(self) -> dict[str, object]:
        return {"enabled": self.enabled, "public_key": self.public_key}

    def subscribe(self, value: object) -> None:
        self.store.add_subscription(validate_subscription(value), time.time(), MAX_SUBSCRIBERS)

    def unsubscribe(self, value: object) -> bool:
        return self.store.remove_subscription(validate_subscription(value))

    def _send_one(self, subscription: dict, payload: dict) -> None:
        from pywebpush import WebPushException, webpush
        body = json.dumps(payload, separators=(",", ":"))
        claims = {"sub": self.subject}
        for attempt in range(2):
            try:
                webpush(subscription, body, vapid_private_key=str(self.key_path),
                        vapid_claims=claims, ttl=300, timeout=PUSH_TIMEOUT_SECONDS)
                return
            except WebPushException as exc:
                status = getattr(exc, "status_code", None)
                if status in (404, 410):
                    self.store.remove_subscription(subscription)
                    return
                if status not in (429, 500, 502, 503, 504) or attempt:
                    log.warning("web push delivery failed (%s)", status or "error")
                    return
                retry_after = getattr(exc, "retry_after", None)
                try:
                    delay = min(float(retry_after), 1.0) if retry_after is not None else 0.25
                except (TypeError, ValueError):
                    delay = 0.25
                time.sleep(max(0.0, delay))
            except Exception:  # noqa: BLE001
                log.warning("web push delivery failed")
                return

    async def _deliver_one(self, subscription: dict, payload: dict) -> None:
        async with self._send_slots:
            try:
                await asyncio.wait_for(asyncio.to_thread(self._send_one, subscription, payload),
                                       timeout=PUSH_TIMEOUT_SECONDS * 2 + 1)
            except Exception:  # noqa: BLE001
                log.warning("web push delivery timed out or failed")

    async def deliver(self, event: dict) -> None:
        if not self.enabled or not self.public_key:
            return
        payload = notification_payload(event)
        subscriptions = self.store.subscriptions_for(event["created_at"])
        await asyncio.gather(*(self._deliver_one(s, payload) for s in subscriptions),
                             return_exceptions=True)
