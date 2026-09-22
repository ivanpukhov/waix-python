"""Server-side WAIX API v1 client. No automatic retries; preserve idempotency keys."""
from __future__ import annotations
import hashlib
import hmac
import json
import math
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

__version__ = "0.1.0"
Json = dict[str, Any]
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)

def _part(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("A non-empty identifier is required")
    return urllib.parse.quote(value, safe="")

def _key(value: str, uuid: bool = False) -> str:
    if not isinstance(value, str) or not (_UUID.fullmatch(value) if uuid else re.fullmatch(r"[A-Za-z0-9_.:-]{8,128}", value)):
        raise ValueError("A stable UUID Idempotency-Key is required" if uuid else "Invalid Idempotency-Key")
    return value

class WaixError(Exception):
    def __init__(self, message: str, *, status: int = 0, code: str = "TRANSPORT_ERROR", request_id: str | None = None, retry_after: str | None = None, body: Any = None):
        super().__init__(message)
        self.status, self.code, self.request_id, self.retry_after, self.body = status, code, request_id, retry_after, body

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class Waix:
    def __init__(self, api_key: str, *, base_url: str = "https://waix.kz/api/v1", timeout: float = 30):
        if not isinstance(api_key, str) or not api_key.strip() or "\r" in api_key or "\n" in api_key:
            raise ValueError("A server-side WAIX API key is required")
        u = urllib.parse.urlsplit(base_url)
        if not u.hostname or u.username or u.password or u.query or u.fragment or u.path.rstrip("/") != "/api/v1" or not (u.scheme == "https" or u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1", "::1")):
            raise ValueError("base_url must be an HTTPS /api/v1 URL (HTTP allowed only on localhost)")
        if not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise ValueError("timeout must be between 0 and 300 seconds")
        self._api_key, self._base_url, self._timeout = api_key, base_url.rstrip("/"), timeout
        self._opener = urllib.request.build_opener(_NoRedirect())
        self.messages, self.connections, self.templates = _Messages(self), _Connections(self), _Templates(self)
        self.otp, self.webhook, self.media = _Otp(self), _Webhook(self), _Media(self)

    def request(self, method: str, path: str, *, body: Any = None, query: Json | None = None, idempotency_key: str | None = None, _content_type: str | None = None) -> Json:
        if not re.fullmatch(r"/(?!/)[a-zA-Z0-9_/%.-]+", path) or ".." in path or re.search(r"%2f|%5c|%2e", path, re.I):
            raise ValueError("Use a relative API endpoint path")
        url = self._base_url + path
        if query:
            url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        headers = {"Authorization": "Bearer " + self._api_key, "Accept": "application/json", "User-Agent": "waix-python/0.1.0"}
        if idempotency_key:
            headers["Idempotency-Key"] = _key(idempotency_key)
        data = None
        if body is not None:
            data = body if _content_type else json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            headers["Content-Type"] = _content_type or "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            response = self._opener.open(req, timeout=self._timeout)
        except urllib.error.HTTPError as error:
            response = error
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            raise WaixError("WAIX request failed or timed out. Delivery outcome may be unknown; reuse the same idempotency key.") from error
        with response:
            status, hdr = response.status, response.headers
            try:
                raw = response.read()
                result = json.loads(raw) if raw else None
            except (ValueError, UnicodeError) as error:
                raise WaixError("WAIX returned an invalid JSON response", status=status, code="INVALID_RESPONSE", request_id=hdr.get("X-Request-Id")) from error
            except (OSError, TimeoutError) as error:
                raise WaixError("WAIX response was interrupted. Reuse the same idempotency key.", request_id=hdr.get("X-Request-Id")) from error
            if not 200 <= status < 300:
                value = result if isinstance(result, dict) else {}
                raise WaixError(str(value.get("error", f"WAIX HTTP {status}")), status=status, code=value.get("code", "API_ERROR"), request_id=value.get("request_id", hdr.get("X-Request-Id")), retry_after=hdr.get("Retry-After"), body=result)
            return result

class _Resource:
    def __init__(self, client: Waix): self._c = client
class _Messages(_Resource):
    def send(self, body: Json, idempotency_key: str) -> Json: return self._c.request("POST", "/messages", body=body, idempotency_key=_key(idempotency_key, True))
    def list(self, **query: Any) -> Json: return self._c.request("GET", "/messages", query=query)
    def get(self, id: str) -> Json: return self._c.request("GET", "/messages/" + _part(id))
    def retry(self, id: str, *, confirm_outcome_unknown: bool = False) -> Json: return self._c.request("POST", "/messages/" + _part(id) + "/retry", body={"confirm_outcome_unknown": confirm_outcome_unknown})
class _Connections(_Resource):
    def list(self) -> Json: return self._c.request("GET", "/connections")
    def profile(self, id: str) -> Json: return self._c.request("GET", "/connections/" + _part(id) + "/profile")
    def update_profile(self, id: str, body: Json) -> Json: return self._c.request("PUT", "/connections/" + _part(id) + "/profile", body=body)
class _Templates(_Resource):
    def list(self, id: str, **query: Any) -> Json: return self._c.request("GET", "/connections/" + _part(id) + "/templates", query=query)
    def get(self, id: str, name: str) -> Json: return self._c.request("GET", "/connections/" + _part(id) + "/templates/" + _part(name))
    def create(self, id: str, body: Json) -> Json: return self._c.request("POST", "/connections/" + _part(id) + "/templates", body=body)
    def update(self, id: str, name: str, body: Json) -> Json: return self._c.request("PATCH", "/connections/" + _part(id) + "/templates/" + _part(name), body=body)
    def delete(self, id: str, name: str) -> Json: return self._c.request("DELETE", "/connections/" + _part(id) + "/templates/" + _part(name))
    def preview(self, id: str, body: Json) -> Json: return self._c.request("POST", "/connections/" + _part(id) + "/templates/preview", body=body)
class _Otp(_Resource):
    def send(self, body: Json, idempotency_key: str) -> Json: return self._c.request("POST", "/otp/send", body=body, idempotency_key=_key(idempotency_key))
    def verify(self, id: str, code: str) -> Json: return self._c.request("POST", "/otp/verify", body={"id": id, "code": code})
    def status(self, id: str) -> Json: return self._c.request("GET", "/otp/" + _part(id))
class _Webhook(_Resource):
    def get(self) -> Json: return self._c.request("GET", "/webhook")
    def update(self, body: Json) -> Json: return self._c.request("PUT", "/webhook", body=body)
    def delete(self) -> Json: return self._c.request("DELETE", "/webhook")
    def test(self) -> Json: return self._c.request("POST", "/webhook/test", body={})
    def rotate_secret(self) -> Json: return self._c.request("POST", "/webhook/rotate-secret", body={})
class _Media(_Resource):
    def list(self, **query: Any) -> Json: return self._c.request("GET", "/media", query=query)
    def get_url(self, id: str) -> Json: return self._c.request("GET", "/media/" + _part(id) + "/url")
    def delete(self, id: str) -> Json: return self._c.request("DELETE", "/media/" + _part(id))
    def upload(self, connection_id: str, file: str | Path, *, content_type: str = "application/octet-stream", type: str | None = None, voice: bool | None = None) -> Json:
        path = Path(file)
        if path.stat().st_size > 100 * 1024 * 1024: raise ValueError("File exceeds 100 MB")
        if not re.fullmatch(r"[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+", content_type): raise ValueError("Invalid content_type")
        boundary = "waix" + secrets.token_hex(24)
        fields = {"connection_id": connection_id, "type": type, "voice": str(voice).lower() if voice is not None else None}
        chunks = []
        for name, value in fields.items():
            if value is not None: chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        filename = path.name.replace('"', "_").replace("\r", "_").replace("\n", "_").replace("\\", "_")
        chunks.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'.encode(), path.read_bytes(), f'\r\n--{boundary}--\r\n'.encode()])
        return self._c.request("POST", "/media", body=b"".join(chunks), _content_type="multipart/form-data; boundary=" + boundary)

def verify_webhook(raw_body: bytes | str, timestamp: str, signature: str, secret: str, *, tolerance: float = 300, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    if not isinstance(timestamp, str) or not re.fullmatch(r"\d{10,12}", timestamp) or not isinstance(signature, str) or not re.fullmatch(r"v1=[a-fA-F0-9]{64}", signature) or not isinstance(secret, str) or not secret or not math.isfinite(tolerance) or tolerance < 0 or not math.isfinite(now) or abs(now - int(timestamp)) > tolerance:
        return False
    if isinstance(raw_body, str): raw_body = raw_body.encode("utf-8")
    if not isinstance(raw_body, bytes): return False
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature[3:].lower())

__all__ = ["Waix", "WaixError", "verify_webhook"]
