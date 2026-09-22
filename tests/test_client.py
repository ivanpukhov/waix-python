import hashlib
import hmac
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from waix import Waix, WaixError, verify_webhook
KEY = 'f5bf0474-d4b6-4ca5-bd1b-92e44f3ad0fb'
class Handler(BaseHTTPRequestHandler):
    calls = []
    def log_message(self, *args): pass
    def handle_request(self):
        raw = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.calls.append((self.command, self.path, dict(self.headers), raw))
        status, body = 200, {'data': {'id': KEY}, 'pagination': {'next_before': 'next'}}
        if self.path.endswith('/connections'):
            status, body = 429, {'error': 'Wait', 'code': 'RATE_LIMITED', 'request_id': 'req-fixture'}
        elif self.path.endswith('/media') and self.command == 'GET':
            status, body = 302, {}
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Retry-After', '60')
        if status == 302: self.send_header('Location', '/stolen')
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())
    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = handle_request
class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()
    def setUp(self):
        Handler.calls.clear()
        self.api = Waix('fixture', base_url=f'http://127.0.0.1:{self.server.server_port}/api/v1')
    def test_message_otp_and_profile_contract(self):
        result = self.api.messages.send({'connection_id':KEY,'to':'+77000000000','type':'text','text':{'body':'Сәлем'}}, KEY)
        self.assertEqual(result['data']['id'], KEY)
        method, path, headers, body = Handler.calls[-1]
        self.assertEqual((method, path), ('POST','/api/v1/messages'))
        self.assertEqual(headers['Authorization'], 'Bearer fixture'); self.assertEqual(headers['Idempotency-Key'], KEY)
        self.assertEqual(json.loads(body)['text']['body'], 'Сәлем')
        self.api.otp.send({'to':'+77000000000'}, KEY); self.api.otp.verify(KEY, '123456'); self.api.otp.status(KEY)
        self.api.connections.update_profile(KEY, {'about':'WAIX'}); self.assertEqual(Handler.calls[-1][0], 'PUT')
        self.api.templates.update(KEY, 'order_ready', {'components':[]}); self.assertEqual(Handler.calls[-1][0], 'PATCH')
    def test_error_metadata_no_retry(self):
        with self.assertRaises(WaixError) as cm: self.api.connections.list()
        self.assertEqual((cm.exception.status, cm.exception.request_id, cm.exception.retry_after), (429,'req-fixture','60'))
        self.assertEqual(len(Handler.calls),1)
    def test_redirect_is_not_followed(self):
        with self.assertRaises(WaixError) as cm: self.api.media.list()
        self.assertEqual(cm.exception.status,302); self.assertEqual(len(Handler.calls),1)
    def test_validation(self):
        with self.assertRaises(ValueError): self.api.messages.send({}, 'bad')
        with self.assertRaises(ValueError): self.api.request('GET','//attacker.test')
        with self.assertRaises(ValueError): Waix('fixture',base_url='http://example.com/api/v1')
    def test_signature(self):
        raw, ts = '{"message":"Сәлем"}'.encode(), '1770000000'
        signature = 'v1=' + hmac.new(b'secret',ts.encode()+b'.'+raw,hashlib.sha256).hexdigest()
        self.assertTrue(verify_webhook(raw,ts,signature,'secret',now=int(ts)))
        self.assertFalse(verify_webhook(b'{}',ts,signature,'secret',now=int(ts)))
        self.assertFalse(verify_webhook(raw,ts,signature,'secret',now=int(ts)+301))
        self.assertFalse(verify_webhook(raw,ts,signature,'wrong',now=int(ts)))
if __name__ == '__main__': unittest.main()
