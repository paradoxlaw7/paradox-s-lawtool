"""Model-free, project-scoped bridge for a user's existing Harness conversation."""
import hashlib
import hmac
import json
import re
import secrets
from urllib.parse import parse_qs, urlparse
from errors import UserError
import ai_gateway
import knowledge
import agent_tasks

VERSION='1.2'
HARNESS_PROMPT=ai_gateway.COMMON.replace(
    '只输出一个合法 JSON 对象，不加解释前后缀、代码围栏或思考过程。',
    '按输出结构生成完整 JSON，并调用 yueding_submit_result 提交；不要在聊天里粘贴整份 JSON。').replace(
    '没有联网检索工具，不声称核验了最新法律。',
    '只有当前会话实际使用检索工具并核对来源后，才说明已核验最新法律；没有检索时明确未核验。')
STAGES={'analyze':['analyze'],'draft':['draft_service','draft_privacy'],
        'revise':['revise_service','revise_privacy']}


def initialize(connection):
    connection.executescript('''
    CREATE TABLE IF NOT EXISTS harness_tasks(
      id TEXT PRIMARY KEY,project_id TEXT NOT NULL,revision INTEGER NOT NULL,kind TEXT NOT NULL,
      payload TEXT NOT NULL,results TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE UNIQUE INDEX IF NOT EXISTS one_harness_task ON harness_tasks(project_id) WHERE status='waiting';
    ''')
    agent_tasks.initialize(connection)


def authorize(configured,authorization):
    if not isinstance(configured,str) or len(configured)<32:
        raise UserError('Harness 接入未启用；请在服务器设置 HARNESS_ACCESS_TOKEN（至少32位）。',503,'harness_not_configured')
    provided=(authorization or '').removeprefix('Bearer ')
    if not (authorization or '').startswith('Bearer ') or not hmac.compare_digest(configured.encode(),provided.encode()):
        raise UserError('工作台连接凭证无效。请检查插件连接配置。',401,'harness_unauthorized')
    return hashlib.sha256(configured.encode()).hexdigest()


def owned(s,pid,owner):
    p=s.get_project(pid)
    if p.get('engine')!='harness' or p.get('harness_owner')!=owner:
        raise UserError('此项目不属于当前插件连接。',404,'harness_project_scope')
    return p


def url(s,pid):
    return (s.ORIGIN or f'http://127.0.0.1:{s.PORT}')+'/?project='+pid


def project_result(s,p):
    p=json.loads(s.dumps(p));p.pop('harness_owner',None)
    return {'project':p,'workbench_url':url(s,p['id']),'model_runtime':'harness-current-session'}


def strict(value,schema):
    """The bridge's small JSON-Schema subset; reject model-supplied state/approval fields."""
    kind=schema.get('type')
    if kind=='object':
        if not isinstance(value,dict):raise UserError('请提交符合任务约定的 JSON 对象。',422,'harness_schema')
        fields=schema.get('properties',{})
        if set(schema.get('required',[]))-set(value) or (schema.get('additionalProperties') is False and set(value)-set(fields)):
            raise UserError('结果字段不完整或包含任务约定外的字段；未改动当前正文。',422,'harness_schema')
        for key,item in value.items():
            if key in fields:strict(item,fields[key])
    elif kind=='array':
        if not isinstance(value,list):raise UserError('结果中的列表格式不正确。',422,'harness_schema')
        for item in value:strict(item,schema['items'])
    elif kind=='string' and not isinstance(value,str):raise UserError('结果中的文字字段格式不正确。',422,'harness_schema')
    if 'enum' in schema and value not in schema['enum']:raise UserError('结果中的枚举值不在允许范围。',422,'harness_schema')


