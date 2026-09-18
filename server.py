"""Single-user agreement workspace. Python 3.11+, standard library only."""
import base64, hashlib, hmac, io, json, os, re, secrets, sqlite3, threading, time, zipfile
import urllib.request, urllib.error
from datetime import datetime, timedelta, timezone, date
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parent
if (ROOT/'.env').exists():
    for line in (ROOT/'.env').read_text(encoding='utf-8-sig').splitlines():
        if '=' in line and not line.strip().startswith('#'):
            k,v=line.split('=',1); os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))
DATA=Path(os.environ.get('DATA_DIR',str(ROOT/'data'))); DATA.mkdir(parents=True,exist_ok=True)
DB=DATA/'workspace.sqlite3'
HOST=os.environ.get('HOST','127.0.0.1'); PORT=int(os.environ.get('PORT','8765'))
PASSWORD=os.environ.get('APP_PASSWORD',''); ORIGIN=os.environ.get('PUBLIC_ORIGIN','').rstrip('/')
CONFIG={'api_key':os.environ.get('SILICONFLOW_API_KEY',''),'model':os.environ.get('AI_MODEL','deepseek-ai/DeepSeek-V3.2')}
API_BASE='https://api.siliconflow.cn/v1'
SESSIONS={}; LOGIN_ATTEMPTS={}; AI_LOCK=threading.BoundedSemaphore(2)

