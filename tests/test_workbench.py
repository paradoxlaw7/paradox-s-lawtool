import base64
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as s
from documents import word_document

class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        p=patch.object(s,'DB',Path(self.tmp.name)/'test.db');p.start();self.addCleanup(p.stop)
        s.initialize();self.p=s.create_project('工作台测试','demo')
    def act(self,a,**kw):
        self.p=s.perform(self.p['id'],a,{'revision':self.p['revision'],**kw});return self.p
    def prepare(self):
        self.act('analyze');self.act('answers',answers=s.seed()['answers'],confirmed_by='业务负责人');self.act('draft')
    def test_import_original_is_preserved_after_edit(self):
        blob='# 原件\n文本'.encode()
        self.act('import',name='prd.md',relative_path='业务/prd.md',content=base64.b64encode(blob).decode())
        f=self.p['files'][0];self.act('fileedit',id=f['id'],text='改写后的正文')
        with s.connect() as c:saved=c.execute('SELECT body FROM imported_files WHERE id=?',(f['id'],)).fetchone()[0]
        self.assertEqual(saved,blob);self.assertEqual(self.p['files'][0]['text'],'改写后的正文')
    def test_invalid_import_path_is_rejected(self):
        with self.assertRaises(s.UserError):self.act('import',name='a.md',relative_path='../a.md',content=base64.b64encode(b'text').decode())
        self.assertEqual(s.get_project(self.p['id'])['files'],[])
    def test_partial_generation_does_not_save_half_draft(self):
        self.act('analyze');self.act('answers',answers=s.seed()['answers'],confirmed_by='业务')
        self.p['mode']='live';self.p=s.store(self.p,self.p['revision'])
        one={'document':'有效正文'*100,'reviews':[],'blockers':[],'provenance':{'kind':'live'}}
        with patch.object(s.ai_gateway,'generate',side_effect=[one,s.UserError('截断',502,'output_truncated')]) as model:
            with self.assertRaises(s.UserError):self.act('draft')
        self.assertIsNone(s.get_project(self.p['id'])['draft'])
        self.assertEqual([c.args[0] for c in model.call_args_list],['draft_service','draft_privacy'])
    def test_proposal_requires_acceptance_and_rejects_stale_text(self):
        self.prepare();self.p['mode']='live';self.p=s.store(self.p,self.p['revision'])
        before=self.p['draft']['service'];anchor=before[:70]
        result={'answer':'建议如下','proposal':{'document':'service','before':anchor,'after':'新条款','reason':'明确范围'}}
        with patch.object(s,'call_model',return_value=result):self.act('chat',message='请修改',document='service')
        self.assertEqual(self.p['draft']['service'],before)
        mid=self.p['messages'][-1]['id']
        self.act('edit',service=before+'\n补充',privacy=self.p['draft']['privacy'])
        with self.assertRaises(s.UserError):self.act('applyproposal',id=mid)
    def test_proposal_can_be_applied_only_once(self):
        self.prepare();self.p['mode']='live';self.p=s.store(self.p,self.p['revision'])
        result={'answer':'建议','proposal':{'document':'privacy','before':self.p['draft']['privacy'][:60],'after':'替换段落','reason':'业务确认'}}
        with patch.object(s,'call_model',return_value=result):self.act('chat',message='请修改',document='privacy')
        mid=self.p['messages'][-1]['id'];self.act('applyproposal',id=mid)
        self.assertTrue(self.p['draft']['privacy'].startswith('替换段落'))
        with self.assertRaises(s.UserError):self.act('applyproposal',id=mid)
    def test_proposal_cannot_modify_another_context_document(self):
        self.prepare();self.p['mode']='live';self.p=s.store(self.p,self.p['revision'])
        result={'answer':'建议','proposal':{'document':'privacy','before':self.p['draft']['privacy'][:60],'after':'越界修改','reason':'测试'}}
        with patch.object(s,'call_model',return_value=result):
            with self.assertRaises(s.UserError) as err:self.act('chat',message='核对材料',document='material')
        self.assertEqual(err.exception.code,'proposal_unanchored')
        self.assertEqual(s.get_project(self.p['id'])['messages'],[])
    def test_jobs_persist_duplicate_guard_and_restart(self):
        with patch.object(s.EXECUTOR,'submit'):
            j=s.submit_job(self.p['id'],'analyze',{'revision':self.p['revision']})
            with self.assertRaises(s.UserError):s.submit_job(self.p['id'],'analyze',{'revision':self.p['revision']})
        self.assertEqual(s.project_jobs(self.p['id'])[0]['id'],j['id'])
        s.recover_jobs();self.assertEqual(s.project_jobs(self.p['id'])[0]['error_code'],'server_restarted')
    def test_job_runs_and_saves_without_browser_waiting(self):
        with patch.object(s.EXECUTOR,'submit'):j=s.submit_job(self.p['id'],'analyze',{'revision':self.p['revision']})
        s.run_job(j['id'])
        self.assertEqual(s.project_jobs(self.p['id'])[0]['status'],'done')
        self.assertIsNotNone(s.get_project(self.p['id'])['analysis'])
    def test_docx_export_has_valid_xml_and_roundtrip_text(self):
        b=word_document('# 服务协议\n\n**重要提示**\n\n中文 & <条款>')
        with zipfile.ZipFile(io.BytesIO(b)) as z:
            for name in z.namelist():
                if name.endswith('.xml'):ET.fromstring(z.read(name))
            self.assertIn(b'<w:b',z.read('word/document.xml'))
        out=s.extract_upload({'name':'协议.docx','content':base64.b64encode(b).decode()})
        self.assertIn('服务协议',out['text']);self.assertIn('中文 & <条款>',out['text'])
    def test_markdown_import_creates_real_word_copy(self):
        self.act('import',name='prd.md',content=base64.b64encode('# PRD\n正文内容'.encode()).decode())
        f=self.p['files'][0];self.assertEqual(f['display_name'],'prd.docx')
        with zipfile.ZipFile(io.BytesIO(s.native_document(self.p['id'],'file_'+f['id']))) as z:self.assertIn('word/document.xml',z.namelist())
    def test_reimported_word_bytes_and_archive_are_preserved(self):
        self.prepare();blob=word_document('# 服务协议\n\n**人工审阅定稿**\n内容。')
        self.act('wordreplace',slot='service',name='审阅稿.docx',content=base64.b64encode(blob).decode())
        self.assertEqual(s.native_document(self.p['id'],'service'),blob)
        self.act('archive',hash=self.p['draft']['hash'],confirmed=True,approver='测试',note='测试归档')
        self.assertEqual(s.native_document(self.p['id'],'service',1),blob)
        with self.assertRaises(s.UserError):self.act('wordreplace',slot='service',name='稿.docx',content=base64.b64encode(blob).decode())
