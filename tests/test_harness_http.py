from http.client import HTTPConnection
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as s


class HarnessHTTPTests(unittest.TestCase):
    def test_real_http_roundtrip_without_any_server_model_key(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(s,'DB',Path(folder)/'workspace.sqlite3'), \
             patch.object(s,'ORIGIN','https://www.idzlawr.cn'),patch.object(s,'HARNESS_TOKEN','t'*40), \
             patch.object(s,'PASSWORD','human-workbench-password'),patch.dict(s.CONFIG,api_key=''), \
             patch.object(s,'call_model',side_effect=AssertionError('No server inference allowed')) as model:
            s.initialize()
            class Handler(s.Handler):
                def log_message(self,*args):pass
            http=s.ThreadingHTTPServer(('127.0.0.1',0),Handler)
            thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
            def request(method,path,body=None,token=True,cookie=None):
                c=HTTPConnection('127.0.0.1',http.server_port,timeout=4)
                headers={'Host':'www.idzlawr.cn','X-Workspace-Request':'1','Content-Type':'application/json'}
                if token:headers['Authorization']='Bearer '+'t'*40
                if cookie:headers['Cookie']=cookie
                try:
                    c.request(method,path,headers=headers,body=None if body is None else json.dumps(body))
                    r=c.getresponse();raw=r.read();meta=dict(r.getheaders())
                    return r.status,meta,json.loads(raw) if 'application/json' in meta.get('Content-Type','') else raw
                finally:c.close()
            try:
                self.assertEqual(request('GET','/api/harness/status',token=False)[0],401)
                self.assertFalse(request('GET','/api/harness/status')[2]['requires_model_api_key'])
                self.assertEqual(request('GET','/api/projects')[0],401)
                self.assertEqual(request('GET','/api/knowledge',token=False)[0],401)
                self.assertEqual(request('GET','/api/harness/knowledge')[0],200)
                references=request('POST','/api/harness/knowledge/search',{'query':'仿声的授权','scenario':'ai_generation'})[2]
                self.assertTrue(references['results'])
                ref=references['results'][0]
                self.assertEqual(request('POST',f"/api/harness/knowledge/{ref['id']}/review",{'confirmed':True})[0],404)
                p=request('POST','/api/harness/projects',{'name':'HTTP Harness 项目'})[2]['project'];pid=p['id']
                p=request('POST',f'/api/harness/projects/{pid}/material',{'revision':p['revision'],'material':'短剧播放产品PRD'})[2]['project']
                task=request('POST',f'/api/harness/projects/{pid}/prepare',{'revision':p['revision'],'kind':'analyze'})[2]
                self.assertTrue(task['knowledge_context']['results'])
                analysis=dict(s.seed()['analysis']);analysis.pop('provenance',None)
                p=request('POST',f"/api/harness/tasks/{task['task_id']}/submit",{'stage':'analyze','result':analysis})[2]['project']
                self.assertEqual(request('POST',f'/api/harness/projects/{pid}/prepare',{'revision':p['revision'],'kind':'draft'})[0],409)
                self.assertEqual(request('POST',f'/api/harness/projects/{pid}/answers',{'answers':{}})[0],404)
                status,headers,_=request('POST','/api/login',{'password':'human-workbench-password'},token=False)
                self.assertEqual(status,200);cookie=headers['Set-Cookie'].split(';')[0]
                p=request('POST',f'/api/projects/{pid}/answers',{'revision':p['revision'],'answers':s.seed()['answers'],'confirmed_by':'人工测试确认'},token=False,cookie=cookie)[2]
                task=request('POST',f'/api/harness/projects/{pid}/prepare',{'revision':p['revision'],'kind':'draft'})[2]
                raw=s.seed()['draft']
                task=request('POST',f"/api/harness/tasks/{task['task_id']}/submit",{'stage':task['stage'],'result':{'document':raw['service'],'reviews':[],'blockers':[]}})[2]
                result=request('POST',f"/api/harness/tasks/{task['task_id']}/submit",{'stage':task['stage'],'result':{'document':raw['privacy'],'reviews':[],'blockers':[]}})[2]
                self.assertEqual(result['status'],'done');self.assertEqual(result['project']['draft']['provenance']['kind'],'harness')
                status,headers,word=request('GET',f'/api/harness/projects/{pid}/documents/service')
                self.assertEqual(status,200);self.assertTrue(word.startswith(b'PK'))
                self.assertEqual(request('POST',f'/api/projects/{pid}/archive',{'confirmed':True})[0],401)
                self.assertEqual(request('POST',f'/api/harness/projects/{pid}/archive',{'confirmed':True})[0],404)
                model.assert_not_called()
            finally:http.shutdown();http.server_close();thread.join(timeout=3)


if __name__=='__main__':unittest.main()
