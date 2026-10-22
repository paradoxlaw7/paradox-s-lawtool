"""Transport/evidence correctness and small retrieval regression cases, not model-quality scores."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as s
import knowledge as k
import harness_bridge as b


def candidate(**changes):
    return dict(title='内部审核规则：声音授权核实',kind='playbook',content='声音克隆前核对授权主体、范围和期限。',
        applicability='用户提供真人声音用于合成',exclusions='普通音轨播放不适用',source_url='',
        locator='内部指引第3页',publisher='法务团队',checked_on='2026-10-21',effective_on='',valid_until='',
        legal_status='not_applicable',scenarios=['ai_generation'],tags=['声音克隆'],**changes)


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        p=patch.object(s,'DB',Path(folder.name)/'workspace.sqlite3');p.start();self.addCleanup(p.stop)
        p=patch.object(s,'call_model',side_effect=AssertionError('knowledge must not call model'));self.model=p.start();self.addCleanup(p.stop)
        s.initialize();self.owner='owner-one'
    def approve(self,item,decision='approve',**extra):
        return k.review(s,item['id'],dict(revision=item['revision'],decision=decision,
                        reviewer='法务测试',note='核验原件和适用条件',confirmed=True,**extra))
    def task(self):
        p=b.handle(s,'POST','/api/harness/projects',{'name':'知识回归项目'},self.owner)['project']
        p=b.handle(s,'POST',f"/api/harness/projects/{p['id']}/material",{
            'revision':p['revision'],'material':'正版短剧付费观看和播放服务。不提供AI生成、声音克隆。'},self.owner)['project']
        t=b.prepare(s,p['id'],self.owner,{'revision':p['revision'],'kind':'analyze'})
        return p,t
    def test_seeds_are_versioned_and_initialization_does_not_revert_retirement(self):
        items=k.entries(s);self.assertEqual(len(items),15)
        self.approve(items[0],'retire');s.initialize()
        self.assertEqual(k.get(s,items[0]['id'])['state'],'retired')
    def test_pending_never_enters_retrieval_and_requires_human_review(self):
        item=k.propose(s,candidate(),self.owner)
        self.assertNotIn(item['id'],[i['id'] for i in k.search(s,'声音授权',self.owner)['results']])
        with self.assertRaises(s.UserError):k.review(s,item['id'],{'confirmed':False})
        self.approve(item)
        self.assertIn(item['id'],[i['id'] for i in k.search(s,'内部声音授权',self.owner,limit=12)['results']])
    def test_agent_cannot_approve_or_forge_approval_fields(self):
        item=k.propose(s,candidate(),self.owner)
        with self.assertRaises(s.UserError):b.handle(s,'POST',f"/api/harness/knowledge/{item['id']}/review",{'confirmed':True},self.owner)
        value=candidate();value['state']='active'
        with self.assertRaises(s.UserError):k.propose(s,value,self.owner)
    def test_owner_isolation_and_web_shared_reference(self):
        item=self.approve(k.propose(s,candidate(),self.owner))
        with self.assertRaises(s.UserError):k.get(s,item['id'],'other')
        self.assertNotIn(item['id'],[i['id'] for i in k.search(s,'声音授权','other',limit=12)['results']])
        shared=k.handle(s,'POST','/api/knowledge/propose',candidate());self.approve(shared)
        self.assertIn(shared['id'],[i['id'] for i in k.search(s,'声音授权','other',limit=12)['results']])
    def test_draft_unknown_and_superseded_cannot_be_approved_as_authority(self):
        for effect in ('draft','unknown','superseded'):
            data=candidate();data['legal_status']=effect
            item=k.propose(s,data,self.owner)
            with self.assertRaises(s.UserError):self.approve(item)
    def test_law_cannot_bypass_effect_check_using_not_applicable(self):
        data=candidate();data.update(kind='legislation',source_url='https://example.com/law')
        with self.assertRaises(s.UserError):self.approve(k.propose(s,data,self.owner))
    def test_future_expired_and_retired_are_excluded(self):
        for begin,end in [('2099-01-01',''),('','2026-01-01')]:
            data=candidate();data.update(effective_on=begin,valid_until=end)
            item=self.approve(k.propose(s,data,self.owner))
            self.assertNotIn(item['id'],[i['id'] for i in k.search(s,'声音克隆',self.owner,limit=12)['results']])
        item=self.approve(k.propose(s,candidate(),self.owner));self.approve(item,'retire')
        self.assertNotIn(item['id'],[i['id'] for i in k.search(s,'声音克隆',self.owner,limit=12)['results']])
    def test_optimistic_review_does_not_overwrite_a_previous_decision(self):
        item=k.propose(s,candidate(),self.owner);self.approve(item)
        with self.assertRaises(s.UserError):self.approve(item)
    def test_urls_dates_and_candidate_size_are_validated(self):
        for key,value in [('source_url','javascript:alert(1)'),('source_url','https://u:p@example.com'),
                          ('checked_on','2099-01-01'),('content','x'*6001),('scenarios',['other'])]:
            data=candidate();data[key]=value
            with self.assertRaises(s.UserError):k.propose(s,data,self.owner)
    def test_retrieval_regression_cases(self):
        cases=json.loads((Path(__file__).parent/'fixtures/knowledge_eval.json').read_text(encoding='utf-8'))
        for case in cases:
            with self.subTest(query=case['query']):
                out=k.search(s,case['query'],self.owner,case['scenario'],6)
                ids={i['id'] for i in out['results']}
                self.assertTrue(set(case['expected_any'])&ids)
                self.assertFalse(set(case.get('forbidden',[]))&ids)
    def test_explicit_negation_does_not_turn_playback_into_generation(self):
        prd=(Path(__file__).parent/'fixtures/追剧时光PRD.md').read_text(encoding='utf-8')
        self.assertEqual(k.scenario_hint(prd),'streaming')
        self.assertEqual(k.scenario_hint('短剧播放；不提供AI生成或语音克隆'),'streaming')
        self.assertEqual(k.scenario_hint('新增声音克隆功能'),'ai_generation')
    def test_task_has_frozen_references_and_records_exact_hashes(self):
        p,t=self.task();snap=copy.deepcopy(t['knowledge_context']);self.assertTrue(snap['results'])
        self.assertEqual(snap['scenario'],'streaming')
        self.assertNotIn('law_gen_scope_20261021',[i['id'] for i in snap['results']])
        self.approve(snap['results'][0],'retire')
        again=b.prepare(s,p['id'],self.owner,{'revision':p['revision'],'kind':'analyze'})
        self.assertEqual(again['task_id'],t['task_id']);self.assertEqual(again['knowledge_context'],snap)
        raw=copy.deepcopy(s.seed()['analysis']);raw.pop('provenance',None)
        out=b.submit(s,t['task_id'],self.owner,{'stage':'analyze','result':raw})
        self.assertEqual(out['project']['analysis']['provenance']['knowledge'],snap)
        self.model.assert_not_called()
    def test_extra_references_must_be_approved_and_scoped(self):
        item=k.propose(s,candidate(),self.owner)
        with self.assertRaises(s.UserError):k.snapshot(s,{'material':'声音克隆'},'analyze',{'knowledge_ids':[item['id']]},self.owner)
        active=self.approve(item)
        snap=k.snapshot(s,{'material':'短剧播放'},'analyze',{'knowledge_ids':[active['id']]},self.owner)
        self.assertIn(active['id'],[i['id'] for i in snap['results']])
    def test_unknown_citations_reject_without_project_change(self):
        p,t=self.task();raw=copy.deepcopy(s.seed()['analysis']);raw.pop('provenance',None)
        raw['scope_note']='[K:invented@123456abcdef]'
        with self.assertRaises(s.UserError):b.submit(s,t['task_id'],self.owner,{'stage':'analyze','result':raw})
        self.assertIsNone(s.get_project(p['id'])['analysis'])
    def test_internal_citations_are_not_written_into_user_document(self):
        snap=k.search(s,'个人信息');citation=snap['results'][0]['citation']
        with self.assertRaises(s.UserError):k.check_citations({'document':'正文 '+citation},snap)
    def test_empty_search_returns_no_match_and_not_fabricated_authority(self):
        out=k.search(s,'zxqv1902387');self.assertTrue(out['no_match']);self.assertFalse(out['results'])
    def test_audit_retains_review_but_not_raw_prd_query(self):
        item=k.propose(s,candidate(),self.owner);self.approve(item)
        k.search(s,'保密PRD-abc-984123',self.owner)
        with s.connect() as c:
            rows=c.execute('SELECT * FROM knowledge_events').fetchall()
        self.assertTrue(any(r['event']=='approve' for r in rows))
        self.assertFalse(any('保密PRD' in r['payload'] for r in rows))


if __name__=='__main__':unittest.main()