def context(s,p,kind,extra):
    if kind=='analyze':
        if p['draft']:raise UserError('已有审阅稿，请通过业务变更修订。',409)
        s.text(p['material'],'业务材料')
        return {'material':p['material'],'source_name':p['source_name']}
    if kind=='draft':
        if p['draft']:raise UserError('已有草稿；请先在工作台处理当前稿。',409)
        if not p['analysis'] or not p.get('confirmed_by') or any(not p['answers'].get(q['id']) for q in p['analysis']['questions']):
            raise UserError('请先在工作台填写并人工确认业务事实，再回到 Harness 起草。',409,'harness_confirmation_required')
        return {'material':p['material'],'analysis':p['analysis'],'answers':p['answers']}
    if not p['versions'] or (p['draft'] and not p['draft'].get('archived_as')):
        raise UserError('修订需要已归档基线，且不能存在未处理的候选稿。',409)
    return {'baseline':s.version(p['id'],p['versions'][-1]['number']),
            'change':s.text(extra.get('change'),'业务变化'),
            'confirmation':s.text(extra.get('confirmation'),'变化的事实来源')}


def task_view(s,row,p):
    results=json.loads(row['results']);payload=json.loads(row['payload'])
    stages=STAGES[row['kind']]
    stage=next((stage for stage in stages if stage not in results),None)
    if row['status']=='done':return {'status':'done',**project_result(s,p)}
    if p['revision']!=row['revision']:raise UserError('项目已变化，请重新准备任务。',409,'harness_task_stale')
    if row['status']!='waiting':raise UserError('此任务已失效或取消，请重新准备任务。',409,'harness_task_stale')
    data={k:v for k,v in payload.items() if k!='_knowledge'}
    if row['kind']=='revise':
        doc=stage.split('_')[1];baseline=payload['baseline']
        data={'baseline_document':baseline['draft'][doc],'material':baseline['material'],
              'analysis':baseline['analysis'],'answers':baseline['answers'],
              'change':payload['change'],'confirmation':payload['confirmation']}
    if stage.endswith('_privacy'):
        data['service_document']=results[stages[0]]['value']['document']
    return {'status':'waiting','task_id':row['id'],'project_id':p['id'],'revision':row['revision'],
            'stage':stage,'instructions':HARNESS_PROMPT+'\n'+ai_gateway.TASKS[stage]+'\n'+knowledge.POLICY,
            'knowledge_context':payload.get('_knowledge',{}),
            'output_schema':ai_gateway.schema(stage),'project_data':data,'workbench_url':url(s,p['id']),
            'next_step':'使用当前 Harness 会话模型完成此阶段，调用 yueding_submit_result。不要调用外部模型或提交人工确认。'}


def prepare(s,pid,owner,data):
    if data.get('workflow_version')==2 and data.get('kind') in ('draft','revise'):
        return agent_tasks.prepare(s,pid,owner,data)
    p=owned(s,pid,owner);kind=data.get('kind')
    if kind not in STAGES:raise UserError('任务类型须为 analyze、draft 或 revise。')
    if data.get('revision')!=p['revision']:raise UserError('项目已变化，请重新读取。',409)
    payload=context(s,p,kind,data)
    if 'knowledge_ids' in data:payload['knowledge_ids']=data['knowledge_ids']
    with s.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        # Recheck after acquiring the write lock; browser edits cannot silently race preparation.
        fresh=owned(s,pid,owner)
        if fresh['revision']!=p['revision']:raise UserError('项目已变化，请重新读取。',409)
        if c.execute("SELECT 1 FROM agent_runs WHERE project_id=? AND revision=? AND status IN ('ready','waiting_human','needs_repair','blocked')",(pid,p['revision'])).fetchone():
            raise UserError('已有Agent质量任务，请先完成或取消。',409,'agent_task_active')
        row=c.execute("SELECT * FROM harness_tasks WHERE project_id=? AND status='waiting'",(pid,)).fetchone()
        if row and row['revision']!=p['revision']:
            c.execute("UPDATE harness_tasks SET status='stale' WHERE id=?",(row['id'],));row=None
        if row:
            saved={k:v for k,v in json.loads(row['payload']).items() if k!='_knowledge'}
            if row['kind']==kind and saved==payload:return task_view(s,row,p)
            raise UserError('此项目已有等待提交的任务；请完成或取消后重试。',409)
        tid=secrets.token_hex(16)
        # Freeze references and their audit log in the same transaction as task preparation.
        payload['_knowledge']=knowledge.snapshot(s,p,kind,payload,owner,connection=c)
        c.execute('INSERT INTO harness_tasks VALUES(?,?,?,?,?,?,?,?)',
                  (tid,pid,p['revision'],kind,s.dumps(payload),'{}','waiting',s.now()))
        return task_view(s,c.execute('SELECT * FROM harness_tasks WHERE id=?',(tid,)).fetchone(),p)


