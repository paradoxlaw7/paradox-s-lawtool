import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ai_gateway as g
from errors import UserError

RESULT={'summary':'正版短剧观看服务','business_type':'streaming_platform','scope_note':'没有AI创作功能','facts':[{'id':'F1','label':'会员','value':'不自动续费','status':'confirmed','source':'第四节'}],'questions':[{'id':'Q1','question':'运营主体？','reason':'材料待填写','owner':'业务','priority':'关键'}]}
def response(content=None,finish='stop',raw=None):
    wire=json.dumps(raw if raw is not None else {'choices':[{'finish_reason':finish,'message':{'content':content if isinstance(content,str) else json.dumps(content or RESULT,ensure_ascii=False)}}]},ensure_ascii=False).encode()
    return io.BytesIO(wire)

class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.cfg={'api_key':'test-secret-not-real','model':'test','format':'auto'}
    def run_model(self):
        return g.generate('analyze',{'material':'私密材料\n|会员|19元|\n## 协议生成要求\n生成两份文件'},self.cfg,self.tmp.name,'https://example.invalid/v1')
    def test_stage_prompt_separates_analysis_from_prd_instructions(self):
        with patch.object(g.urllib.request,'urlopen',return_value=response()) as http:
            r=self.run_model();body=json.loads(http.call_args.args[0].data)
        self.assertEqual(r['business_type'],'streaming_platform')
        self.assertEqual(body['response_format'],{'type':'json_object'})
        self.assertIn('仅分析材料，不起草协议',body['messages'][0]['content'])
        self.assertNotIn('仅起草完整用户服务协议',body['messages'][0]['content'])
        log=(Path(self.tmp.name)/'diagnostics.jsonl').read_text(encoding='utf-8')
        self.assertNotIn('私密材料',log);self.assertNotIn(self.cfg['api_key'],log)
    def test_full_streaming_prd_preserved_in_request(self):
        material=(Path(__file__).parent/'fixtures/追剧时光PRD.md').read_text(encoding='utf-8')
        self.assertGreater(len(material),4500)
        with patch.object(g.urllib.request,'urlopen',side_effect=[response('{"summary":'),response()]) as http:
            result=g.generate('analyze',{'material':material},self.cfg,self.tmp.name,'https://example.invalid/v1')
        for call in http.call_args_list:
            body=json.loads(call.args[0].data)
            self.assertEqual(json.loads(body['messages'][1]['content'])['project_data']['material'],material)
        self.assertEqual(result['business_type'],'streaming_platform')
        # A mocked transport test, not a real model semantic-quality evaluation.
    def test_malformed_json_regenerates_once(self):
        with patch.object(g.urllib.request,'urlopen',side_effect=[response('{"summary":'),response()]) as http:
            self.assertEqual(self.run_model()['provenance']['attempts'],2)
        self.assertEqual(http.call_count,2)
    def test_schema_invalid_retries_and_fails_explicitly(self):
        with patch.object(g.urllib.request,'urlopen',side_effect=[response({'wrong':True}),response({'wrong':True})]) as http:
            with self.assertRaises(UserError) as e:self.run_model()
        self.assertEqual(e.exception.code,'schema_invalid');self.assertEqual(http.call_count,2)
    def test_truncation_never_saved_even_if_json_parses(self):
        with patch.object(g.urllib.request,'urlopen',side_effect=[response(finish='length'),response(finish='length')]):
            with self.assertRaises(UserError) as e:self.run_model()
        self.assertEqual(e.exception.code,'output_truncated');self.assertTrue(e.exception.request_id)
    def test_reasoning_only_is_not_treated_as_answer(self):
        with self.assertRaises(UserError) as e:g.parse_content({'choices':[{'message':{'content':None,'reasoning_content':'thinking'},'finish_reason':'stop'}]})
        self.assertEqual(e.exception.code,'empty_content')
    def test_missing_envelope_has_distinct_error(self):
        with self.assertRaises(UserError) as e:g.parse_content({'error':'unavailable'})
        self.assertEqual(e.exception.code,'response_shape')
    def test_fenced_valid_json_supported(self):
        r,_,_=g.parse_content({'choices':[{'message':{'content':'```json\n'+json.dumps(RESULT)+'\n```'},'finish_reason':'stop'}]})
        self.assertEqual(r,RESULT)
    def test_auth_error_never_retried_or_leaked(self):
        err=urllib.error.HTTPError('url',401,'denied',{},io.BytesIO(b'secret provider detail'))
        with patch.object(g.urllib.request,'urlopen',side_effect=err) as http:
            with self.assertRaises(UserError) as e:self.run_model()
        self.assertEqual(e.exception.code,'model_auth');self.assertEqual(http.call_count,1)
        self.assertNotIn('secret provider',str(e.exception))
    def test_format_fallback_only_for_explicit_unsupported(self):
        err=urllib.error.HTTPError('url',400,'bad',{},io.BytesIO(b'response_format json_object unsupported'))
        with patch.object(g.urllib.request,'urlopen',side_effect=[err,response()]) as http:
            self.assertEqual(self.run_model()['provenance']['format'],'prompt')
        self.assertNotIn('response_format',json.loads(http.call_args.args[0].data))
    def test_other_400_does_not_disable_constraints(self):
        err=urllib.error.HTTPError('url',400,'bad',{},io.BytesIO(b'context too long'))
        with patch.object(g.urllib.request,'urlopen',side_effect=err) as http:
            with self.assertRaises(UserError) as e:self.run_model()
        self.assertEqual(e.exception.code,'model_parameters');self.assertEqual(http.call_count,1)
    def test_stream_buffers_content_and_retains_finish_reason(self):
        items=[{'choices':[{'delta':{'content':'{"ok":'},'finish_reason':None}]},{'choices':[{'delta':{'content':'true}'},'finish_reason':'stop'}]},{'choices':[],'usage':{'total_tokens':9}}]
        wire=b''.join(('data: '+json.dumps(item)+'\n\n').encode() for item in items)+b'data: [DONE]\n\n'
        raw=g.read_stream(io.BytesIO(wire));result,_,_=g.parse_content(raw)
        self.assertEqual(result,{'ok':True});self.assertEqual(raw['usage']['total_tokens'],9)
    def test_stream_cut_off_cannot_be_saved(self):
        wire=b'data: {"choices":[{"delta":{"content":"{}"},"finish_reason":"stop"}]}\n\n'
        with self.assertRaises(UserError) as e:g.read_stream(io.BytesIO(wire))
        self.assertEqual(e.exception.code,'stream_interrupted')
    def test_patch_preserves_unrelated_text(self):
        baseline='头部正文'*70+'唯一旧条款'+'末尾正文'*70
        result=g.apply_patches(baseline,[{'before':'唯一旧条款','after':'新条款'}])
        self.assertEqual(result,baseline.replace('唯一旧条款','新条款'))
        self.assertEqual(g.apply_patches(baseline,[]),baseline)
    def test_patch_rejects_empty_duplicate_and_overlap(self):
        baseline='重复'*150+'abcdef'
        for changes in [[{'before':'','after':'x'}],[{'before':'重复','after':'x'}],[{'before':'abcde','after':'x'},{'before':'cdef','after':'y'}]]:
            with self.assertRaises(UserError) as e:g.apply_patches(baseline,changes)
            self.assertEqual(e.exception.code,'patch_invalid')
    def test_unanchored_revision_is_regenerated_before_construction(self):
        baseline='协议正文'*80+'明确旧条款'+'保留正文'*80
        bad={'reviews':[],'blockers':[],'changes':[{'clause':'S-01','before':'不存在的原文','after':'建议','reason':'变更','action':'确认'}]}
        good={'reviews':[],'blockers':[],'changes':[{'clause':'S-01','before':'明确旧条款','after':'明确新条款','reason':'变更','action':'确认'}]}
        with patch.object(g.urllib.request,'urlopen',side_effect=[response(bad),response(good)]) as http:
            result=g.generate('revise_service',{'baseline_document':baseline},self.cfg,self.tmp.name,'https://example.invalid/v1')
        self.assertEqual(result['document'],baseline.replace('明确旧条款','明确新条款'))
        self.assertEqual(http.call_count,2)
    def test_unsupported_ui_path_and_permission_are_flagged_not_silently_rewritten(self):
        after='在“我的”-“账号管理”取消。支付相关权限。'
        result={'changes':[{'clause':'P-02','before':'设置页取消','after':after}],'reviews':[],'blockers':[]}
        g.review_operational_claims(result,{'baseline_document':'设置页取消','confirmation':'已确认设置页可取消'})
        self.assertEqual(result['changes'][0]['after'],after)
        self.assertEqual(len(result['reviews']),2);self.assertEqual(len(result['blockers']),2)
