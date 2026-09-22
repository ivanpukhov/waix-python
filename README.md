# waix-python

Python 3.10+ SDK for WAIX WhatsApp Business API. Uses the Python standard library; type annotations are included. This is a synchronous client: use a worker/thread when calling it from an asynchronous web handler.

## Install

Install the tagged GitHub release:

```sh
python -m pip install "waix-python @ git+https://github.com/ivanpukhov/waix-python.git@v0.1.0"
```

## Send an approved template

```python
import os
import uuid
from waix import Waix, WaixError
waix = Waix(os.environ['WAIX_API_KEY'])
# Persist this UUID with the order/outbox record before calling WAIX.
event_id = str(uuid.uuid4())
result = waix.messages.send({
    'connection_id': os.environ['WAIX_CONNECTION_ID'],
    'to': '+77071234567', 'type': 'template',
    'template': {
        'name': 'order_ready', 'language': {'code': 'ru'},
        'components': [{'type': 'body', 'parameters': [{'type': 'text', 'text': '42'}]}],
    },
}, event_id)
print(result['data']['id'], result['data']['status'])
```

## OTP, media and webhooks

```python
otp = Waix(os.environ['WAIX_OTP_PROJECT_KEY'])
sent = otp.otp.send({'to': '+77071234567', 'ttl': 300}, event_id)
# Bind sent['data']['id'] to this user's server session.
status = otp.otp.status(sent['data']['id'])
verified = otp.otp.verify(sent['data']['id'], supplied_code)
```

```python
from waix import verify_webhook
valid = verify_webhook(raw_body, timestamp_header, signature_header, secret)
```

Catch `WaixError`: `status` (0 for network/timeout), `code`, `request_id`, `retry_after`, `body`. Configure `Waix(key, timeout=30, base_url='https://waix.kz/api/v1')` with timeout in seconds. TLS certificate verification is enabled; configure your OS/Python CA store if needed, rather than disabling verification.

Upload: `waix.media.upload(connection_id, 'invoice.pdf', content_type='application/pdf', type='document')`. The file is read into memory (up to 100 MB; the API also enforces media-type limits). List messages: `waix.messages.list(limit=50, before=cursor, before_id=cursor_id)`.

## Development

```sh
PYTHONPATH=src python -m unittest discover -s tests
python -m pip install build
python -m build
```

## API behavior

- All calls use `https://waix.kz/api/v1` and return the complete JSON envelope (`data`, plus `pagination` when present).
- Keep API keys on your server. Never include them in a browser bundle, mobile app or workflow export. Grant only the scopes the integration needs.
- Create and persist one UUID per logical message before sending. Reuse that UUID and identical payload after network errors. A different key creates a different message. A `202` response means accepted into the queue, not delivered.
- Requests time out after 30 seconds and do not retry automatically or follow redirects. For HTTP 429 respect `Retry-After`; preserve the original idempotency key. Never blindly retry an `outcome_unknown` message.
- Start conversations with an approved template. Free-form messages depend on Meta's customer-service window. Collect recipient consent and honor opt-outs.
- OTP uses a separate project API key. Sandbox returns `test_code` and sends no WhatsApp message. Never expose `test_code` to the user being authenticated. Live OTP requires an available market/package and approved system sender. Check your WAIX dashboard before enabling production traffic.
- Bind the OTP challenge ID to the requesting user's server session. Only that session may verify it. The SDK does not implement your application's account policy, login session or public-endpoint rate limit.

## Endpoint coverage

Messages: send, list with cursor pagination, get and explicit retry. Connections: list and business profile read/update. Templates: list, get, create, update, delete and preview. Media: list, upload, URL and delete. Workspace webhook: read, update, delete, test and secret rotation. OTP: send, verify and status.

Some operations require management scopes or a workspace-level key; a project OTP key cannot manage a workspace webhook. API permissions and schemas: [WAIX API reference](https://waix.kz/openapi-api-v1.json).

The generic `request` method is available for additional API v1 operations. It accepts only relative API paths; never use it with a destination supplied by an untrusted caller.

## Webhook receiver

Verify the signature against the **original raw request bytes before JSON parsing**, using `X-Waix-Timestamp`, `X-Waix-Signature` and your webhook secret. The signing string is `timestamp + "." + rawBody`, HMAC-SHA256, prefixed with `v1=`. Verification uses constant-time comparison and a default 300-second tolerance. Reject invalid requests and deduplicate accepted events by `X-Waix-Delivery`; a valid signature alone does not prevent replay within the time window. Store/process the event durably, then return a 2xx response promptly.

## Support and versioning

[Documentation](https://waix.kz/docs) · [Support](https://waix.kz/contacts) · [Pricing](https://waix.kz/pricing).

This is the WAIX API v1 client, not the Meta Graph API SDK. SDK versions use SemVer. The client never logs keys, message bodies or OTP codes. If you add application logging, redact those values and retain request IDs for troubleshooting.

License: MIT.