def submit(s,tid,owner,data):
    with s.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT * FROM harness_tasks WHERE id=?',(tid,)).fetchone()
        if not row:raise UserError('任务不存在。',404)
        p=owned(s,row['project_id'],owner)
        if row['status']=='done':return task_view(s,row,p)
        if row['status']!='waiting' or p['revision']!=row['revision']:
            raise UserError('项目正文或业务事实已变化；当前结果未写入，请重新准备任务。',409,'harness_task_stale')
        results=json.loads(row['results']);stage=data.get('stage');raw=data.get('result')
        if stage not in STAGES[row['kind']]:raise UserError('阶段与任务不匹配。',422)
        digest=hashlib.sha256(json.dumps(raw,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        if stage in results:
            if results[stage]['digest']!=digest:raise UserError('该阶段已经提交其他内容；请取消并重新准备。',409)
            return task_view(s,row,p)
        expected=next(stage for stage in STAGES[row['kind']] if stage not in results)
        if stage!=expected:raise UserError('请按服务协议、隐私政策顺序提交，避免口径不一致。',409)
        strict(raw,ai_gateway.schema(stage))
        knowledge.check_citations(raw,json.loads(row['payload']).get('_knowledge',{}))
        clean=json.loads(s.dumps(raw));ai_gateway.validate(clean,stage)
        if stage.startswith('revise_'):
            payload=json.loads(row['payload']);doc=stage.split('_')[1]
            clean['document']=ai_gateway.apply_patches(payload['baseline']['draft'][doc],clean['changes'])
            ai_gateway.review_operational_claims(clean,{'baseline_document':payload['baseline']['draft'][doc],
                    'material':payload['baseline']['material'],'change':payload['change'],'confirmation':payload['confirmation']})
        results[stage]={'value':clean,'digest':digest}
        if any(stage not in results for stage in STAGES[row['kind']]):
            c.execute('UPDATE harness_tasks SET results=? WHERE id=?',(s.dumps(results),tid))
            return task_view(s,c.execute('SELECT * FROM harness_tasks WHERE id=?',(tid,)).fetchone(),p)
        if row['kind']=='analyze':combined=clean
        else:
            combined={'reviews':[],'blockers':[],'changes':[]}
            for stage in STAGES[row['kind']]:
                result=results[stage]['value'];doc=stage.split('_')[1]
                combined[doc]=result['document'];combined['reviews']+=result['reviews'];combined['blockers']+=result['blockers']
                for item in result.get('changes',[]):combined['changes'].append({**item,'document':doc})
            combined['blockers']=list(dict.fromkeys(combined['blockers']))
        combined['provenance']={'kind':'harness','runtime':'current-session-model','task_id':tid,
               'prompt_version':ai_gateway.PROMPT_VERSION,'knowledge':json.loads(row['payload']).get('_knowledge',{}),
               'source_status':'Harness 生成建议；未经法务确认，不代表已定稿。'}
        action_data={'revision':p['revision']}
        if row['kind']=='revise':
            payload=json.loads(row['payload']);action_data.update(change=payload['change'],confirmation=payload['confirmation'])
        p=s.perform(p['id'],row['kind'],action_data,external_result=combined,connection=c)
        c.execute("UPDATE harness_tasks SET results=?,status='done' WHERE id=?",(s.dumps(results),tid))
        return {'status':'done',**project_result(s,p)}


def handle(s,method,target,data,owner):
    parsed=urlparse(target);path=parsed.path.removeprefix('/api/harness')
    if path=='/knowledge' or path.startswith('/knowledge/'):
        return knowledge.handle(s,method,target,data,owner,agent=True)
    if method=='GET' and path=='/status':
        return {'bridge_version':VERSION,'model_runtime':'harness-current-session','requires_model_api_key':False,
                'knowledge':{'enabled':True,'retrieval':'lexical_bm25','human_review_required':True},
                'agent_quality':{'workflow_version':2,'verification':True,'human_change_confirmation':True,'max_repairs':2},
                'human_confirmation':'业务事实、修订采纳和法务归档在工作台人工完成。'}
    if method=='GET' and path=='/agent/tasks':
        return agent_tasks.list_runs(s,parse_qs(parsed.query).get('project_id',[None])[0],owner)
    if method=='GET' and path=='/projects':
        with s.connect() as c:rows=c.execute('SELECT payload FROM projects ORDER BY rowid').fetchall()
        return [{'id':p['id'],'name':p['name'],'stage':p['stage'],'workbench_url':url(s,p['id'])}
                for row in rows if (p:=json.loads(row[0])).get('engine')=='harness' and p.get('harness_owner')==owner]
    if method=='POST' and path=='/projects':
        with s.connect() as c:
            p=s.create_project(data.get('name'),'live',c);p.update(engine='harness',harness_owner=owner)
            s.store(p,p['revision'],c)
        return project_result(s,p)
    match=re.fullmatch(r'/projects/([a-f0-9]+)/documents/(material|service|privacy)',path)
    if method=='GET' and match:
        owned(s,match[1],owner)
        try:version=int(parse_qs(parsed.query).get('version',['0'])[0])
        except ValueError:raise UserError('版本号无效。')
        if version<0:raise UserError('版本号无效。')
        return s.native_document(match[1],match[2],version),'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    match=re.fullmatch(r'/projects/([a-f0-9]+)(?:/(material|import|prepare))?',path)
    if match:
        p=owned(s,match[1],owner);action=match[2]
        if method=='GET' and not action:return project_result(s,p)
        if method=='POST' and action=='prepare':return prepare(s,p['id'],owner,data)
        if method=='POST' and action in ('material','import'):
            if p['draft']:raise UserError('已有协议，请使用业务变更任务。',409)
            p=s.perform(p['id'],action,data)
            if action=='import':
                p=s.perform(p['id'],'material',{'revision':p['revision'],'material':p['files'][-1]['text'],
                                                'source_name':p['files'][-1]['name']})
            return project_result(s,p)
    match=re.fullmatch(r'/tasks/([a-f0-9]+)(?:/(submit|cancel|knowledge))?',path)
    if match:
        if agent_tasks.exists(s,match[1]):
            if method=='GET' and not match[2]:return agent_tasks.get(s,match[1],owner)
            if method=='POST' and match[2]=='submit':return agent_tasks.submit(s,match[1],owner,data)
            if method=='POST' and match[2]=='cancel':return agent_tasks.cancel(s,match[1],owner)
            if method=='POST' and match[2]=='knowledge':return agent_tasks.add_knowledge(s,match[1],owner,data)
            raise UserError('Agent不能调用人工确认接口。',404,'harness_operation_denied')
        with s.connect() as c:row=c.execute('SELECT * FROM harness_tasks WHERE id=?',(match[1],)).fetchone()
        if not row:raise UserError('任务不存在。',404)
        p=owned(s,row['project_id'],owner)
        if method=='GET' and not match[2]:return task_view(s,row,p)
        if method=='POST' and match[2]=='submit':return submit(s,row['id'],owner,data)
        if method=='POST' and match[2]=='cancel':
            with s.connect() as c:changed=c.execute("UPDATE harness_tasks SET status='cancelled' WHERE id=? AND status='waiting'",(row['id'],)).rowcount
            return {'cancelled':changed==1,'workbench_url':url(s,p['id'])}
    raise UserError('此插件接口不存在或操作不被允许。',404,'harness_operation_denied')
