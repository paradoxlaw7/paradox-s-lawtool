"""Durable quality runs; the Harness session owns all model inference.

Version 1 bridge tasks remain readable. Version 2 runs keep plans, quotations,
human confirmation, candidate documents and bounded verification/repair apart
from the project's current draft until final atomic commit.
"""
import json
import secrets
import re
from urllib.parse import urlparse
import ai_gateway
import agent_quality as q
import knowledge
from errors import UserError

ACTIVE = ('ready','waiting_human','needs_repair','blocked')
LABELS = {'assess_change':'分析变化与事实','evidence_review':'核对问题依据',
          'confirm_change':'等待业务确认','draft_service':'起草服务协议','draft_privacy':'起草隐私政策',
          'revise_service':'修订服务协议','revise_privacy':'修订隐私政策',
          'verify_bundle':'交叉核验两份协议','repair_bundle':'修复候选条款','done':'候选稿已保存'}


def initialize(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS agent_runs(
      id TEXT PRIMARY KEY,project_id TEXT NOT NULL,revision INTEGER NOT NULL,
      status TEXT NOT NULL,record TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
      CREATE UNIQUE INDEX IF NOT EXISTS one_agent_run ON agent_runs(project_id)
      WHERE status IN ('ready','waiting_human','needs_repair','blocked');''')


def exists(s,tid):
    with s.connect() as c:return bool(c.execute('SELECT 1 FROM agent_runs WHERE id=?',(tid,)).fetchone())


def project(s,pid,owner):
    import harness_bridge as bridge
    return bridge.owned(s,pid,owner)


def row_for(s,tid,owner,c):
    row=c.execute('SELECT * FROM agent_runs WHERE id=?',(tid,)).fetchone()
    if not row:raise UserError('Agent任务不存在。',404,'agent_task_missing')
    p=project(s,row['project_id'],owner)
    return row,p,json.loads(row['record'])


def save(s,c,row,record,status=None):
    c.execute('UPDATE agent_runs SET record=?,status=?,updated_at=? WHERE id=?',
              (s.dumps(record),status or row['status'],s.now(),row['id']))


def event(s,r,action,detail):
    r['events'].append({'at':s.now(),'action':action,'detail':detail})


def stages(kind):
    return (['assess_change','evidence_review','confirm_change'] if kind=='revise' else ['evidence_review'])+[
        kind+'_service',kind+'_privacy','verify_bundle']


def check_live(row,p):
    if row['revision']!=p['revision']:
        raise UserError('项目或业务事实已变化，本任务结果未写入；请取消后按新版本重新准备。',409,'agent_task_stale')
    if row['status'] not in ACTIVE:raise UserError('任务已结束，请读取结果或准备新任务。',409,'agent_task_closed')


def output_schema(stage):
    if stage=='assess_change':return q.PLAN
    if stage=='evidence_review':return q.EVIDENCE
    if stage=='verify_bundle':return q.VERIFY
    if stage=='repair_bundle':return q.REPAIR
    schema=ai_gateway.schema(stage)
    if stage.startswith('revise_'):schema['properties']['changes']=q.arr(q.PATCH)
    return schema


def view(s,row,p,r,web=False):
    import harness_bridge as bridge
    stale=row['status'] in ACTIVE and row['revision']!=p['revision']
    status='stale' if stale else row['status']
    stage=r['stage']
    result={'task_id':row['id'],'project_id':p['id'],'workflow_version':2,'kind':r['kind'],
            'status':status,'stage':stage,'stage_label':LABELS.get(stage,stage),'revision':row['revision'],
            'created_at':row['created_at'],'updated_at':row['updated_at'],
            'goal':r['goal'],'events':r['events'],'plan':r.get('plan'),
            'evidence':r.get('evidence',[]),'human_confirmation':r.get('human_confirmation'),
            'verification':r.get('verification'),'repair_count':r['repair_count'],
            'plan_hash':q.content_hash(r['plan']) if r.get('plan') else None,
            'references':[{k:i.get(k,'') for k in ('id','title','source_url','locator','checked_on','content_hash')} for i in r['knowledge']['results']],
            'workbench_url':bridge.url(s,p['id']),
            'execution_note':'由Harness当前会话执行；等待人工确认时停止，无后台付费推理。'}
    if status=='done':
        if not web:result.update(bridge.project_result(s,p))
        return result
    if web:return result
    if status not in ('ready','needs_repair'):
        result['next_step']='请用户在工作台确认事实或处理任务；不得伪造人工确认。' if status=='waiting_human' else '请处理任务状态后继续；不自动重试或重复计费。'
        return result
    context={**r['sources'],'plan':r.get('plan'),'evidence':r.get('evidence',[]),
             'human_confirmation':r.get('human_confirmation'), 'confirmed_facts':r.get('confirmed_facts',[])}
    if stage in ('verify_bundle','repair_bundle'):
        context.update(candidate=r['candidate'],changes=r['changes'],last_verification=r.get('verification'))
    elif stage.startswith(('draft_','revise_')):
        doc=stage.split('_')[1]
        if r['kind']=='revise':context['baseline_document']=r['baseline']['draft'][doc]
        if doc=='privacy':context['service_document']=r['candidate']['service']
    instructions=q.INSTRUCTIONS.get(stage,ai_gateway.TASKS.get(stage,''))
    if stage.startswith('revise_'):
        instructions+='\n每项修改须填写issue_ids、fact_ids、knowledge_ids，关联本任务已核对的问题、事实和依据。无依据不得编造，使用待确认占位并列入blockers。'
    result.update(instructions=bridge.HARNESS_PROMPT+'\n'+instructions+'\n'+knowledge.POLICY,
                  output_schema=output_schema(stage),project_data=context,knowledge_context=r['knowledge'],
                  next_step='使用当前Harness会话模型完成本阶段，通过yueding_submit_result提交。')
    return result


def prepare(s,pid,owner,data):
    import harness_bridge as bridge
    p=project(s,pid,owner);kind=data.get('kind')
    if kind not in ('draft','revise'):raise UserError('质量任务支持起草或业务变更修订。',422)
    if data.get('revision')!=p['revision']:raise UserError('项目已变化，请重新读取。',409,'agent_task_stale')
    payload=bridge.context(s,p,kind,data)
    signature=q.content_hash({'kind':kind,'payload':payload,'knowledge_ids':data.get('knowledge_ids',[])})
    with s.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        p=project(s,pid,owner)
        if data.get('revision')!=p['revision']:raise UserError('项目已变化，请重新读取。',409,'agent_task_stale')
        c.execute("UPDATE agent_runs SET status='stale' WHERE project_id=? AND revision<>? AND status IN ('ready','waiting_human','needs_repair','blocked')",(pid,p['revision']))
        old=c.execute("SELECT * FROM agent_runs WHERE project_id=? AND status IN ('ready','waiting_human','needs_repair','blocked')",(pid,)).fetchone()
        if old:
            r=json.loads(old['record'])
            if r['signature']==signature:return view(s,old,p,r)
            raise UserError('已有Agent任务，请先处理或取消。',409,'agent_task_active')
        legacy=c.execute("SELECT id FROM harness_tasks WHERE project_id=? AND revision=? AND status='waiting'",(pid,p['revision'])).fetchone()
        if legacy:
            raise UserError('已有旧版Harness任务（编号：'+legacy['id']+'），请先查询并完成或取消。',409,'agent_task_active')
        sources={'material':p['material'],'change':payload.get('change',''),'confirmation':payload.get('confirmation','')}
        r={'kind':kind,'goal':('分析业务变化并生成经核验的候选修订' if kind=='revise' else '起草并核验两份协议'),
           'signature':signature,'sources':sources,'baseline':payload.get('baseline'),
           'stage':stages(kind)[0],'candidate':{},'changes':{},'documents':{},'submissions':{},
           'repair_count':0,'events':[],'contract_version':q.VERSION}
        r['knowledge']=knowledge.snapshot(s,p,kind,{**payload,'knowledge_ids':data.get('knowledge_ids',[])},owner,c)
        if kind=='draft':
            source_facts=p['analysis']['facts']
            fact_ids=[f['id'] for f in source_facts]
            r['plan']={'summary':p['analysis']['summary'],'facts':source_facts,'issues':[
                {'id':'I1','topic':'事实与条款对应','query':'协议 功能 主体 联系方式 告知','fact_ids':fact_ids,'priority':'critical'},
                {'id':'I2','topic':'服务协议和隐私政策口径一致','query':'个人信息 处理目的 供应商 第三方 保存期限','fact_ids':fact_ids,'priority':'critical'},
                {'id':'I3','topic':'业务场景与依据适用条件','query':p['analysis'].get('scope_note') or p['analysis']['summary'],'fact_ids':fact_ids,'priority':'normal'}], 'questions':[]}
            r['confirmed_facts']={'analysis':p['analysis'],'answers':p['answers'],'confirmed_by':p['confirmed_by'],'confirmed_at':p.get('confirmed_at')}
            r['sources'].update(analysis=p['analysis'],answers=p['answers'])
        tid=secrets.token_hex(16);at=s.now();event(s,r,'created','任务已建立，等待Harness执行')
        c.execute('INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?)',(tid,pid,p['revision'],'ready',s.dumps(r),at,at))
        return view(s,c.execute('SELECT * FROM agent_runs WHERE id=?',(tid,)).fetchone(),p,r)


def get(s,tid,owner,web=False):
    with s.connect() as c:row,p,r=row_for(s,tid,owner,c)
    return view(s,row,p,r,web)


def list_runs(s,pid,owner,web=False):
    if pid:project(s,pid,owner)
    with s.connect() as c:
        rows=c.execute('SELECT * FROM agent_runs '+('WHERE project_id=? ' if pid else '')+'ORDER BY created_at DESC LIMIT 100', (pid,) if pid else ()).fetchall()
    result=[]
    for row in rows:
        try:p=project(s,row['project_id'],owner)
        except UserError:continue
        result.append(view(s,row,p,json.loads(row['record']),True))
    return {'tasks':result}


def add_knowledge(s,tid,owner,data):
    with s.connect() as c:
        c.execute('BEGIN IMMEDIATE');row,p,r=row_for(s,tid,owner,c);check_live(row,p)
        if r['stage']!='evidence_review' or row['status']!='ready':
            raise UserError('仅可在依据核对阶段补充知识；生成后不得更换任务依据。',409,'agent_evidence_frozen')
        values=data.get('knowledge_ids');q.bounded(values,'补充知识',8,1)
        if any(not isinstance(k,str) for k in values):q.fail('知识编号格式无效。')
        items={i['id']:i for i in r['knowledge']['results']}
        for kid in values:
            item=knowledge.get(s,kid,owner,c)
            if not knowledge.eligible(item,r['knowledge']['as_of']):q.fail('知识未经审核、失效或尚未生效。')
            items[kid]=item
        if len(items)>24:q.fail('任务参考最多24项，请按问题选择。')
        r['knowledge']['results']=list(items.values());event(s,r,'knowledge_added','补充核对依据：'+str(len(values))+'项')
        save(s,c,row,r)
        return view(s,row,p,r)


def confirm(s,tid,owner,data):
    with s.connect() as c:
        c.execute('BEGIN IMMEDIATE');row,p,r=row_for(s,tid,owner,c);check_live(row,p)
        if row['status']!='waiting_human':raise UserError('当前任务不在业务确认阶段。',409)
        if data.get('revision')!=row['revision'] or data.get('plan_hash')!=q.content_hash(r['plan']):
            raise UserError('确认内容已变化，请重新打开任务。',409,'agent_confirmation_stale')
        if data.get('confirmed') is not True:raise UserError('请人工勾选业务事实确认。',422)
        answers=data.get('answers',{})
        expected={x['id'] for x in r['plan']['questions']}
        if not isinstance(answers,dict) or set(answers)!=expected:raise UserError('请回答本轮全部业务追问。',422)
        answers={k:s.text(v,'业务回答',6000) for k,v in answers.items()}
        person=s.text(data.get('confirmed_by'),'业务确认人',80)
        r['human_confirmation']={'answers':answers,'confirmed_by':person,'at':s.now(),'plan_hash':data['plan_hash'],
                                 'note':s.text(data.get('note'),'事实取舍与来源说明',6000)}
        r['stage']='revise_service';event(s,r,'human_confirmed','业务确认完成，可继续修订')
        save(s,c,row,r,'ready');row=c.execute('SELECT * FROM agent_runs WHERE id=?',(tid,)).fetchone()
        return view(s,row,p,r,True)


def cancel(s,tid,owner):
    with s.connect() as c:
        c.execute('BEGIN IMMEDIATE');row,p,r=row_for(s,tid,owner,c)
        if row['status'] not in ACTIVE:return {'cancelled':False,'task_id':tid}
        event(s,r,'cancelled','用户取消任务，正文及定稿保留');save(s,c,row,r,'cancelled')
        return {'cancelled':True,'task_id':tid}


def submit(s,tid,owner,data):
    import harness_bridge as bridge
    with s.connect() as c:
        c.execute('BEGIN IMMEDIATE');row,p,r=row_for(s,tid,owner,c)
        stage=data.get('stage');raw=data.get('result');digest=q.content_hash(raw)
        # Idempotent replay of previously accepted stages never rewrites content.
        prior=r['submissions'].get(stage)
        if prior==digest:return view(s,row,p,r)
        check_live(row,p)
        if row['status'] not in ('ready','needs_repair') or stage!=r['stage']:
            raise UserError('阶段不匹配或正在等待人工处理，请先读取任务。',409,'agent_stage_mismatch')
        bridge.strict(raw,output_schema(stage));knowledge.check_citations(raw,r['knowledge'])
        if len(s.dumps(raw))>400000:q.fail('阶段结果过大。')
        result=json.loads(s.dumps(raw));status='ready'
        if stage=='assess_change':
            q.validate_plan(result,r['sources']);r['plan']=result
            queries=[i['query'] for i in result['issues']]
            extra=knowledge.search_many(s,queries,owner,'all',12,c)
            items={i['id']:i for i in r['knowledge']['results']}
            items.update({i['id']:i for i in extra['results']})
            r['knowledge']['results']=list(items.values())
            r['knowledge']['issue_queries']=queries;r['stage']='evidence_review'
        elif stage=='evidence_review':
            q.validate_evidence(result,r['plan'],r['knowledge']);r['evidence']=result['evidence']
            if r['kind']=='revise':r['stage']='confirm_change';status='waiting_human'
            else:r['stage']='draft_service'
        elif stage.startswith(('draft_','revise_')):
            ai_gateway.validate(result,stage);doc=stage.split('_')[1]
            if stage.startswith('revise_'):
                q.validate_changes(result['changes'],r)
                result['document']=ai_gateway.apply_patches(r['baseline']['draft'][doc],result['changes'])
                ai_gateway.review_operational_claims(result,{**r['sources'],'baseline_document':r['baseline']['draft'][doc]})
            r['candidate'][doc]=result['document'];r['documents'][doc]=result;r['changes'][doc]=result.get('changes',[])
            r['stage']=r['kind']+'_privacy' if doc=='service' else 'verify_bundle'
        elif stage=='verify_bundle':
            q.validate_verification(result,r);r['verification']=result
            if any(i['status']=='issue' for i in result['checks']):
                if r['repair_count']>=2:status='blocked';event(s,r,'repair_limit','两轮修复后仍有问题，请人工处理或取消后重新准备')
                else:r['stage']='repair_bundle';status='needs_repair'
            else:
                combined={'service':r['candidate']['service'],'privacy':r['candidate']['privacy'],
                          'reviews':[],'blockers':[],'changes':[]}
                for doc in ('service','privacy'):
                    combined['reviews']+=r['documents'][doc]['reviews'];combined['blockers']+=r['documents'][doc]['blockers']
                    combined['changes'] += [{**x,'document':doc} for x in r['changes'].get(doc,[])]
                combined['blockers']=list(dict.fromkeys(combined['blockers']+q.warnings(r,result)))
                for check in result['checks']:
                    if check['status']!='pass':combined['reviews'].append({'clause':check['clause'],'issue':'Agent核验：'+check['finding'],
                         'basis':'核验建议，仍需法务核对原文与适用条件。','url':'','suggestion':'处理本轮记录的事实或依据缺口。'})
                quality={'version':q.VERSION,'plan':r['plan'],'evidence':r.get('evidence',[]),
                         'human_confirmation':r.get('human_confirmation'),'verification':result,
                         'repair_count':r['repair_count'],'candidate_hash':s.doc_hash(combined),
                         'label':'模型核验记录 · 待法务审阅','warnings':q.warnings(r,result)}
                combined['provenance']={'kind':'harness','runtime':'current-session-model','task_id':tid,
                      'prompt_version':ai_gateway.PROMPT_VERSION,'knowledge':r['knowledge'],'quality':quality,
                      'source_status':'经程序约束与模型核验的候选稿，未经法务批准。'}
                action={'revision':p['revision']}
                if r['kind']=='revise':action.update(change=r['sources']['change'],confirmation=r['sources']['confirmation'])
                p=s.perform(p['id'],r['kind'],action,external_result=combined,connection=c)
                r['stage']='done';status='done'
        elif stage=='repair_bundle':
            if r['repair_count']>=2:raise UserError('已达到修复上限。',409,'agent_repair_limit')
            for doc in ('service','privacy'):
                patches=result[doc+'_changes'];q.validate_changes(patches,r)
                r['candidate'][doc]=ai_gateway.apply_patches(r['candidate'][doc],patches)
                if patches:
                    # Keep original and subsequent patches as a truthful chronological audit.
                    r['changes'][doc]+=patches;r['documents'][doc]['document']=r['candidate'][doc]
            r['repair_count']+=1;r['stage']='verify_bundle'
        r['submissions'][stage]=digest
        # Verification and repair can recur: only the last accepted attempt is replayable.
        if stage=='repair_bundle':r['submissions'].pop('verify_bundle',None)
        if stage=='verify_bundle' and status=='needs_repair':r['submissions'].pop('repair_bundle',None)
        event(s,r,'stage_completed',LABELS.get(stage,stage)+'已提交')
        save(s,c,row,r,status);row=c.execute('SELECT * FROM agent_runs WHERE id=?',(tid,)).fetchone()
        return view(s,row,p,r)


def web_handle(s,method,pid,tid=None,action=None,data=None):
    data=data or {};p=s.get_project(pid)
    if p.get('engine')!='harness':raise UserError('请先将真实项目授权给Harness。',409)
    owner=p.get('harness_owner')
    if not owner:raise UserError('项目缺少Harness授权。',403)
    if tid:
        with s.connect() as c:row,_,r=row_for(s,tid,owner,c)
        if row['project_id']!=pid:raise UserError('任务不属于此项目。',404)
    if method=='GET':
        result=get(s,tid,owner,True) if tid else list_runs(s,pid,owner,True)
        if tid and r.get('plan'):result['plan_hash']=q.content_hash(r['plan'])
        return result
    if not tid:return prepare(s,pid,owner,{**data,'kind':data.get('kind','revise')})
    if action=='confirm':return confirm(s,tid,owner,data)
    if action=='cancel':return cancel(s,tid,owner)
    raise UserError('任务操作不存在。',404)
