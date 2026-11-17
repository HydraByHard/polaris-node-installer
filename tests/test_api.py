import base64
import io
import http.server
import os
import threading
import json
import time
import unittest
import urllib.error
from unittest.mock import patch


def token(role='API', remaining=3600):
    body = base64.urlsafe_b64encode(json.dumps({'role':role,'exp':int(time.time())+remaining,'iat':int(time.time()),'uuid':'test-token-id','username':'API'}).encode()).decode().rstrip('=')
    return 'eyJhbGciOiJIUzI1NiJ9.'+body+'.synthetic-signature'


class Response:
    def __init__(self, payload, status=200):
        self.payload, self.status = payload, status
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, limit=-1): return json.dumps(self.payload).encode()


class ApiTests(unittest.TestCase):
    def setUp(self):
        from polaris_node.api import API
        from polaris_node.core import PolarisError
        self.API, self.Error = API, PolarisError

    def test_rejects_non_https_and_credential_urls(self):
        for url in ['http://panel.test','https://user:password@panel.test','https://panel.test/api?token=x','https://panel.test/#x','https://panel.test/other']:
            with self.subTest(url=url), self.assertRaises(self.Error): self.API(url, token())

    def test_rejects_admin_expired_or_long_lived_jwt_before_network(self):
        for value in ['opaque','eyJhbGciOiJIUzI1NiJ9.W10.signature',token('ADMIN'),token(remaining=30),token(remaining=90000)]:
            with self.subTest(kind=len(value)), self.assertRaises(self.Error): self.API('https://panel.test', value)

    def test_install_does_not_allow_updates_or_visible_host(self):
        client=self.API('https://panel.test',token())
        for method,path,data in [('PATCH','/hosts',{'uuid':'x'}),('DELETE','/nodes/x',None),('GET','/users',None),('POST','/hosts',{'isHidden':False,'isDisabled':True})]:
            with self.subTest(path=path), self.assertRaises(self.Error): client.request(method,path,data)

    def test_metadata_authenticates_and_version_gate_precedes_writes(self):
        client=self.API('https://panel.test',token()); seen=[]
        class Transport:
            def open(_,request,timeout):
                seen.append((request.full_url,request.get_method(),request.get_header('Authorization'),request.get_header('X-remnawave-client-type')))
                return Response({'response':{'version':'3.4.10'}})
        with patch('urllib.request.build_opener',return_value=Transport()):
            client=self.API('https://panel.test',token())
            with self.assertRaises(self.Error): client.request('POST','/config-profiles',{'name':'new'})
        self.assertEqual([(u,m) for u,m,_,_ in seen],[('https://panel.test/api/system/metadata','GET')])
        self.assertTrue(seen[0][2].startswith('Bearer '));self.assertIsNone(seen[0][3])

    def test_response_unwraps_once_and_never_retries_post(self):
        seen=[]
        class Transport:
            def open(_,request,timeout):
                seen.append(request.get_method())
                if request.full_url.endswith('/system/metadata'):return Response({'response':{'version':'3.4.11'}})
                raise urllib.error.URLError('secret-token-that-must-not-be-echoed')
        with patch('urllib.request.build_opener',return_value=Transport()):
            client=self.API('https://panel.test',token())
            with self.assertRaises(self.Error) as caught:client.request('POST','/nodes',{'name':'new'})
        self.assertEqual(seen,['GET','POST']);self.assertNotIn('secret-token',str(caught.exception))
        self.assertIn('ambiguous',str(caught.exception).lower())

    def test_http_error_body_and_redirect_location_are_not_disclosed(self):
        class Transport:
            def open(_,request,timeout):raise urllib.error.HTTPError(request.full_url,403,'secret',{},io.BytesIO(b'private-key'))
        with patch('urllib.request.build_opener',return_value=Transport()):
            client=self.API('https://panel.test',token())
            with self.assertRaises(self.Error) as caught:client.metadata()
        self.assertNotIn('private-key',str(caught.exception));self.assertNotIn('secret',str(caught.exception))
        self.assertIn('403',str(caught.exception))
        from polaris_node.api import NoRedirect
        with self.assertRaises(self.Error):NoRedirect().redirect_request(None,None,302,'m',{},'https://other.test/?secret=x')

    def test_https_request_honors_inherited_proxy(self):
        tunnels=[]
        class Proxy(http.server.BaseHTTPRequestHandler):
            def do_CONNECT(handler):
                tunnels.append(handler.path)
                handler.send_error(502)
            def log_message(handler,*args):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Proxy)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            proxy='http://127.0.0.1:'+str(server.server_port)
            with patch.dict(os.environ,{'https_proxy':proxy,'no_proxy':''},clear=True):
                client=self.API('https://127.0.0.2:9443',token())
                with self.assertRaises(self.Error):client.metadata()
            self.assertEqual(tunnels,['127.0.0.2:9443'])
        finally:server.shutdown();server.server_close();thread.join()

    def test_metadata_works_only_with_expected_wrapper(self):
        class Transport:
            def open(_,request,timeout):return Response({'response':{'version':'3.4.11','build':{'number':'230'}}})
        with patch('urllib.request.build_opener',return_value=Transport()):
            client=self.API('https://panel.test/api/',token())
            self.assertEqual(client.metadata()['version'],'3.4.11')
        self.assertNotIn(token(),repr(client))


if __name__=='__main__':unittest.main()
