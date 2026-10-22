import base64
import copy
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as s
import harness_bridge as b


class HarnessBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        for name,value in [('DB',Path(self.temp.name)/'test.sqlite3'),('CONFIG',{'api_key':'','model':'unused'})]:
            p=patch.object(s,name,value);p.start();self.addCleanup(p.stop)
        p=patch.object(s,'call_model',side_effect=AssertionError('Server model must never be called'))
        self.model=p.start();self.addCleanup(p.stop)
        s.initialize();self.owner=b.authorize('x'*40,'Bearer '+'x'*40)
        self.p=self.call('POST','/projects',{'name':'Harness 测试'})['project']
        self.material('平台提供付费短剧观看，主体与联系方式待业务确认。')

    def call(self,method,path,data=None):return b.handle(s,method,'/api/harness'+path,data or {},self.owner)
    def read(self):self.p=self.call('GET','/projects/'+self.p['id'])['project'];return self.p
    def material(self,value):
        self.p=self.call('POST',f"/projects/{self.p['id']}/material",{'revision':self.p['revision'],'material':value,'source_name':'PRD'})['project']
    def prepare(self,kind,**kw):
        self.read();return self.call('POST',f"/projects/{self.p['id']}/prepare",{'revision':self.p['revision'],'kind':kind,**kw})
    def submit(self,task,result):
        out=self.call('POST',f"/tasks/{task['task_id']}/submit",{'stage':task['stage'],'result':result})
        if out['status']=='done':self.p=out['project']
        return out
    def analysis(self):
        raw=copy.deepcopy(s.seed()['analysis']);raw.pop('provenance',None)
        self.submit(self.prepare('analyze'),raw)
    def confirmed(self):
        self.analysis()
        self.p=s.perform(self.p['id'],'answers',{'revision':self.p['revision'],
                    'answers':s.seed()['answers'],'confirmed_by':'人工确认测试'})
    def draft(self):
        self.confirmed();task=self.prepare('draft');raw=s.seed()['draft']
        next_task=self.submit(task,{'document':raw['service'],'reviews':raw['reviews'],'blockers':raw['blockers']})
        return self.submit(next_task,{'document':raw['privacy'],'reviews':[],'blockers':[]})

    def test_server_status_does_not_require_model_key(self):
        out=self.call('GET','/status');self.assertFalse(out['requires_model_api_key']);self.model.assert_not_called()
    def test_token_authentication(self):
        with self.assertRaises(s.UserError):b.authorize('','Bearer '+'x'*40)
        with self.assertRaises(s.UserError):b.authorize('x'*40,'Bearer '+'y'*40)
    def test_other_projects_are_outside_plugin_scope(self):
        other=s.create_project('网页项目','live')
        with self.assertRaises(s.UserError):self.call('GET','/projects/'+other['id'])
        with self.assertRaises(s.UserError):b.owned(s,self.p['id'],'other-owner')
        self.assertEqual(len(self.call('GET','/projects')),1)
    def test_analysis_comes_from_harness_and_has_no_approval(self):
        self.analysis();self.assertEqual(self.p['analysis']['provenance']['kind'],'harness')
        self.assertNotIn('confirmed_by',self.p);self.model.assert_not_called()
    def test_agent_cannot_confirm_or_archive_through_bridge(self):
        for action in ('answers','archive','edit','review'):
            with self.assertRaises(s.UserError):self.call('POST',f"/projects/{self.p['id']}/{action}",{'confirmed':True})
        with self.assertRaises(s.UserError):self.prepare('draft')
    def test_unexpected_approval_fields_are_rejected(self):
        task=self.prepare('analyze');raw=copy.deepcopy(s.seed()['analysis']);raw.pop('provenance',None);raw['confirmed_by']='AI'
        with self.assertRaises(s.UserError):self.submit(task,raw)
        self.assertIsNone(self.read()['analysis'])
    def test_partial_draft_and_invalid_privacy_do_not_change_current_text(self):
        self.confirmed();task=self.prepare('draft');raw=s.seed()['draft']
        next_task=self.submit(task,{'document':raw['service'],'reviews':[],'blockers':[]})
        self.assertIsNone(self.read()['draft'])
        with self.assertRaises(s.UserError):self.submit(next_task,{'document':'截断','reviews':[],'blockers':[]})
        self.assertIsNone(self.read()['draft'])
        self.submit(next_task,{'document':raw['privacy'],'reviews':[],'blockers':[]})
        self.assertEqual(self.p['draft']['service'],raw['service']);self.assertFalse(self.p['versions'])
        self.model.assert_not_called()
    def test_material_edit_makes_pending_result_stale(self):
        task=self.prepare('analyze');self.material('业务材料发生了变化。')
        raw=copy.deepcopy(s.seed()['analysis']);raw.pop('provenance',None)
        with self.assertRaises(s.UserError):self.submit(task,raw)
        self.assertIsNone(self.read()['analysis'])
        self.assertNotEqual(self.prepare('analyze')['task_id'],task['task_id'])
    def test_preparation_and_submission_are_idempotent(self):
        task=self.prepare('analyze');self.assertEqual(self.prepare('analyze')['task_id'],task['task_id'])
        raw=copy.deepcopy(s.seed()['analysis']);raw.pop('provenance',None)
        first=self.submit(task,raw);second=self.submit(task,raw)
        self.assertEqual(first['project']['revision'],second['project']['revision'])
    def test_partial_stage_survives_initialization_and_duplicate(self):
        self.confirmed();task=self.prepare('draft');raw=s.seed()['draft']
        result={'document':raw['service'],'reviews':[],'blockers':[]}
        following=self.submit(task,result);s.initialize()
        duplicate=self.submit(task,result)
        self.assertEqual(following['stage'],duplicate['stage']);self.assertEqual(duplicate['stage'],'draft_privacy')
    def test_web_generation_for_harness_project_never_calls_server_model(self):
        for action in ('analyze','draft','chat','revise'):
            with self.assertRaises(s.UserError):s.perform(self.p['id'],action,{'revision':self.p['revision']})
            with self.assertRaises(s.UserError):s.submit_job(self.p['id'],action,{'revision':self.p['revision']})
        self.model.assert_not_called()
    def test_original_upload_and_real_word_export(self):
        self.p=self.call('POST',f"/projects/{self.p['id']}/import",{'revision':self.p['revision'],
                    'name':'材料.txt','content':base64.b64encode('业务正文。'.encode()).decode()})['project']
        self.assertEqual(self.p['material'],'业务正文。')
        body,mime=self.call('GET',f"/projects/{self.p['id']}/documents/material")
        self.assertIn('wordprocessingml',mime)
        with zipfile.ZipFile(io.BytesIO(body)) as archive:self.assertIn('word/document.xml',archive.namelist())
    def test_revision_only_applies_unique_patches_and_preserves_archive(self):
        self.draft();self.p=s.perform(self.p['id'],'archive',{'revision':self.p['revision'],'hash':self.p['draft']['hash'],
                          'approver':'人工法务测试','note':'已审阅测试','confirmed':True})
        old=s.version(self.p['id'],1)
        task=self.prepare('revise',change=s.seed()['change_input'],confirmation=s.seed()['change_confirmation'])
        raw=s.seed()['revision'];stages=[]
        for doc in ('service','privacy'):
            changes=[{k:v for k,v in item.items() if k!='document'} for item in raw['changes']
                     if item['document']==doc and old['draft'][doc].count(item['before'])==1]
            result={'reviews':raw['reviews'] if doc=='service' else [],'blockers':raw['blockers'],'changes':changes}
            task=self.submit(task,result);stages.append(task['status'])
        self.assertEqual(stages,['waiting','done']);self.assertEqual(s.version(self.p['id'],1)['hash'],old['hash'])
        self.assertEqual(self.p['draft']['base_version'],1);self.assertIn('verified_diff',self.p['draft'])
        self.assertEqual(self.p['draft']['provenance']['kind'],'harness');self.model.assert_not_called()
    def test_nonunique_revision_patch_is_rejected(self):
        self.draft();self.p=s.perform(self.p['id'],'archive',{'revision':self.p['revision'],'hash':self.p['draft']['hash'],
                          'approver':'人工法务测试','note':'已审阅测试','confirmed':True})
        task=self.prepare('revise',change='修改客服邮箱',confirmation='业务负责人确认')
        item=next(item for item in s.seed()['revision']['changes']
                  if item['document']=='service' and self.p['draft']['service'].count(item['before'])>1)
        result={'reviews':[],'blockers':[],'changes':[{k:v for k,v in item.items() if k!='document'}]}
        before=self.read()['draft']['hash']
        with self.assertRaises(s.UserError):self.submit(task,result)
        self.assertEqual(self.read()['draft']['hash'],before)
    def test_cancel_does_not_modify_project(self):
        task=self.prepare('analyze');before=self.read()
        self.call('POST',f"/tasks/{task['task_id']}/cancel")
        self.assertEqual(self.read(),before)
    def test_failed_final_commit_rolls_back_project_and_can_retry(self):
        self.confirmed();task=self.prepare('draft');raw=s.seed()['draft']
        task=self.submit(task,{'document':raw['service'],'reviews':[],'blockers':[]})
        real_store=s.store
        def fail_after_write(*args,**kwargs):
            real_store(*args,**kwargs)
            raise RuntimeError('simulated write interruption')
        result={'document':raw['privacy'],'reviews':[],'blockers':[]}
        with patch.object(s,'store',side_effect=fail_after_write):
            with self.assertRaises(RuntimeError):self.submit(task,result)
        self.assertIsNone(self.read()['draft'])
        self.submit(task,result);self.assertIsNotNone(self.read()['draft'])
    def test_human_can_handoff_existing_project_without_changing_documents(self):
        legacy=s.create_project('已有项目','live');legacy['material']='已有业务材料。'
        legacy['draft']=copy.deepcopy(s.seed()['draft']);legacy['draft']['hash']=s.doc_hash(legacy['draft'])
        s.store(legacy,legacy['revision'])
        legacy=s.perform(legacy['id'],'archive',{'revision':legacy['revision'],'hash':legacy['draft']['hash'],
                    'approver':'人工测试','note':'原有定稿','confirmed':True})
        before=s.version(legacy['id'],1)['hash'];text=legacy['draft']['service']
        with patch.object(s,'HARNESS_TOKEN','x'*40):
            with self.assertRaises(s.UserError):s.perform(legacy['id'],'harnesslink',{'revision':legacy['revision'],'confirmed':False})
            legacy=s.perform(legacy['id'],'harnesslink',{'revision':legacy['revision'],'confirmed':True})
        self.assertEqual(b.owned(s,legacy['id'],self.owner)['draft']['service'],text)
        self.assertEqual(s.version(legacy['id'],1)['hash'],before)
        self.assertEqual(legacy['material'],'已有业务材料。')
    def test_plugin_cannot_grant_itself_an_existing_project(self):
        legacy=s.create_project('未授权项目','live')
        with self.assertRaises(s.UserError):self.call('POST',f"/projects/{legacy['id']}/harnesslink",{'confirmed':True})


if __name__=='__main__':unittest.main()
