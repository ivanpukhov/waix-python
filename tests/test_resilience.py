import io
import json
import time
import unittest
from email.message import Message
from waix import Waix, WaixError, verify_webhook
class Response(io.BytesIO):
 def __init__(self,raw,status=200,headers=None):
  super().__init__(raw);self.status=status;self.headers=Message()
  for k,v in (headers or {}).items():self.headers[k]=v
class Opener:
 def __init__(self,responses):self.responses=iter(responses);self.requests=[]
 def open(self,request,**kwargs):self.requests.append(request);return next(self.responses)
class Tests(unittest.TestCase):
 def test_proxy_errors_limits_and_no_retry(self):
  for status,raw,code in [(429,b'html','API_ERROR'),(502,b'bad','API_ERROR'),(302,b'','REDIRECT_DISALLOWED'),(200,b'null','INVALID_RESPONSE'),(200,b'[]','INVALID_RESPONSE'),(200,b'bad','INVALID_RESPONSE'),(200,b'x'*1025,'RESPONSE_TOO_LARGE')]:
   with self.subTest(status=status,code=code):
    api=Waix('fixture',max_response_bytes=1024);api._opener=Opener([Response(raw,status,{'Retry-After':'7','X-Request-Id':'req-1'})])
    with self.assertRaises(WaixError) as cm:api.connections.list()
    e=cm.exception;self.assertEqual((e.status,e.code,e.request_id,e.retry_after),(status,code,'req-1','7'));self.assertEqual(len(api._opener.requests),1)
 def test_lazy_pagination_and_repeated_cursor(self):
  api=Waix('fixture');api._opener=Opener([Response(json.dumps({'data':[{'id':'a'}],'pagination':{'next_before':'date','next_before_id':'id'}}).encode()),Response(b'{"data":[{"id":"b"}],"pagination":{"next_before":null,"next_before_id":null}}')])
  items=api.messages.iterate(connection_id='fixture',limit=1);self.assertEqual(len(api._opener.requests),0)
  self.assertEqual([x['id'] for x in items],['a','b']);self.assertIn('before_id=id',api._opener.requests[-1].full_url);self.assertIn('connection_id=fixture',api._opener.requests[-1].full_url)
  raw=b'{"data":[],"pagination":{"next_before":"same","next_before_id":"same"}}';api._opener=Opener([Response(raw),Response(raw)])
  with self.assertRaises(WaixError) as cm:list(api.messages.iterate())
  self.assertEqual(cm.exception.code,'INVALID_PAGINATION')
 def test_validation_before_transport(self):
  api=Waix('fixture');api._opener=Opener([])
  for kwargs in [{'query':{'bad':[]}},{'query':{'bad':float('nan')}},{'body':{}},{'idempotency_key':''}]:
   with self.assertRaises(ValueError):api.request('GET','/messages',**kwargs)
  with self.assertRaises(ValueError):api.otp.verify('bad','123456')
  with self.assertRaises(ValueError):Waix('fixture',timeout=True)
  self.assertEqual(len(api._opener.requests),0)
 def test_error_metadata_and_retry_after(self):
  error=WaixError('private',body={'test_code':'123456'},retry_after='60');self.assertEqual(error.retry_delay(),60)
  self.assertNotIn('123456',json.dumps(error.to_dict()))
  self.assertEqual(WaixError('wait',retry_after='Wed, 23 Sep 2026 00:00:00 GMT').retry_delay(now=1790121540),60)
 def test_webhook_wrong_input_types_are_false(self):
  for options in [{'tolerance':None},{'tolerance':True},{'now':'bad'}]:self.assertFalse(verify_webhook(b'{}','1770000000','v1='+'0'*64,'secret',**options))
if __name__=='__main__':unittest.main()

class IncompleteTests(unittest.TestCase):
 def test_incomplete_body_keeps_request_id(self):
  api=Waix('fixture');api._opener=Opener([Response(b'{"data":{}}',200,{'Content-Length':'999','X-Request-Id':'req-cut'})])
  with self.assertRaises(WaixError) as cm:api.connections.list()
  self.assertEqual((cm.exception.code,cm.exception.request_id),('TRANSPORT_ERROR','req-cut'))

class VersionTests(unittest.TestCase):
 def test_user_agent_version(self):
  from waix import __version__
  api=Waix('fixture');api._opener=Opener([Response(b'{"data":{}}')]);api.connections.list()
  self.assertEqual(api._opener.requests[0].get_header('User-agent'),'waix-python/'+__version__)