class UserError(Exception):
    def __init__(self,message,status=400): super().__init__(message); self.status=status

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
        CREATE TABLE IF NOT EXISTS versions(project_id TEXT NOT NULL,number INTEGER NOT NULL,snapshot TEXT NOT NULL,
          PRIMARY KEY(project_id,number),FOREIGN KEY(project_id) REFERENCES projects(id));
        CREATE TRIGGER IF NOT EXISTS immutable_versions_update BEFORE UPDATE ON versions BEGIN SELECT RAISE(ABORT,'immutable version'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_versions_delete BEFORE DELETE ON versions BEGIN SELECT RAISE(ABORT,'immutable version'); END;''')
        if not c.execute('SELECT 1 FROM projects LIMIT 1').fetchone(): create_project('星幕漫剧工作台','demo',c)
def create_project(name,mode,conn=None):
    name=text(name,'项目名称',80)
    if mode not in ('demo','live'): raise UserError('请选择演示或真实项目。')
    p={'id':secrets.token_hex(8),'name':name,'mode':mode,'stage':0,
       'material':seed()['material'] if mode=='demo' else '', 'source_name':'虚构 PRD' if mode=='demo' else '',
       'analysis':None,'answers':{},'draft':None,'versions':[],'reviews':[],
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

def validate_result(r,stage):
    if not isinstance(r,dict):raise UserError('模型未返回有效结构，请重试。',502)
    def rows(k,fields):
        if not isinstance(r.get(k),list):raise UserError('模型结果缺少 '+k+'，未保存。',502)
        for row in r[k]:
            if not isinstance(row,dict) or any(not isinstance(row.get(f),str) for f in fields):raise UserError('模型字段不完整，未保存。',502)
    if stage=='analyze':
        rows('facts',['id','label','value','status','source']);rows('questions',['id','question','reason','owner','priority'])
        ids=[q['id'] for q in r['questions']]
        if len(ids)!=len(set(ids)) or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',i) for i in ids):raise UserError('模型问题编号不合法，未保存。',502)
    else:
        for k in ('service','privacy'):
            if not isinstance(r.get(k),str) or len(r[k])<200:raise UserError('模型协议输出不完整，未保存。',502)
        rows('reviews',['clause','issue','basis','url','suggestion'])
        if not isinstance(r.get('blockers'),list) or any(not isinstance(x,str) for x in r['blockers']):raise UserError('模型缺少待确认事项，未保存。',502)
        if stage=='revise':rows('changes',['clause','before','after','reason','action'])
    return r
def call_model(stage,payload):
    key,model=CONFIG['api_key'],CONFIG['model']
    if not key:raise UserError('尚未连接硅基流动，请在模型设置中填写密钥。',503)
    if not AI_LOCK.acquire(blocking=False):raise UserError('已有两个生成任务，请稍后重试。',429)
    try:
        body={'model':model,'messages':[{'role':'system','content':(ROOT/'prompts.md').read_text(encoding='utf-8')},
              {'role':'user','content':dumps({'task':stage,'project_data':payload})}], 'stream':False,'max_tokens':12000,'temperature':0.2}
        req=urllib.request.Request(API_BASE+'/chat/completions',data=dumps(body).encode(),
            headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=210) as response:raw=json.loads(response.read(3_000_000))
        except urllib.error.HTTPError as e:
            msg={401:'密钥无效，请检查配置。',403:'当前密钥无权使用此模型。',429:'模型限流或账户额度不足，请检查控制台。',400:'模型或参数不支持，请核对完整模型名称。'}
            raise UserError(msg.get(e.code,'模型服务暂时不可用，请稍后重试。'),502) from None
        except (OSError,ValueError):raise UserError('模型连接超时或响应异常，未覆盖已有内容。',502) from None
        try:
            choice=raw['choices'][0]
            if choice.get('finish_reason')=='length':raise UserError('输出达到长度上限，未保存不完整协议。请缩小材料范围后重试。',502)
            content=choice['message']['content'].strip()
            if content.startswith('```'):content=re.sub(r'\s*```$','',re.sub(r'^```(?:json)?\s*','',content))
            result=validate_result(json.loads(content),stage)
        except (KeyError,IndexError,TypeError,ValueError,AttributeError):raise UserError('模型未返回完整 JSON，未保存。请重试。',502) from None
        result['provenance']={'kind':'live','provider':'硅基流动','model':model,'at':now(),'usage':raw.get('usage',{}),'source_status':'内置法律线索，需法务核验'}
        return result
    finally:AI_LOCK.release()

def perform(pid,action,data):
    p=get_project(pid);expected=data.get('revision');demo=p['mode']=='demo'
    if expected!=p['revision']:raise UserError('当前页面不是最新版本，请刷新后重试。',409)
    if action=='material':
        if p['draft'] or p['versions']:raise UserError('已有协议，请在业务变更中提交新材料。')
        p['material']=text(data.get('material'),'业务材料');p['source_name']=str(data.get('source_name','手动输入'))[:150]
        p['analysis']=None;p['answers']={};p.pop('confirmed_by',None);p.pop('confirmed_at',None);p['stage']=0;event='保存业务材料'
    elif action=='analyze':
        if p['draft']:raise UserError('已有审阅稿，请使用业务变更流程。')
        text(p['material'],'业务材料')
        if demo and p['material']!=seed()['material']:raise UserError('回放仅适用原始虚构材料，自定义材料请建立真实项目。')
        p['analysis']=seed()['analysis'] if demo else call_model('analyze',{'material':p['material'],'source_name':p['source_name']})
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
        p['draft']=seed()['draft'] if demo else call_model('draft',{'material':p['material'],'analysis':p['analysis'],'answers':p['answers']})
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
                ('模型与第三方','核实模型清单、接收方、部署地、留存及训练策略是否变化。','研发 / 法务'),
                ('域名与联系入口','确认服务域名、客服邮箱、投诉与注销入口仍准确可用。','产品 / 客服'),
                ('数据与商业规则','确认个人信息用途、保留期限、素材许可及积分退款规则有无调整。','产品 / 法务')]]
        p['events'].append({'at':now(),'text':f'归档法务定稿 v{n}'})
        with connect() as c:
            store(p,expected,c);c.execute('INSERT INTO versions VALUES(?,?,?)',(pid,n,dumps(snap)))
        return p
    elif action=='revise':
        if not p['versions']:raise UserError('请先完成 v1 定稿归档。')
        if p['draft'] and not p['draft'].get('archived_as'):raise UserError('已有未定稿候选版本，请先处理当前候选稿。')
        change=text(data.get('change'),'业务变更');confirmation=text(data.get('confirmation'),'补充事实与确认来源')
        if demo and (change!=seed()['change_input'] or confirmation!=seed()['change_confirmation']):raise UserError('回放仅适用示例变更及确认材料，自定义变更请使用真实项目。')
        latest=p['versions'][-1]['number'];snap=version(pid,latest)
        if demo and latest!=1:raise UserError('示例只准备了 v1 → v2，进一步变更请建立真实项目。')
        d=seed()['revision'] if demo else call_model('revise',{'baseline':snap,'change':change,'confirmation':confirmation})
        if demo:
            for doc in ('service','privacy'):
                d[doc]=snap['draft'][doc]
            for change_item in d['changes']:
                doc=change_item['document']
                if change_item['before'] not in d[doc]:raise UserError('基线的示例条款已经改变，需要真实模型分析，不能套用固定回放。')
                d[doc]=d[doc].replace(change_item['before'],change_item['after'])
        d['base_version']=latest;d['hash']=doc_hash(d);p['draft']=d;p['change_input']=change;p['change_confirmation']=confirmation;p['stage']=2
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
    p['events'].append({'at':now(),'text':event});return store(p,expected)

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
        except (zipfile.BadZipFile,KeyError,ElementTree.ParseError):raise UserError('无法读取 Word 文件，请另存为 .docx 或粘贴正文。')
    elif name.lower().endswith(('.txt','.md')):
        try:out=blob.decode('utf-8-sig')
        except UnicodeDecodeError:
            try:out=blob.decode('gb18030')
            except UnicodeDecodeError:raise UserError('无法识别编码，请使用 UTF-8。')
    else:raise UserError('支持 .docx、.txt、.md；PDF 请复制正文后提交。')
    return {'name':name,'text':text(out,'文件正文'),'sha256':hashlib.sha256(blob).hexdigest()}

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
    def authenticated(self):
        if not PASSWORD:return True
        cookie=SimpleCookie()
        try:cookie.load(self.headers.get('Cookie',''))
        except Exception:return False
        s=cookie.get('agreement_session');return bool(s and SESSIONS.get(s.value,0)>time.time())
    def guard(self,mutation=False):
        hosts={f'127.0.0.1:{PORT}',f'localhost:{PORT}'}
        if ORIGIN:hosts.add(urlparse(ORIGIN).netloc)
        if self.headers.get('Host') not in hosts:raise UserError('主机不被允许。',403)
        if mutation:
            origins={f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'}
            if ORIGIN:origins.add(ORIGIN)
            if self.headers.get('Origin') and self.headers.get('Origin') not in origins:raise UserError('来源不被允许。',403)
            if self.headers.get('X-Workspace-Request')!='1':raise UserError('缺少请求校验。',403)
        if not self.authenticated():raise UserError('请先输入工作台访问口令。',401)
    def do_GET(self):
        path=urlparse(self.path).path
        try:
            if path=='/healthz':
                with connect() as c:c.execute('SELECT 1 FROM projects LIMIT 1').fetchone()
                return self.send_json({'status':'ok'})
            if path=='/api/session':return self.send_json({'authenticated':self.authenticated(),'login_required':bool(PASSWORD)})
            if path.startswith('/api/'):
                self.guard()
                if path=='/api/status':return self.send_json({'ready':bool(CONFIG['api_key']),'provider':'硅基流动','model':CONFIG['model'],'local_config':not ORIGIN and self.client_address[0]=='127.0.0.1','scheduler':False})
                if path=='/api/demo':return self.send_json(seed())
                if path=='/api/projects':
                    with connect() as c:ps=[json.loads(r[0]) for r in c.execute('SELECT payload FROM projects ORDER BY rowid')]
                    return self.send_json([{k:p[k] for k in ('id','name','mode','stage')} for p in ps])
                m=re.fullmatch(r'/api/projects/([a-f0-9]+)/versions/(\d+)',path)
                if m:return self.send_json(version(m[1],int(m[2])))
                m=re.fullmatch(r'/api/projects/([a-f0-9]+)',path)
                if m:return self.send_json(get_project(m[1]))
                raise UserError('接口不存在。',404)
            public_assets={'/assets/'+n for n in ('character-sheet.png','review-scene.png','privacy-scene.png','login-scene.png','workflow-scene.png')}
            if path not in ('/','/index.html','/app.js','/style.css','/favicon.svg') and path not in public_assets:raise UserError('页面不存在。',404)
            return super().do_GET()
        except UserError as e:self.send_json({'error':str(e)},e.status)
        except (BrokenPipeError,ConnectionResetError):pass
    def do_POST(self):
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size<1 or size>4_500_000:raise UserError('请求为空或文件过大。',413)
            try:data=json.loads(self.rfile.read(size))
            except ValueError:raise UserError('请求不是有效 JSON。')
            if not isinstance(data,dict):raise UserError('请求格式错误。')
            path=urlparse(self.path).path
            if path=='/api/login':
                if self.headers.get('X-Workspace-Request')!='1':raise UserError('请求不被允许。',403)
                ip=self.client_address[0];recent=[t for t in LOGIN_ATTEMPTS.get(ip,[]) if time.time()-t<60];LOGIN_ATTEMPTS[ip]=recent
                if len(recent)>=5:raise UserError('请一分钟后再试。',429)
                if not isinstance(data.get('password'),str) or not hmac.compare_digest(data['password'].encode(),PASSWORD.encode()):recent.append(time.time());raise UserError('访问口令不正确。',401)
                token=secrets.token_urlsafe(32);SESSIONS[token]=time.time()+28800
                cookie=f'agreement_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800'
                if ORIGIN.startswith('https:'):cookie+='; Secure'
                return self.send_json({'ok':True},cookie=cookie)
            self.guard(True)
            if path=='/api/config':
                if ORIGIN or self.client_address[0]!='127.0.0.1':raise UserError('线上配置请在服务器环境变量中设置。',403)
                CONFIG['model']=text(data.get('model'),'模型名称',150)
                if data.get('api_key'):CONFIG['api_key']=text(data['api_key'],'密钥',300)
                return self.send_json({'ok':True,'ready':bool(CONFIG['api_key'])})
            if path=='/api/upload':return self.send_json(extract_upload(data))
            if path=='/api/projects':return self.send_json(create_project(data.get('name'),data.get('mode')))
            m=re.fullmatch(r'/api/projects/([a-f0-9]+)/([a-z]+)',path)
            if m:return self.send_json(perform(m[1],m[2],data))
            raise UserError('接口不存在。',404)
        except UserError as e:self.send_json({'error':str(e)},e.status)
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception as e:
            print('Request failed:',type(e).__name__,flush=True);self.send_json({'error':'操作未完成，请刷新核对当前状态后重试。'},500)

if __name__=='__main__':
    if HOST not in ('127.0.0.1','localhost') and (len(PASSWORD)<16 or not ORIGIN.startswith('https://')):raise SystemExit('Public binding requires APP_PASSWORD (16+ characters) and HTTPS PUBLIC_ORIGIN')
    initialize();print(f'Local: http://127.0.0.1:{PORT}',flush=True);ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
