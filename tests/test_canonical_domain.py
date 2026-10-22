import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as s


class QuietHandler(s.Handler):
    def log_message(self,*args):pass


class CanonicalDomainTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        for name,value in [('DB',Path(self.folder.name)/'test.sqlite3'),('ORIGIN','https://www.idzlawr.cn'),
                           ('PASSWORD','test-domain-password'),('RENDER_HOST','yueding-law.onrender.com')]:
            p=patch.object(s,name,value);p.start();self.addCleanup(p.stop)
        s.initialize()
        self.http=s.ThreadingHTTPServer(('127.0.0.1',0),QuietHandler)
        p=patch.object(s,'PORT',self.http.server_port);p.start();self.addCleanup(p.stop)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.http.shutdown();self.http.server_close();self.thread.join(timeout=3)

    def request(self,host,path='/',method='GET',data=None,extra=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=3)
        try:
            headers={'Host':host,**(extra or {})}
            body=None if data is None else json.dumps(data)
            if data is not None:headers.update({'Content-Type':'application/json','X-Workspace-Request':'1'})
            connection.request(method,path,body=body,headers=headers)
            response=connection.getresponse()
            return response.status,dict(response.getheaders()),response.read()
        finally:connection.close()

    def test_render_root_redirects_before_login(self):
        status,headers,body=self.request('yueding-law.onrender.com')
        self.assertEqual(status,302)
        self.assertEqual(headers['Location'],'https://www.idzlawr.cn/')
        self.assertEqual(body,b'');self.assertNotIn('Set-Cookie',headers)
        self.assertEqual(headers['Cache-Control'],'no-store')

    def test_path_query_and_head_preserved(self):
        for method in ['GET','HEAD']:
            status,headers,body=self.request('yueding-law.onrender.com:443','/index.html?project=abc123',method)
            self.assertEqual(status,302)
            self.assertEqual(headers['Location'],'https://www.idzlawr.cn/index.html?project=abc123')
            self.assertEqual(body,b'')

    def test_health_check_does_not_redirect(self):
        status,headers,body=self.request('yueding-law.onrender.com','/healthz')
        self.assertEqual(status,200);self.assertNotIn('Location',headers)
        self.assertEqual(json.loads(body)['status'],'ok')

    def test_canonical_login_and_session_still_work(self):
        status,headers,_=self.request('www.idzlawr.cn')
        self.assertEqual(status,200);self.assertNotIn('Location',headers)
        status,headers,_=self.request('www.idzlawr.cn','/api/login','POST',{'password':'test-domain-password'},
                                      {'Origin':'https://www.idzlawr.cn'})
        self.assertEqual(status,200)
        cookie=headers['Set-Cookie'].split(';')[0]
        status,_,body=self.request('www.idzlawr.cn','/api/status',extra={'Cookie':cookie})
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['connection_scope'],'server')

    def test_unknown_host_and_spoofed_forwarded_host_stay_rejected(self):
        status,headers,body=self.request('attacker.example','/api/status',extra={'X-Forwarded-Host':'yueding-law.onrender.com'})
        self.assertEqual(status,403);self.assertNotIn('Location',headers)
        self.assertEqual(json.loads(body)['error'],'主机不被允许。')

    def test_alias_login_post_does_not_redirect_credentials_or_create_session(self):
        before=len(s.SESSIONS)
        status,headers,_=self.request('yueding-law.onrender.com','/api/login','POST',{'password':'test-domain-password'},
                                      {'Origin':'https://yueding-law.onrender.com'})
        self.assertEqual(status,403);self.assertNotIn('Location',headers);self.assertNotIn('Set-Cookie',headers)
        self.assertEqual(len(s.SESSIONS),before)

    def test_cross_origin_login_stays_rejected(self):
        status,headers,_=self.request('www.idzlawr.cn','/api/login','POST',{'password':'test-domain-password'},
                                      {'Origin':'https://attacker.example'})
        self.assertEqual(status,403);self.assertNotIn('Set-Cookie',headers)

    def test_local_preview_is_not_redirected(self):
        status,headers,_=self.request('127.0.0.1:'+str(self.http.server_port))
        self.assertEqual(status,200);self.assertNotIn('Location',headers)

    def test_no_redirect_when_alias_is_itself_canonical_or_configuration_is_missing(self):
        with patch.object(s,'ORIGIN','https://yueding-law.onrender.com'):
            self.assertIsNone(s.canonical_redirect_target('yueding-law.onrender.com','/'))
        for name,value in [('ORIGIN',''),('RENDER_HOST',''),('ORIGIN','https://user@www.idzlawr.cn'),
                           ('ORIGIN','http://www.idzlawr.cn'),('ORIGIN','https://www.idzlawr.cn/path')]:
            with patch.object(s,name,value):
                self.assertIsNone(s.canonical_redirect_target('yueding-law.onrender.com','/'))

    def test_target_cannot_select_an_external_origin(self):
        for path in ['//attacker.example/path','/\\attacker.example/path','https://attacker.example/path']:
            target=s.canonical_redirect_target('yueding-law.onrender.com',path)
            self.assertTrue(target.startswith('https://www.idzlawr.cn/'))


if __name__=='__main__':unittest.main()
