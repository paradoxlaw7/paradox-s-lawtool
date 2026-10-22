"""Single-user agreement workspace. Python 3.11+, standard library only."""
import base64, hashlib, hmac, io, json, os, re, secrets, sqlite3, sys, threading, time, zipfile
import urllib.request, urllib.error
from datetime import datetime, timedelta, timezone, date
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from difflib import unified_diff
import ai_gateway
import harness_bridge
import knowledge
import agent_tasks
from documents import word_document
from errors import UserError

ROOT = Path(__file__).resolve().parent
if (ROOT/'.env').exists():
    for line in (ROOT/'.env').read_text(encoding='utf-8-sig').splitlines():
        if '=' in line and not line.strip().startswith('#'):
            k,v=line.split('=',1); os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))
DATA=Path(os.environ.get('DATA_DIR',str(ROOT/'data'))); DATA.mkdir(parents=True,exist_ok=True)
DB=DATA/'workspace.sqlite3'
HOST=os.environ.get('HOST','127.0.0.1'); PORT=int(os.environ.get('PORT','8765'))
PASSWORD=os.environ.get('APP_PASSWORD',''); ORIGIN=os.environ.get('PUBLIC_ORIGIN','').rstrip('/')
RENDER_HOST=os.environ.get('RENDER_EXTERNAL_HOSTNAME','').strip().lower().rstrip('.')
CONFIG={'api_key':os.environ.get('SILICONFLOW_API_KEY',''),'model':os.environ.get('AI_MODEL','deepseek-ai/DeepSeek-V3.2'),'format':os.environ.get('AI_RESPONSE_FORMAT','auto'),'stream':os.environ.get('AI_STREAM','true').lower()=='true'}
HARNESS_TOKEN=os.environ.get('HARNESS_ACCESS_TOKEN','')
API_BASE='https://api.siliconflow.cn/v1'
SESSIONS={}; LOGIN_ATTEMPTS={}; AI_LOCK=threading.BoundedSemaphore(2)
JOB_LOCAL=threading.local()


def canonical_redirect_target(host,target):
    """Redirect only this service's Render alias to its configured HTTPS origin."""
    if not ORIGIN or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.onrender\.com',RENDER_HOST):return None
    try:
        canonical=urlparse(ORIGIN)
        incoming=urlparse('//'+(host or ''))
        if (canonical.scheme!='https' or not canonical.hostname or canonical.username is not None
            or canonical.password is not None or canonical.path not in ('','/') or canonical.query or canonical.fragment):return None
        if (incoming.hostname!=RENDER_HOST or incoming.port not in (None,443) or incoming.username is not None
            or incoming.password is not None or incoming.path or incoming.query or incoming.fragment):return None
        if canonical.hostname.lower().rstrip('.')==RENDER_HOST:return None
    except ValueError:return None
    parsed=urlparse(target)
    path=parsed.path or '/'
    if not path.startswith('/') or path.startswith(('//','/\\')):path='/'
    return ORIGIN.rstrip('/')+path+('?' + parsed.query if parsed.query else '')


def now(): return datetime.now(timezone.utc).isoformat()
def dumps(v): return json.dumps(v,ensure_ascii=False,separators=(',',':'))
def doc_hash(d): return hashlib.sha256(dumps({'service':d['service'],'privacy':d['privacy']}).encode()).hexdigest()
def seed(): return json.loads((ROOT/'demo.json').read_text(encoding='utf-8'))
def text(v,name,limit=80000):
    if not isinstance(v,str) or not v.strip(): raise UserError('请填写'+name+'。')
    if len(v)>limit: raise UserError(name+'过长，请拆分材料。')
    return v.strip()
@contextmanager
def connect():
    c=sqlite3.connect(DB,timeout=15); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON')
    try:
        with c:yield c
    finally:c.close()
