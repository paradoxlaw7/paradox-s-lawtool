import base64
import io
import json
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as s


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.dbpatch=patch.object(s,'DB',Path(self.temp.name)/'test.sqlite3');self.dbpatch.start();self.addCleanup(self.dbpatch.stop)
        s.initialize()
        self.p=s.create_project('测试项目','demo')
    def act(self,a,**kw):
        self.p=s.perform(self.p['id'],a,{'revision':self.p['revision'],**kw});return self.p
    def prepare(self):
        self.act('analyze');self.act('answers',answers=s.seed()['answers'],confirmed_by='模拟业务');self.act('draft')
    def archive(self):
        self.act('archive',hash=self.p['draft']['hash'],confirmed=True,approver='模拟法务',note='测试审批，非真实法务意见')
    def test_complete_lifecycle_and_baseline_preserved(self):
        self.prepare()
        self.act('edit',service=self.p['draft']['service']+'\n\n额外的模拟法务保留条款。',privacy=self.p['draft']['privacy'])
        self.archive();old=s.version(self.p['id'],1)
        self.act('revise',change=s.seed()['change_input'],confirmation=s.seed()['change_confirmation'])
        self.assertIn('额外的模拟法务保留条款',self.p['draft']['service'])
        self.assertEqual(s.version(self.p['id'],1)['hash'],old['hash'])
        self.assertIn('support@example.com',self.p['draft']['service'])
        self.assertNotIn('legal@example.com',self.p['draft']['privacy'])
        self.assertEqual(len(self.p['draft']['changes']),6)
        self.archive()
        self.assertEqual(len(self.p['versions']),2)
        self.assertTrue(s.version(self.p['id'],2)['integrity'])
    def test_approval_is_bound_to_exact_text(self):
        self.prepare();oldhash=self.p['draft']['hash']
        self.act('edit',service=self.p['draft']['service']+'\n修改',privacy=self.p['draft']['privacy'])
        with self.assertRaises(s.UserError):self.act('archive',hash=oldhash,confirmed=True,approver='法务',note='已审')
        self.assertFalse(s.get_project(self.p['id'])['versions'])
    def test_confirmation_and_no_duplicate_archive(self):
        self.prepare()
        with self.assertRaises(s.UserError):self.act('archive',hash=self.p['draft']['hash'],confirmed=False,approver='法务',note='已阅')
        self.archive()
        with self.assertRaises(s.UserError):self.archive()
        with self.assertRaises(sqlite3.IntegrityError):
            with s.connect() as c:c.execute('UPDATE versions SET snapshot=? WHERE project_id=?',('{}',self.p['id']))
    def test_stale_revision_rejected(self):
        old=self.p['revision'];self.act('analyze')
        with self.assertRaises(s.UserError):s.perform(self.p['id'],'analyze',{'revision':old})
    def test_demo_cannot_masquerade_as_custom_analysis(self):
        self.act('material',material='自定义实际业务材料',source_name='测试')
        with self.assertRaises(s.UserError):self.act('analyze')
    def test_no_key_does_not_fall_back_to_fake_ai(self):
        with patch.dict(s.CONFIG,{'api_key':''}):
            with self.assertRaises(s.UserError):s.call_model('analyze',{'material':'测试'})
    def test_openai_compatible_request_and_provenance(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps({'choices':[{'message':{'content':json.dumps(s.seed()['analysis'],ensure_ascii=False)},'finish_reason':'stop'}],'usage':{'total_tokens':100}}).encode()
        with patch.dict(s.CONFIG,{'api_key':'fictional-test-key','model':'test-model'}),patch.object(s.urllib.request,'urlopen',return_value=Response()) as http:
            result=s.call_model('analyze',{'material':'虚构测试'})
            request=http.call_args.args[0]
            self.assertEqual(request.full_url,'https://api.siliconflow.cn/v1/chat/completions')
            self.assertEqual(json.loads(request.data)['model'],'test-model')
            self.assertEqual(result['provenance']['kind'],'live')
            self.assertEqual(result['provenance']['usage']['total_tokens'],100)
    def test_incomplete_model_output_rejected(self):
        with self.assertRaises(s.UserError):s.validate_result({'service':'short','privacy':'short'},'draft')
    def test_word_text_extract(self):
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>测试材料</w:t></w:r></w:p></w:body></w:document>')
        result=s.extract_upload({'name':'虚构PRD.docx','content':base64.b64encode(buf.getvalue()).decode()})
        self.assertEqual(result['text'],'测试材料')
    def test_review_conclusion_persists(self):
        self.prepare();self.archive();r=self.p['reviews'][0]
        nd=(s.date.today()+s.timedelta(days=60)).isoformat()
        self.act('review',id=r['id'],resolution='模拟研发确认未变化，依据配置清单',next_due=nd)
        self.assertEqual(self.p['reviews'][0]['due'],nd)
        self.assertEqual(len(self.p['reviews'][0]['history']),1)


if __name__=='__main__':unittest.main(verbosity=2)
