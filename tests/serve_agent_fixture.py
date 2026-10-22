"""Local, isolated browser fixture; deliberately refuses every model call."""
import copy
import json
import os
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
data=root/'test-results'/'agent-browser-data';data.mkdir(parents=True,exist_ok=True)
os.environ.update(DATA_DIR=str(data),HOST='127.0.0.1',PORT='18778',PUBLIC_ORIGIN='',
                  APP_PASSWORD='',HARNESS_ACCESS_TOKEN='c'*40,SILICONFLOW_API_KEY='')
sys.path.insert(0,str(root))
import server as s
import harness_bridge as b
def no_model(*args,**kwargs):raise AssertionError('Browser fixture must not call any model')
s.call_model=no_model;s.initialize()
owner=b.authorize('c'*40,'Bearer '+'c'*40)
p=b.handle(s,'POST','/api/harness/projects',{'name':'Agent升级浏览器验收（受控样例）'},owner)['project']
p=s.get_project(p['id'])
p.update(material='平台提供短剧播放。供应商范围待业务确认。',analysis=copy.deepcopy(s.seed()['analysis']),
         answers=copy.deepcopy(s.seed()['answers']),confirmed_by='业务样例',confirmed_at=s.now(),draft=copy.deepcopy(s.seed()['draft']))
p['draft']['hash']=s.doc_hash(p['draft']);s.store(p,p['revision'])
p=s.perform(p['id'],'archive',{'revision':p['revision'],'hash':p['draft']['hash'],
            'approver':'受控样例','note':'浏览器回归的虚构基线','confirmed':True})
(root/'test-results'/'agent-browser-fixture.json').write_text(json.dumps({'project_id':p['id'],'baseline_hash':p['draft']['hash']}),encoding='utf-8')
print('Isolated browser fixture ready at http://127.0.0.1:18778',flush=True)
s.ThreadingHTTPServer(('127.0.0.1',18778),s.Handler).serve_forever()
