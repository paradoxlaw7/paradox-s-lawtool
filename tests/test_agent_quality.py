"""Grounding, lifecycle and commit integrity; controlled outputs, no inference."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as s
import harness_bridge as b
import agent_tasks as a
import agent_quality as q
import knowledge as k


class AgentQualityTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        for name,value in [('DB',Path(folder.name)/'test.sqlite3'),('call_model',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('No inference')))]:
            p=patch.object(s,name,value);p.start();self.addCleanup(p.stop)
        s.initialize();self.owner='quality-owner'
        self.p=b.handle(s,'POST','/api/harness/projects',{'name':'质量流程回归'},self.owner)['project']
        self.p=s.get_project(self.p['id'])
        self.p.update(material='平台提供短剧播放。供应商信息待业务确认。',analysis=copy.deepcopy(s.seed()['analysis']),
                      answers=copy.deepcopy(s.seed()['answers']),confirmed_by='业务测试',confirmed_at=s.now())
        s.store(self.p,self.p['revision'])

    def archive(self):
        self.p['draft']=copy.deepcopy(s.seed()['draft']);self.p['draft']['hash']=s.doc_hash(self.p['draft'])
        s.store(self.p,self.p['revision'])
        self.p=s.perform(self.p['id'],'archive',{'revision':self.p['revision'],'hash':self.p['draft']['hash'],
                       'approver':'人工测试','note':'受控回归基线','confirmed':True})

    def prepare(self,kind='revise'):
        self.p=s.get_project(self.p['id'])
        return b.prepare(s,self.p['id'],self.owner,{'revision':self.p['revision'],'kind':kind,'workflow_version':2,
                         'change':'更换SDK，具体数据接收范围待确认。','confirmation':'产品负责人提供变更说明。'})

    def submit(self,t,value):
        return b.handle(s,'POST',f"/api/harness/tasks/{t['task_id']}/submit",{'stage':t['stage'],'result':value},self.owner)

    def plan(self):
        return {'summary':'核对供应商变化','facts':[{'id':'F1','label':'供应商变化','value':'计划更换SDK',
                'status':'material','source':'change','quote':'更换SDK'}],
                'issues':[{'id':'I1','topic':'第三方数据处理','query':'SDK 供应商 第三方 数据',
                           'priority':'critical','fact_ids':['F1']}],
                'questions':[{'id':'Q1','question':'实际接收哪些数据？','reason':'避免补造范围','fact_ids':['F1']}]}

    def assess(self):
        t=self.prepare();return self.submit(t,self.plan())

    def evidence(self,t):
        return self.submit(t,{'evidence':[{'issue_id':'I1','support':'gap','explanation':'实际数据范围待确认，需核验适用条件。','quotes':[]}]})

    def confirm(self,t):
        return a.web_handle(s,'POST',self.p['id'],t['task_id'],'confirm',{
            'revision':t['revision'],'plan_hash':t['plan_hash'],'confirmed':True,
            'answers':{'Q1':'仅接收业务确认的设备标识；测试答案。'},'confirmed_by':'业务负责人',
            'note':'按本轮变更材料确认，其他事项不推定。'})

    def documents(self,t):
        for doc in ('service','privacy'):
            t=self.submit(t,{'reviews':[],'blockers':[],'changes':[]})
        return t

    def verification(self,t,issue=False):
        fact=t['plan']['facts'][0]['id']
        return {'summary':'受控核验样例，不评价法律质量','checks':[
            {'kind':'facts','status':'pass','document':'both','clause':'整体','excerpt':'',
             'finding':'核对给定事实','fact_ids':[fact],'knowledge_ids':[]},
            {'kind':'evidence','status':'unknown','document':'both','clause':'整体','excerpt':'',
             'finding':'依据适用关系仍需人工核验','fact_ids':[],'knowledge_ids':[]},
            {'kind':'consistency','status':'issue' if issue else 'pass','document':'both','clause':'整体','excerpt':'',
             'finding':'需要进一步核对' if issue else '样例中未提出口径矛盾','fact_ids':[],'knowledge_ids':[]},
            {'kind':'coverage','status':'pass','document':'both','clause':'整体','excerpt':'',
             'finding':'所有给定问题均列出处理结果','fact_ids':[],'knowledge_ids':[]}],
             'coverage':[{'issue_id':i['id'],'document':doc,'disposition':'unchanged','reason':'受控测试：保留正文并记录待决事项。'}
                         for i in t['plan']['issues'] for doc in ('service','privacy')]}

    def revision_to_verify(self):
        self.archive();t=self.evidence(self.assess());self.confirm(t)
        t=a.get(s,t['task_id'],self.owner);return self.documents(t)

    def test_revision_requires_human_and_does_not_write_partial_documents(self):
        self.archive();old=s.get_project(self.p['id'])['draft']['hash'];t=self.assess()
        self.assertEqual(t['stage'],'evidence_review')
        t=self.evidence(t);self.assertEqual(t['status'],'waiting_human')
        with self.assertRaises(s.UserError):self.submit(t,{})
        self.confirm(t);t=a.get(s,t['task_id'],self.owner)
        self.assertEqual(t['stage'],'revise_service');t=self.documents(t)
        self.assertEqual(t['stage'],'verify_bundle')
        self.assertEqual(s.get_project(self.p['id'])['draft']['hash'],old)
        t=self.submit(t,self.verification(t));self.assertEqual(t['status'],'done')
        d=t['project']['draft'];self.assertEqual(d['base_version'],1)
        self.assertTrue(d['provenance']['quality']['warnings']);self.assertEqual(len(t['project']['versions']),1)

    def test_fabricated_fact_quote_cannot_enter_plan(self):
        self.archive();t=self.prepare();value=self.plan();value['facts'][0]['quote']='不存在的已上线功能'
        with self.assertRaises(s.UserError):self.submit(t,value)
        self.assertEqual(a.get(s,t['task_id'],self.owner)['stage'],'assess_change')

    def test_fake_or_unlocated_legal_quotes_rejected(self):
        self.archive();t=self.assess();item=t['knowledge_context']['results'][0]
        value={'evidence':[{'issue_id':'I1','support':'supported','explanation':'受控测试',
               'quotes':[{'knowledge_id':item['id'],'quote':'这不是原文'}]}]}
        with self.assertRaises(s.UserError):self.submit(t,value)
        value['evidence'][0]['quotes'][0]['quote']=item['content'][:20]
        out=self.submit(t,value);self.assertEqual(out['status'],'waiting_human')

    def test_supported_requires_evidence_and_every_issue_is_covered(self):
        self.archive();t=self.assess()
        for rows in ([],[{'issue_id':'I1','support':'supported','explanation':'空依据','quotes':[]}]):
            with self.assertRaises(s.UserError):self.submit(t,{'evidence':rows})

    def test_agent_has_no_human_confirmation_endpoint(self):
        self.archive();t=self.evidence(self.assess())
        with self.assertRaises(s.UserError):b.handle(s,'POST',f"/api/harness/tasks/{t['task_id']}/confirm",{'confirmed':True},self.owner)
        self.assertEqual(a.get(s,t['task_id'],self.owner)['status'],'waiting_human')

    def test_confirmation_is_bound_to_plan_and_project(self):
        self.archive();t=self.evidence(self.assess())
        with self.assertRaises(s.UserError):a.confirm(s,t['task_id'],self.owner,{'revision':t['revision'],'plan_hash':'wrong','confirmed':True})
        with self.assertRaises(s.UserError):a.web_handle(s,'POST',s.create_project('未授权','live')['id'],t['task_id'],'confirm',{})

    def test_knowledge_addition_only_before_generation_and_scope_checked(self):
        self.archive();t=self.assess();item=t['knowledge_context']['results'][0]
        self.assertEqual(a.add_knowledge(s,t['task_id'],self.owner,{'knowledge_ids':[item['id']]})['stage'],'evidence_review')
        t=self.evidence(t)
        with self.assertRaises(s.UserError):a.add_knowledge(s,t['task_id'],self.owner,{'knowledge_ids':[item['id']]})
        with self.assertRaises(s.UserError):a.get(s,t['task_id'],'different-owner')

    def test_restart_and_replayed_stage_preserve_progress(self):
        self.archive();t=self.prepare();plan=self.plan();first=self.submit(t,plan);s.initialize()
        second=self.submit(t,plan);self.assertEqual(first['stage'],second['stage'])
        self.assertEqual(a.get(s,t['task_id'],self.owner)['stage'],'evidence_review')

    def test_project_change_invalidates_run_and_no_stale_commit(self):
        self.archive();t=self.prepare();p=s.get_project(self.p['id']);p['name']='项目已改';s.store(p,p['revision'])
        with self.assertRaises(s.UserError):self.submit(t,self.plan())
        self.assertEqual(a.get(s,t['task_id'],self.owner)['status'],'stale')
        self.assertNotEqual(self.prepare()['task_id'],t['task_id'])

    def test_old_and_new_tasks_cannot_race(self):
        self.archive();self.prepare()
        with self.assertRaises(s.UserError):b.prepare(s,self.p['id'],self.owner,{
            'revision':self.p['revision'],'kind':'revise','change':'改邮箱','confirmation':'确认来源'})

    def test_cross_document_review_and_coverage_cannot_be_skipped(self):
        t=self.revision_to_verify();v=self.verification(t)
        v['checks']=v['checks'][:1]
        with self.assertRaises(s.UserError):self.submit(t,v)
        v=self.verification(t);v['coverage']=v['coverage'][:1]
        with self.assertRaises(s.UserError):self.submit(t,v)
        v=self.verification(t);v['coverage'][0]['disposition']='changed'
        with self.assertRaises(s.UserError):self.submit(t,v)

    def test_verification_quote_and_fact_references_must_exist(self):
        t=self.revision_to_verify();v=self.verification(t);v['checks'][0]['excerpt']='不存在的候选原文'
        with self.assertRaises(s.UserError):self.submit(t,v)
        v=self.verification(t);v['checks'][0]['fact_ids']=['F_missing']
        with self.assertRaises(s.UserError):self.submit(t,v)

    def test_repair_limit_blocks_commit_without_overwriting_archive(self):
        t=self.revision_to_verify();old=s.version(self.p['id'],1)['hash']
        for i in range(3):
            t=self.submit(t,self.verification(t,True))
            if i==2:break
            self.assertEqual(t['stage'],'repair_bundle')
            t=self.submit(t,{'service_changes':[],'privacy_changes':[],'summary':'受控空修复，验证上限'})
        self.assertEqual(t['status'],'blocked');self.assertEqual(t['repair_count'],2)
        self.assertEqual(s.get_project(self.p['id'])['draft']['hash'],old)

    def test_repair_patch_is_located_and_internal_ids_stay_outside_body(self):
        t=self.revision_to_verify();t=self.submit(t,self.verification(t,True))
        patchrow={'clause':'测试','before':'不存在的原文','after':'新文','reason':'测试','action':'核对',
                  'issue_ids':['I1'],'fact_ids':['F1'],'knowledge_ids':[]}
        with self.assertRaises(s.UserError):self.submit(t,{'service_changes':[patchrow],'privacy_changes':[],'summary':'修复'})
        patchrow['after']='[K:internal]'
        with self.assertRaises(s.UserError):q.validate_changes([patchrow],{'plan':t['plan'],'knowledge':{'results':[]}})

    def test_final_commit_rolls_back_and_can_be_retried(self):
        t=self.revision_to_verify();v=self.verification(t);old=s.get_project(self.p['id'])['revision'];real=s.store
        def fail(*args,**kwargs):real(*args,**kwargs);raise RuntimeError('controlled interruption')
        with patch.object(s,'store',side_effect=fail):
            with self.assertRaises(RuntimeError):self.submit(t,v)
        self.assertEqual(s.get_project(self.p['id'])['revision'],old)
        self.assertEqual(a.get(s,t['task_id'],self.owner)['stage'],'verify_bundle')
        done=self.submit(t,v);again=self.submit(t,v)
        self.assertEqual(done['project']['revision'],again['project']['revision'])

    def test_draft_also_requires_final_verification(self):
        t=self.prepare('draft');raw=s.seed()['draft']
        t=self.submit(t,{'evidence':[{'issue_id':i['id'],'support':'gap','explanation':'受控测试待核对','quotes':[]} for i in t['plan']['issues']]})
        for doc in ('service','privacy'):t=self.submit(t,{'document':raw[doc],'reviews':[],'blockers':[]})
        self.assertIsNone(s.get_project(self.p['id'])['draft'])
        self.assertEqual(t['stage'],'verify_bundle')
        self.assertEqual(self.submit(t,self.verification(t))['status'],'done')

    def test_initial_draft_can_repair_using_its_fact_and_issue_registry(self):
        t=self.prepare('draft');raw=s.seed()['draft']
        t=self.submit(t,{'evidence':[{'issue_id':i['id'],'support':'gap','explanation':'受控测试待核对','quotes':[]} for i in t['plan']['issues']]})
        for doc in ('service','privacy'):t=self.submit(t,{'document':raw[doc],'reviews':[],'blockers':[]})
        t=self.submit(t,self.verification(t,True));before=raw['service'].splitlines()[0]
        fix={'clause':'首段','before':before,'after':before+'（样例修复）','reason':'受控核验','action':'核对',
             'issue_ids':['I1'],'fact_ids':[t['plan']['facts'][0]['id']],'knowledge_ids':[]}
        t=self.submit(t,{'service_changes':[fix],'privacy_changes':[],'summary':'修复初稿'})
        v=self.verification(t);v['coverage'][0]['disposition']='changed'
        self.assertEqual(self.submit(t,v)['status'],'done')

    def test_real_patch_then_repair_preserves_history_and_audits_both_edits(self):
        self.archive();old=s.version(self.p['id'],1);t=self.evidence(self.assess());self.confirm(t)
        t=a.get(s,t['task_id'],self.owner);before=old['draft']['service'].splitlines()[0]
        self.assertEqual(old['draft']['service'].count(before),1)
        patchrow={'clause':'S-01','before':before,'after':before+'（候选调整）','reason':'受控变更','action':'法务复核',
                  'issue_ids':['I1'],'fact_ids':['F1'],'knowledge_ids':[]}
        t=self.submit(t,{'reviews':[],'blockers':[],'changes':[patchrow]})
        t=self.submit(t,{'reviews':[],'blockers':[],'changes':[]})
        t=self.submit(t,self.verification(t,True))
        repair={**patchrow,'before':patchrow['after'],'after':before+'（复核后的调整）'}
        t=self.submit(t,{'service_changes':[repair],'privacy_changes':[],'summary':'修正候选措辞'})
        v=self.verification(t);v['coverage'][0]['disposition']='changed'
        done=self.submit(t,v);draft=done['project']['draft']
        self.assertIn('复核后的调整',draft['service']);self.assertEqual(len(draft['changes']),2)
        self.assertEqual(draft['provenance']['quality']['candidate_hash'],s.doc_hash(draft))
        self.assertEqual(s.version(self.p['id'],1)['hash'],old['hash'])

    def test_cancel_preserves_current_draft_and_list_is_scoped(self):
        self.archive();old=s.get_project(self.p['id'])['draft'];t=self.prepare()
        self.assertFalse(a.list_runs(s,None,'other-owner')['tasks'])
        self.assertEqual(len(a.list_runs(s,None,self.owner)['tasks']),1)
        self.assertTrue(a.cancel(s,t['task_id'],self.owner)['cancelled'])
        self.assertEqual(s.get_project(self.p['id'])['draft'],old)

    def test_full_tail_and_mixed_scenarios_are_in_retrieval(self):
        p={**self.p,'material':'平台提供正版短剧播放。'+'常规描述。'*4000+'用户支持声音克隆与文生视频。'}
        snap=k.snapshot(s,p,'analyze',{},self.owner)
        self.assertEqual(snap['scenario'],'all');self.assertGreater(len(snap['queries']),1)
        self.assertTrue(any('声音克隆' in i['content'] or '声音' in i['title'] for i in snap['results']))


if __name__=='__main__':unittest.main()
