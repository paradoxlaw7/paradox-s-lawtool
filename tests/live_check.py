"""Manual live validation. Credential entered invisibly, never saved to a file."""
import getpass, json, sys, time, urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server as s
out=s.ROOT/'test-results/live';out.mkdir(parents=True,exist_ok=True)
key=getpass.getpass('SiliconFlow credential (hidden): ')
if not key:raise SystemExit('No credential supplied')
s.CONFIG.update(api_key=key,format='auto')
key=None
try:
    request=urllib.request.Request('http://127.0.0.1:8766/api/config',data=json.dumps({'api_key':s.CONFIG['api_key'],'model':s.CONFIG['model'],'format':'auto'}).encode(),headers={'Content-Type':'application/json','X-Workspace-Request':'1'})
    with urllib.request.urlopen(request,timeout=10):pass
    print('Local workbench model configured in memory.',flush=True)
except OSError:print('Local workbench was not configured; standalone checks continue.',flush=True)
report={'model':s.CONFIG['model'],'steps':[]}
def run(stage,payload):
    started=time.monotonic();print('Running '+stage,flush=True)
    try:
        r=s.call_model(stage,payload)
        (out/(stage+'.json')).write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
        item={'stage':stage,'ok':True,'seconds':round(time.monotonic()-started,1),'business_type':r.get('business_type'),'questions':len(r.get('questions',[])),'service_chars':len(r.get('service','')),'privacy_chars':len(r.get('privacy',''))}
        report['steps'].append(item);print(json.dumps(item,ensure_ascii=False),flush=True);return r
    except s.UserError as e:
        item={'stage':stage,'ok':False,'code':e.code,'request_id':e.request_id,'seconds':round(time.monotonic()-started,1)}
        report['steps'].append(item);print(json.dumps(item),flush=True);return None
    finally:(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
material=(Path(__file__).parent/'fixtures/追剧时光PRD.md').read_text(encoding='utf-8')
saved=out/'analyze.json'
analysis=json.loads(saved.read_text(encoding='utf-8')) if '--resume' in sys.argv and saved.exists() else run('analyze',{'material':material,'source_name':'追剧时光PRD.docx'})
if '--resume' in sys.argv:report['resumed_analysis']=True
if analysis:
    # Deliberately unanswered items remain placeholders; no fictitious legal approval.
    answers={q['id']:'测试材料尚未确认此项。请保留明确待确认占位，不得编造事实。' for q in analysis['questions']}
    saved_draft=out/'draft.json'
    draft=json.loads(saved_draft.read_text(encoding='utf-8')) if '--revise-only' in sys.argv and saved_draft.exists() else run('draft',{'material':material,'analysis':analysis,'answers':answers})
    if draft:
        if '--revise-only' not in sys.argv:run('chat',{'message':'请检查协议是否错误引入自动续费或AI模型训练。只回答，不修改。','document':'service','current_document':draft['service'],'material':material,'analysis':analysis,'answers':answers,'editable':True,'selection':'','history':[]})
        baseline={'draft':draft,'material':material,'analysis':analysis,'answers':answers}
        run('revise',{'baseline':baseline,'change':'已实现会员自动续费；仅对用户主动另行选择开通的会员生效，原一次性会员不自动转换。需要同步更新协议。','confirmation':'仅为离线验收假设，不是业务或法务定稿：每次扣费前5日提醒；用户可在设置页取消，取消后当前周期可继续使用。渠道及首次独立授权页面需保留待确认。'})
print('Live check finished; no credential stored.',flush=True)