def initialize():
    with connect() as c:
        c.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,payload TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS imported_files(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,name TEXT NOT NULL,body BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS office_documents(project_id TEXT NOT NULL,slot TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 0,body BLOB NOT NULL,text_hash TEXT NOT NULL,PRIMARY KEY(project_id,slot,version));
        CREATE TRIGGER IF NOT EXISTS immutable_office_update BEFORE UPDATE ON office_documents WHEN OLD.version>0 BEGIN SELECT RAISE(ABORT,'immutable office version'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_office_delete BEFORE DELETE ON office_documents WHEN OLD.version>0 BEGIN SELECT RAISE(ABORT,'immutable office version'); END;
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,action TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,error TEXT,error_code TEXT,request_id TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_job ON jobs(project_id) WHERE status IN ('queued','running');
        CREATE TABLE IF NOT EXISTS versions(project_id TEXT NOT NULL,number INTEGER NOT NULL,snapshot TEXT NOT NULL,
          PRIMARY KEY(project_id,number),FOREIGN KEY(project_id) REFERENCES projects(id));
        CREATE TRIGGER IF NOT EXISTS immutable_versions_update BEFORE UPDATE ON versions BEGIN SELECT RAISE(ABORT,'immutable version'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_versions_delete BEFORE DELETE ON versions BEGIN SELECT RAISE(ABORT,'immutable version'); END;''')
        if 'progress' not in [r['name'] for r in c.execute('PRAGMA table_info(jobs)')]:c.execute('ALTER TABLE jobs ADD COLUMN progress TEXT')
        harness_bridge.initialize(c)
        knowledge.initialize(c,now)
        if not c.execute('SELECT 1 FROM projects LIMIT 1').fetchone(): create_project('星幕漫剧工作台','demo',c)
def create_project(name,mode,conn=None):
    name=text(name,'项目名称',80)
    if mode not in ('demo','live'): raise UserError('请选择演示或真实项目。')
    p={'id':secrets.token_hex(8),'name':name,'mode':mode,'stage':0,
       'material':seed()['material'] if mode=='demo' else '', 'source_name':'虚构 PRD' if mode=='demo' else '',
       'files':[],'messages':[],'analysis':None,'answers':{},'draft':None,'versions':[],'reviews':[],
       'events':[{'at':now(),'text':'建立演示项目' if mode=='demo' else '建立真实项目'}]}
    if conn is not None: conn.execute('INSERT INTO projects(id,payload) VALUES(?,?)',(p['id'],dumps(p)))
    else:
        with connect() as c: c.execute('INSERT INTO projects(id,payload) VALUES(?,?)',(p['id'],dumps(p)))
    p['revision']=0; return p
def get_project(pid):
    with connect() as c: row=c.execute('SELECT * FROM projects WHERE id=?',(pid,)).fetchone()
    if not row: raise UserError('项目不存在。',404)
    p=json.loads(row['payload']);p['revision']=row['revision'];return p
def store(p,expected,conn=None):
    clean={k:v for k,v in p.items() if k!='revision'}
    def write(c):
        r=c.execute('UPDATE projects SET payload=?,revision=revision+1 WHERE id=? AND revision=?',(dumps(clean),p['id'],expected))
        if r.rowcount!=1:raise UserError('项目已在其他窗口更新，请刷新后重试。',409)
    if conn is not None:write(conn)
    else:
        with connect() as c:write(c)
    p['revision']=expected+1;return p
def version(pid,n):
    with connect() as c:r=c.execute('SELECT snapshot FROM versions WHERE project_id=? AND number=?',(pid,n)).fetchone()
    if not r:raise UserError('版本不存在。',404)
    v=json.loads(r[0]);v['integrity']=doc_hash(v['draft'])==v['hash'];return v

def native_document(pid,slot,number=0):
    p=get_project(pid)
    if number:
        if slot not in ('service','privacy'):raise UserError('此文档没有历史定稿',404)
        content=version(pid,number)['draft'][slot]
    elif slot=='material':content=p['material']
    elif slot in ('service','privacy'):
        if not p.get('draft'):raise UserError('协议尚未生成',404)
        content=p['draft'][slot]
    elif re.fullmatch('file_[a-f0-9]+',slot):
        f=next((f for f in p.get('files',[]) if f['id']==slot[5:]),None)
        if not f:raise UserError('文件不存在',404)
        content=f['text']
    else:raise UserError('文档类型无效',404)
    digest=hashlib.sha256(content.encode()).hexdigest()
    with connect() as c:
        row=c.execute('SELECT body,text_hash FROM office_documents WHERE project_id=? AND slot=? AND version=?',(pid,slot,number)).fetchone()
        if row and row['text_hash']==digest:return row['body']
        if number and row:raise UserError('原生文档与归档内容不一致',409)
        body=word_document(content)
        c.execute('INSERT OR REPLACE INTO office_documents VALUES(?,?,?,?,?)',(pid,slot,number,body,digest))
    return body

def validate_result(r,stage):
    return ai_gateway.validate(r,stage)

def call_model(stage,payload):
    def progress(task,chars,elapsed):
        jid=getattr(JOB_LOCAL,'id',None)
        if jid:
            with connect() as c:c.execute('UPDATE jobs SET progress=?,updated_at=? WHERE id=?',(dumps({'stage':task,'chars':chars,'seconds':round(elapsed)}),now(),jid))
    if stage not in ('draft','revise'):
        progress(stage,0,0)
        return ai_gateway.generate(stage,payload,CONFIG,DATA,API_BASE,progress)
    output={'reviews':[],'blockers':[],'changes':[],'provenance':{'kind':'live','calls':[]}}
    for doc in ('service','privacy'):
        progress(stage+'_'+doc,0,0)
        context=dict(payload)
        if stage=='revise':
            baseline=payload['baseline']
            context={'baseline_document':baseline['draft'][doc],'material':baseline['material'],'analysis':baseline['analysis'],'answers':baseline['answers'],'change':payload['change'],'confirmation':payload['confirmation']}
        if doc=='privacy':context['service_document']=output['service']
        result=ai_gateway.generate(stage+'_'+doc,context,CONFIG,DATA,API_BASE,progress)
        output[doc]=result['document'];output['reviews']+=result['reviews'];output['blockers']+=result['blockers']
        output['provenance']['calls'].append(result['provenance'])
        for change in result.get('changes',[]):
            change['document']=doc;output['changes'].append(change)
    output['blockers']=list(dict.fromkeys(output['blockers']))
    return validate_result(output,stage)


def perform(pid,action,data,*,external_result=None,connection=None):
    p=get_project(pid);expected=data.get('revision');demo=p['mode']=='demo'
    p.setdefault('files',[]);p.setdefault('messages',[])
    if external_result is not None:
        if p.get('engine')!='harness' or action not in ('analyze','draft','revise'):raise UserError('外部结果仅能写入 Harness 专属生成任务。',403)
        external_result=validate_result(external_result,action)
    if p.get('engine')=='harness' and action in ('analyze','draft','revise','chat') and external_result is None:
        raise UserError('此项目使用 Harness 账号模型；请在 Harness 中发起生成，工作台不另行调用模型。',409,'harness_required')
    if expected!=p['revision']:raise UserError('当前页面不是最新版本，请刷新后重试。',409)
    if action=='harnesslink':
        if demo:raise UserError('示例项目不接入真实模型；请使用真实项目。')
        if data.get('confirmed') is not True:raise UserError('请在工作台明确确认授权此项目给 Harness。')
        if len(HARNESS_TOKEN)<32:raise UserError('请先在服务器配置 HARNESS_ACCESS_TOKEN。',503)
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT 1 FROM jobs WHERE project_id=? AND status IN ('queued','running')",(pid,)).fetchone():
                raise UserError('请等待当前生成任务结束后再切换模型来源。',409)
            p.update(engine='harness',harness_owner=hashlib.sha256(HARNESS_TOKEN.encode()).hexdigest())
            p['events'].append({'at':now(),'text':'用户在工作台授权当前项目改用 Harness 会话模型'})
            return store(p,expected,c)
    if action=='import':
        result=extract_upload(data);fid=secrets.token_hex(8)
        rel=str(data.get('relative_path') or result['name']).replace('\\','/')
        if len(rel)>500 or any(x in ('..','') for x in rel.split('/')) or ':' in rel:raise UserError('文件路径无效')
        result.update(id=fid,path=rel,at=now(),original=True)
        result['display_name']=re.sub(r'\.(md|txt)$','.docx',result['name'],flags=re.I)
        p['files'].append(result);p['events'].append({'at':now(),'text':'导入文件：'+result['name']})
        with connect() as c:
            blob=base64.b64decode(data['content']);body=blob if result['name'].lower().endswith('.docx') else word_document(result['text'])
            store(p,expected,c);c.execute('INSERT INTO imported_files VALUES(?,?,?,?)',(fid,pid,result['name'],blob))
            c.execute('INSERT INTO office_documents VALUES(?,?,?,?,?)',(pid,'file_'+fid,0,body,hashlib.sha256(result['text'].encode()).hexdigest()))
        return p
    elif action=='wordreplace':
        name=str(data.get('name',''))
        if not name.lower().endswith('.docx'):raise UserError('请导入 .docx 格式的修订稿')
        result=extract_upload(data);slot=data.get('slot');body=base64.b64decode(data['content'])
        if slot=='material':
            if p['draft'] or p['versions']:raise UserError('已有协议，请使用业务变更流程提交材料')
            p.update(material=result['text'],source_name=name,analysis=None,answers={},stage=0);p.pop('confirmed_by',None);p.pop('confirmed_at',None)
        elif slot in ('service','privacy'):
            d=p.get('draft')
            if not d or d.get('archived_as'):raise UserError('当前没有可替换的审阅稿')
            d[slot]=result['text'];d['hash']=doc_hash(d);d['edited_at']=now()
        elif isinstance(slot,str) and re.fullmatch('file_[a-f0-9]+',slot):
            f=next((f for f in p['files'] if f['id']==slot[5:]),None)
            if not f:raise UserError('文档不存在',404)
            f['text']=result['text'];f['edited_at']=now()
        else:raise UserError('文档类型无效')
        p['events'].append({'at':now(),'text':'导入 Word 修订稿：'+name})
        with connect() as c:
            store(p,expected,c)
            c.execute('INSERT OR REPLACE INTO office_documents VALUES(?,?,?,?,?)',(pid,slot,0,body,hashlib.sha256(result['text'].encode()).hexdigest()))
        return p
    elif action=='fileedit':
        f=next((f for f in p['files'] if f['id']==data.get('id')),None)
        if not f:raise UserError('文件不存在',404)
        f['text']=text(data.get('text'),'文档正文',120000);f['edited_at']=now();event='保存工作区文档副本'
    elif action=='chat':
        message=text(data.get('message'),'消息',8000);doc=data.get('document','material')
        if doc not in ('material','service','privacy'):raise UserError('对话文档无效')
        d=p.get('draft') or {};selection=str(data.get('selection') or '')[:12000]
        current=p['material'] if doc=='material' else d.get(doc,'')
        if selection and selection not in current:raise UserError('所选文本已发生变化，请保存后重新选择',409)
        history=[{'role':m['role'],'content':m['content']} for m in p['messages'][-12:]]
        if demo:
            result={'answer':'当前为示例项目，未调用实时模型。可以在上方执行材料分析、确认、起草与修订流程。自由提问和选文修改请在连接模型后建立真实项目。','proposal':None}
        else:
            result=call_model('chat',{'message':message,'document':doc,'current_document':current,'selection':selection,'material':p['material'],'analysis':p['analysis'],'answers':p['answers'],'editable':bool(doc!='material' and d and not d.get('archived_as')),'history':history})
        proposal=result.get('proposal')
        if proposal:
            target=proposal['document']
            if doc=='material' or target!=doc or d.get('archived_as') or not d or d.get(target,'').count(proposal['before'])!=1:raise UserError('AI建议无法唯一对应当前草稿，未改动正文，请缩小选文后重试',502,'proposal_unanchored')
            proposal.update(hash=d['hash'],applied=False)
        p['messages'] += [{'id':secrets.token_hex(8),'role':'user','content':message,'at':now(),'document':doc,'selection':selection},{'id':secrets.token_hex(8),'role':'assistant','content':result['answer'],'proposal':proposal,'at':now(),'provenance':result.get('provenance',{'kind':'demo'})}]
        event='完成一次文档对话'
    elif action=='applyproposal':
        m=next((m for m in p['messages'] if m['id']==data.get('id')),None)
        prop=m.get('proposal') if m else None;d=p.get('draft')
        if not prop or not d or prop.get('applied') or d.get('archived_as'):raise UserError('没有可应用的修改建议')
        if prop['hash']!=doc_hash(d):raise UserError('正文已改变，请重新生成建议',409)
        key=prop['document']
        if d[key].count(prop['before'])!=1:raise UserError('原文无法唯一定位',409)
        d[key]=d[key].replace(prop['before'],prop['after'],1);d['hash']=doc_hash(d);prop['applied']=True;d['edited_at']=now();event='法务采纳AI修改建议'
    elif action=='material':
        if p['draft'] or p['versions']:raise UserError('已有协议，请在业务变更中提交新材料。')
        p['material']=text(data.get('material'),'业务材料');p['source_name']=str(data.get('source_name','手动输入'))[:150]
        p['analysis']=None;p['answers']={};p.pop('confirmed_by',None);p.pop('confirmed_at',None);p['stage']=0;event='保存业务材料'
    elif action=='analyze':
        if p['draft']:raise UserError('已有审阅稿，请使用业务变更流程。')
        text(p['material'],'业务材料')
        if demo and p['material']!=seed()['material']:raise UserError('回放仅适用原始虚构材料，自定义材料请建立真实项目。')
        p['analysis']=external_result if external_result is not None else seed()['analysis'] if demo else call_model('analyze',{'material':p['material'],'source_name':p['source_name']})
        p['answers']={};p.pop('confirmed_by',None);p.pop('confirmed_at',None);p['stage']=1;event='整理事实并生成业务追问'
    elif action=='answers':
        if not p['analysis'] or p['draft']:raise UserError('请先分析材料；初稿后的补充请走变更流程。')
        a=data.get('answers')
        if not isinstance(a,dict):raise UserError('回答格式错误。')
        p['answers']={q['id']:text(a.get(q['id']),'业务回答',6000) for q in p['analysis']['questions']}
        p['confirmed_by']=text(data.get('confirmed_by'),'业务确认人',80);p['confirmed_at']=now();event='业务确认起草事实'
    elif action=='draft':
        if p['draft']:raise UserError('初稿已存在，请编辑或进入业务变更。')
        if not p['analysis'] or not p.get('confirmed_by') or any(not p['answers'].get(q['id']) for q in p['analysis']['questions']):raise UserError('请先填写并保存全部业务回答。')
        if demo and p['answers']!=seed()['answers']:raise UserError('回放稿仅适用示例回答，自定义回答需要真实模型生成。')
        p['draft']=external_result if external_result is not None else seed()['draft'] if demo else call_model('draft',{'material':p['material'],'analysis':p['analysis'],'answers':p['answers']})
        p['draft']['base_version']=None;p['draft']['hash']=doc_hash(p['draft']);p['stage']=2;event='生成协议及法务审阅意见'
    elif action=='edit':
        if not p['draft'] or p['draft'].get('archived_as'):raise UserError('无可编辑草稿，已归档文本须走变更流程。')
        for k in ('service','privacy'):p['draft'][k]=text(data.get(k),'协议正文',120000)
        p['draft']['hash']=doc_hash(p['draft']);p['draft']['edited_at']=now();event='法务编辑审阅稿'
    elif action=='archive':
        d=p['draft']
        if not d or d.get('archived_as'):raise UserError('暂无可归档新稿。')
        if data.get('hash')!=doc_hash(d):raise UserError('确认文件与当前文本不一致，请重新审阅。',409)
        if data.get('confirmed') is not True:raise UserError('请明确确认两份文本为法务定稿。')
        approver=text(data.get('approver'),'定稿确认人',80);note=text(data.get('note'),'法务决定与未决事项处理结论',6000)
        if re.search(r'[\[【]待确认',d['service']+d['privacy']):raise UserError('正文仍有待确认占位，请补充编辑后再归档。')
        effective=data.get('effective_date') or None
        if effective:
            try:date.fromisoformat(effective)
            except (ValueError,TypeError):raise UserError('生效日期无效。')
        n=len(p['versions'])+1
        snap={'number':n,'at':now(),'approver':approver,'note':note,'effective_date':effective,'mode':p['mode'],'hash':doc_hash(d),
              'draft':json.loads(dumps(d)),'material':p['material'],'analysis':p['analysis'],'answers':p['answers'],
              'confirmed_by':p.get('confirmed_by'),'confirmed_at':p.get('confirmed_at'),
              'change_input':p.get('change_input'),'change_confirmation':p.get('change_confirmation')}
        p['versions'].append({k:snap[k] for k in ('number','at','approver','note','effective_date','mode','hash')})
        d['archived_as']=n;p['stage']=3
        if not p['reviews']:
            due=(date.today()+timedelta(days=30)).isoformat()
            p['reviews']=[{'id':secrets.token_hex(4),'topic':t,'question':q,'owner':o,'due':due,'history':[]} for t,q,o in [
                ('供应商与数据流','核实实际供应商、接收方、处理地点、留存及用途是否变化；存在AI功能时核对模型清单。','研发 / 法务'),
                ('域名与联系入口','确认服务域名、客服邮箱、投诉与注销入口仍准确可用。','产品 / 客服'),
                ('数据与商业规则','确认个人信息用途、保留期限、内容授权、收费权益及退款规则有无调整。','产品 / 法务')]]
        p['events'].append({'at':now(),'text':f'归档法务定稿 v{n}'})
        native={slot:native_document(pid,slot) for slot in ('service','privacy')}
        with connect() as c:
            store(p,expected,c);c.execute('INSERT INTO versions VALUES(?,?,?)',(pid,n,dumps(snap)))
            for slot,body in native.items():c.execute('INSERT INTO office_documents VALUES(?,?,?,?,?)',(pid,slot,n,body,hashlib.sha256(d[slot].encode()).hexdigest()))
        return p
    elif action=='revise':
        if not p['versions']:raise UserError('请先完成 v1 定稿归档。')
        if p['draft'] and not p['draft'].get('archived_as'):raise UserError('已有未定稿候选版本，请先处理当前候选稿。')
        change=text(data.get('change'),'业务变更');confirmation=text(data.get('confirmation'),'补充事实与确认来源')
        if demo and (change!=seed()['change_input'] or confirmation!=seed()['change_confirmation']):raise UserError('回放仅适用示例变更及确认材料，自定义变更请使用真实项目。')
        latest=p['versions'][-1]['number'];snap=version(pid,latest)
        if demo and latest!=1:raise UserError('示例只准备了 v1 → v2，进一步变更请建立真实项目。')
        d=external_result if external_result is not None else seed()['revision'] if demo else call_model('revise',{'baseline':snap,'change':change,'confirmation':confirmation})
        if demo:
            for doc in ('service','privacy'):
                d[doc]=snap['draft'][doc]
            for change_item in d['changes']:
                doc=change_item['document']
                if change_item['before'] not in d[doc]:raise UserError('基线的示例条款已经改变，需要真实模型分析，不能套用固定回放。')
                d[doc]=d[doc].replace(change_item['before'],change_item['after'])
        d['base_version']=latest;d['hash']=doc_hash(d);d['verified_diff']={doc:'\n'.join(unified_diff(snap['draft'][doc].splitlines(),d[doc].splitlines(),fromfile=f'v{latest}',tofile='候选稿',lineterm='')) for doc in ('service','privacy')};p['draft']=d;p['change_input']=change;p['change_confirmation']=confirmation;p['stage']=2
        event='根据业务变更生成候选修订'
    elif action=='review':
        item=next((x for x in p['reviews'] if x['id']==data.get('id')),None)
        if not item:raise UserError('复核事项不存在。')
        resolution=text(data.get('resolution'),'复核结论与来源',6000)
        try:
            nd=date.fromisoformat(data.get('next_due',''))
            if nd<=date.today():raise ValueError()
        except (ValueError,TypeError):raise UserError('请选择今天之后的下次复核日期。')
        item['history'].append({'at':now(),'resolution':resolution,'old_due':item['due']});item['due']=nd.isoformat();event='记录复核结论：'+item['topic']
    else:raise UserError('未知操作。',404)
    p['events'].append({'at':now(),'text':event});return store(p,expected,connection)

def extract_upload(data):
    name=text(data.get('name'),'文件名',200)
    try:blob=base64.b64decode(data.get('content',''),validate=True)
    except ValueError:raise UserError('文件编码无效。')
    if len(blob)>3_000_000:raise UserError('请使用 3 MB 以内的文档。')
    if name.lower().endswith('.docx'):
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                info=z.getinfo('word/document.xml')
                if info.file_size>5_000_000:raise UserError('文档解压内容过大。')
                xml=z.read(info)
                if b'<!DOCTYPE' in xml or b'<!ENTITY' in xml:raise UserError('文档结构不支持。')
                root=ElementTree.fromstring(xml);ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                out='\n'.join(''.join(t.text or '' for t in p.findall('.//w:t',ns)) for p in root.findall('.//w:p',ns))
        except (zipfile.BadZipFile,KeyError,ElementTree.ParseError,RuntimeError):raise UserError('无法读取 Word 文件，请检查是否加密，或另存为 .docx 后重试。')
    elif name.lower().endswith(('.txt','.md')):
        try:out=blob.decode('utf-8-sig')
        except UnicodeDecodeError:
            try:out=blob.decode('gb18030')
            except UnicodeDecodeError:raise UserError('无法识别编码，请使用 UTF-8。')
    else:raise UserError('支持 .docx、.txt、.md；PDF 请复制正文后提交。')
    return {'name':name,'text':text(out,'文件正文'),'sha256':hashlib.sha256(blob).hexdigest()}

EXECUTOR=ThreadPoolExecutor(max_workers=2,thread_name_prefix='agreement-job')
def recover_jobs():
    with connect() as c:
        c.execute("UPDATE jobs SET status='failed',error='服务重启中断了任务，已保存文件保留，请重新发起',error_code='server_restarted',updated_at=? WHERE status IN ('queued','running')",(now(),))

def job_public(row):
    d=dict(row);payload=json.loads(d.pop('payload'));d['message']=payload.get('message','');d['progress']=json.loads(d['progress']) if d.get('progress') else None;return d

def project_jobs(pid):
    get_project(pid)
    with connect() as c:return [job_public(r) for r in c.execute('SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC LIMIT 8',(pid,))]

def run_job(jid):
    JOB_LOCAL.id=jid
    with connect() as c:
        row=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        c.execute("UPDATE jobs SET status='running',updated_at=? WHERE id=?",(now(),jid))
    try:
        perform(row['project_id'],row['action'],json.loads(row['payload']))
        with connect() as c:c.execute("UPDATE jobs SET status='done',updated_at=? WHERE id=?",(now(),jid))
    except Exception as e:
        err=e if isinstance(e,UserError) else UserError('任务异常，已保存内容保留',500,'internal_error')
        with connect() as c:c.execute("UPDATE jobs SET status='failed',updated_at=?,error=?,error_code=?,request_id=? WHERE id=?",(now(),str(err),err.code,err.request_id,jid))
    finally:JOB_LOCAL.id=None

def submit_job(pid,action,data):
    if action not in ('analyze','draft','revise','chat'):raise UserError('该操作不是生成任务')
    p=get_project(pid)
    if data.get('revision')!=p['revision']:raise UserError('项目已更新，请刷新后重试',409)
    if p.get('engine')=='harness':raise UserError('请在 Harness 使用当前账号模型生成；网页不另行调用模型。',409,'harness_required')
    if p['mode']=='live' and not CONFIG['api_key']:raise UserError('请先连接模型；已保存的材料保留。',503,'model_not_configured')
    jid=secrets.token_hex(8)
    try:
        with connect() as c:c.execute('INSERT INTO jobs(id,project_id,action,payload,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(jid,pid,action,dumps(data),'queued',now(),now()))
    except sqlite3.IntegrityError:raise UserError('本项目已有任务正在运行',409,'job_active')
    EXECUTOR.submit(run_job,jid)
    return {'id':jid,'project_id':pid,'status':'queued','action':action}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*a,**kw):super().__init__(*a,directory=str(ROOT/'public'),**kw)
    def log_message(self,fmt,*args):print(f'{self.command} {urlparse(self.path).path}',flush=True)
    def end_headers(self):
        for k,v in {'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer','Cache-Control':'no-store',
          'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"}.items():self.send_header(k,v)
        super().end_headers()
    def send_json(self,v,status=200,cookie=None):
        body=dumps(v).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)))
        if cookie:self.send_header('Set-Cookie',cookie)
        self.end_headers();self.wfile.write(body)
    def send_bytes(self,body,mime):
        self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def authenticated(self):
        if not PASSWORD:return True
        cookie=SimpleCookie()
        try:cookie.load(self.headers.get('Cookie',''))
        except Exception:return False
        s=cookie.get('agreement_session');return bool(s and SESSIONS.get(s.value,0)>time.time())
    def guard_host(self,mutation=False):
        hosts={f'127.0.0.1:{PORT}',f'localhost:{PORT}'}
        if ORIGIN:hosts.add(urlparse(ORIGIN).netloc)
        if self.headers.get('Host') not in hosts:raise UserError('主机不被允许。',403)
        if mutation:
            origins={f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'}
            if ORIGIN:origins.add(ORIGIN)
            if self.headers.get('Origin') and self.headers.get('Origin') not in origins:raise UserError('来源不被允许。',403)
            if self.headers.get('X-Workspace-Request')!='1':raise UserError('缺少请求校验。',403)
    def guard(self,mutation=False):
        self.guard_host(mutation)
        if not self.authenticated():raise UserError('请先输入工作台访问口令。',401)
    def redirect_to_canonical(self):
        if urlparse(self.path).path=='/healthz':return False
        target=canonical_redirect_target(self.headers.get('Host'),self.path)
        if not target:return False
        self.send_response(302)
        self.send_header('Location',target)
        self.send_header('Content-Length','0')
        self.end_headers()
        return True
    def harness_request(self,method,data=None):
        self.guard_host(method=='POST')
        owner=harness_bridge.authorize(HARNESS_TOKEN,self.headers.get('Authorization'))
        result=harness_bridge.handle(sys.modules[__name__],method,self.path,data or {},owner)
        if isinstance(result,tuple):return self.send_bytes(*result)
        return self.send_json(result)
    def do_HEAD(self):
        if self.redirect_to_canonical():return
        return super().do_HEAD()
    def do_GET(self):
        path=urlparse(self.path).path
        try:
            if self.redirect_to_canonical():return
            if path=='/healthz':
                with connect() as c:c.execute('SELECT 1 FROM projects LIMIT 1').fetchone()
                return self.send_json({'status':'ok'})
            if path.startswith('/api/harness/'):return self.harness_request('GET')
            if path=='/api/session':return self.send_json({'authenticated':self.authenticated(),'login_required':bool(PASSWORD)})
            if path.startswith('/api/'):
                self.guard()
                if path=='/api/status':return self.send_json({'ready':bool(CONFIG['api_key']),'provider':'硅基流动','model':CONFIG['model'],'local_config':not ORIGIN and self.client_address[0]=='127.0.0.1','scheduler':False,'format':CONFIG.get('format','auto'),'version':'2.8','agent_quality_enabled':True,'knowledge_enabled':True,'harness_enabled':len(HARNESS_TOKEN)>=32,'connection_scope':'server' if ORIGIN else 'local','office':{'provider':'local','wps_ready':False}})
                if path=='/api/knowledge' or path.startswith('/api/knowledge/'):
                    return self.send_json(knowledge.handle(sys.modules[__name__],'GET',self.path,{}))
                if path=='/api/demo':return self.send_json(seed())
                if path=='/api/projects':
                    with connect() as c:ps=[json.loads(r[0]) for r in c.execute('SELECT payload FROM projects ORDER BY rowid')]
                    return self.send_json([{k:p[k] for k in ('id','name','mode','stage')} for p in ps if not p.get('internal_ui_test')])
                m=re.fullmatch(r'/api/projects/([a-f0-9]+)/jobs',path)
                if m:return self.send_json(project_jobs(m[1]))
                m=re.fullmatch(r'/api/projects/([a-f0-9]+)/agent(?:/([a-f0-9]+))?',path)
                if m:return self.send_json(agent_tasks.web_handle(sys.modules[__name__],'GET',m[1],m[2]))
                m=re.fullmatch(r'/api/projects/([a-f0-9]+)/documents/([a-z0-9_]+)',path)
                if m:
                    from urllib.parse import parse_qs
                    try:number=int(parse_qs(urlparse(self.path).query).get('version',['0'])[0])
                    except ValueError:raise UserError('版本号无效')
                    return self.send_bytes(native_document(m[1],m[2],number),'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
                m=re.fullmatch(r'/api/projects/([a-f0-9]+)/files/([a-f0-9]+)',path)
                if m:
                    with connect() as c:r=c.execute('SELECT body FROM imported_files WHERE project_id=? AND id=?',(m[1],m[2])).fetchone()
                    if not r:raise UserError('原文件不存在',404)
                    return self.send_bytes(r['body'],'application/octet-stream')
                m=re.fullmatch(r'/api/projects/([a-f0-9]+)/versions/(\d+)',path)
                if m:return self.send_json(version(m[1],int(m[2])))
                m=re.fullmatch(r'/api/projects/([a-f0-9]+)',path)
                if m:return self.send_json(get_project(m[1]))
                raise UserError('接口不存在。',404)
            public_assets={'/assets/'+n for n in ('character-sheet.png','review-scene.png','privacy-scene.png','login-scene.png','workflow-scene.png','companion-idle.webp','companion-still.png','companion-blink.gif','entrance-v1.mp4','entrance-start.png','entrance-poster.png')}
            if path not in ('/','/index.html','/studio.js','/agent.js','/agent.css','/knowledge.js','/knowledge.css','/motion.js','/studio.css','/motion.css','/intro.js','/intro.css','/favicon.svg') and path not in public_assets:raise UserError('页面不存在。',404)
            return super().do_GET()
        except UserError as e:self.send_json({'error':str(e),'code':e.code,'request_id':e.request_id},e.status)
        except (BrokenPipeError,ConnectionResetError):pass
    def do_POST(self):
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size<1 or size>4_500_000:raise UserError('请求为空或文件过大。',413)
            try:data=json.loads(self.rfile.read(size))
            except ValueError:raise UserError('请求不是有效 JSON。')
            if not isinstance(data,dict):raise UserError('请求格式错误。')
            path=urlparse(self.path).path
            if path.startswith('/api/harness/'):return self.harness_request('POST',data)
            if path=='/api/login':
                self.guard_host(True)
                ip=self.client_address[0];recent=[t for t in LOGIN_ATTEMPTS.get(ip,[]) if time.time()-t<60];LOGIN_ATTEMPTS[ip]=recent
                if len(recent)>=5:raise UserError('请一分钟后再试。',429)
                if not isinstance(data.get('password'),str) or not hmac.compare_digest(data['password'].encode(),PASSWORD.encode()):recent.append(time.time());raise UserError('访问口令不正确。',401)
                token=secrets.token_urlsafe(32);SESSIONS[token]=time.time()+28800
                cookie=f'agreement_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800'
                if ORIGIN.startswith('https:'):cookie+='; Secure'
                return self.send_json({'ok':True},cookie=cookie)
            self.guard(True)
            if path.startswith('/api/knowledge/'):
                return self.send_json(knowledge.handle(sys.modules[__name__],'POST',self.path,data))
            if path=='/api/config':
                if ORIGIN or self.client_address[0]!='127.0.0.1':raise UserError('线上配置请在服务器环境变量中设置。',403)
                fmt=data.get('format','auto')
                if fmt not in ('auto','json_object','json_schema','prompt'):raise UserError('输出模式无效')
                CONFIG['format']=fmt
                CONFIG['model']=text(data.get('model'),'模型名称',150)
                if data.get('api_key'):CONFIG['api_key']=text(data['api_key'],'密钥',300)
                return self.send_json({'ok':True,'ready':bool(CONFIG['api_key'])})
            if path=='/api/export':return self.send_bytes(word_document(text(data.get('text'),'文档正文',120000)),'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            if path=='/api/upload':return self.send_json(extract_upload(data))
            if path=='/api/projects':return self.send_json(create_project(data.get('name'),data.get('mode')))
            m=re.fullmatch(r'/api/projects/([a-f0-9]+)/agent(?:/([a-f0-9]+)/(confirm|cancel))?',path)
            if m:return self.send_json(agent_tasks.web_handle(sys.modules[__name__],'POST',m[1],m[2],m[3],data))
            m=re.fullmatch(r'/api/projects/([a-f0-9]+)/jobs/([a-z]+)',path)
            if m:return self.send_json(submit_job(m[1],m[2],data),202)
            m=re.fullmatch(r'/api/projects/([a-f0-9]+)/([a-z]+)',path)
            if m:return self.send_json(perform(m[1],m[2],data))
            raise UserError('接口不存在。',404)
        except UserError as e:self.send_json({'error':str(e),'code':e.code,'request_id':e.request_id},e.status)
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception as e:
            print('Request failed:',type(e).__name__,flush=True);self.send_json({'error':'操作未完成，请刷新核对当前状态后重试。'},500)

if __name__=='__main__':
    if HOST not in ('127.0.0.1','localhost') and (len(PASSWORD)<16 or not ORIGIN.startswith('https://')):raise SystemExit('Public binding requires APP_PASSWORD (16+ characters) and HTTPS PUBLIC_ORIGIN')
    initialize();recover_jobs();print(f'Local: http://127.0.0.1:{PORT}',flush=True);ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
