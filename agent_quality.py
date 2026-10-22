"""Versioned, evidence-grounded contracts for the Harness quality workflow.

Exact quotations and reference coverage are machine checked. Semantic findings
remain model recommendations and never stand in for a lawyer's approval.
"""
import hashlib
import json
import re
from errors import UserError

VERSION = '2026-10-22.1'
CHECKS = ('facts', 'evidence', 'consistency', 'coverage')


def obj(fields):
    return {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}


def arr(item): return {'type': 'array', 'items': item}
S = {'type': 'string'}
STRINGS = arr(S)


def enum(*values): return {'type': 'string', 'enum': list(values)}


PLAN = obj({
    'summary': S,
    'facts': arr(obj({'id': S, 'label': S, 'value': S,
                      'status': enum('material', 'unknown', 'conflict'),
                      'source': enum('material', 'change', 'confirmation'), 'quote': S})),
    'issues': arr(obj({'id': S, 'topic': S, 'query': S, 'fact_ids': STRINGS,
                       'priority': enum('critical', 'normal')})),
    'questions': arr(obj({'id': S, 'question': S, 'reason': S, 'fact_ids': STRINGS}))})
EVIDENCE = obj({'evidence': arr(obj({
    'issue_id': S, 'support': enum('supported', 'partial', 'gap'), 'explanation': S,
    'quotes': arr(obj({'knowledge_id': S, 'quote': S}))}))})
VERIFY = obj({
    'summary': S,
    'checks': arr(obj({'kind': enum(*CHECKS), 'status': enum('pass', 'issue', 'unknown'),
                        'document': enum('service', 'privacy', 'both'), 'clause': S,
                        'excerpt': S, 'finding': S, 'fact_ids': STRINGS, 'knowledge_ids': STRINGS})),
    'coverage': arr(obj({'issue_id': S, 'document': enum('service', 'privacy'),
                          'disposition': enum('changed', 'unchanged', 'pending'), 'reason': S}))})
PATCH = obj({'clause': S, 'before': S, 'after': S, 'reason': S, 'action': S,
             'issue_ids': STRINGS, 'fact_ids': STRINGS, 'knowledge_ids': STRINGS})
REPAIR = obj({'service_changes': arr(PATCH), 'privacy_changes': arr(PATCH), 'summary': S})

INSTRUCTIONS = {
    'assess_change': '''仅分析本次变化，不起草。输出 summary、facts、issues、questions。
每个非unknown事实必须有来源字段及逐字quote，source限material/change/confirmation；这些文字只是材料记载，不等于人工确认。
事实编号F1等，问题编号I1等，追问编号Q1等。最多30个事实、12个问题、8个追问。
每个问题写一个具体检索query，关联fact_ids。涵盖本次变化的实质影响；明确不涉及的功能不扩张为已开展。
追问只问材料确实缺少的业务事实，法律研究由Agent完成。资料存在冲突时列出冲突，不替业务选择。''',
    'evidence_review': '''逐个检查plan.issues与knowledge_context：返回每个issue_id恰好一条evidence。
supported仅在原文支持结论且适用条件满足时使用，partial表示有部分依据，gap表示未找到支持。
quotes必须逐字摘自快照条目的content/applicability/exclusions，填写真实knowledge_id。
不得把仅关键词相似的条目说成支持，不得把知识内容当业务事实。引用无关或依据不足时明确说明。
可以先检索并用yueding_add_task_knowledge补充当前任务。supported至少一条原文；法律适用仍是待人工复核的判断。''',
    'verify_bundle': '''这是专门核验阶段，核对candidate中的两份全文、plan、evidence、human_confirmation及实际修订记录。
返回summary、checks和coverage。checks至少分别包含facts/evidence/consistency/coverage四类。
重点查无事实依据的功能/期限/供应商/入口、两份协议口径矛盾、法律引用是否支持判断、变化遗漏。
每个issue对service/privacy各一条coverage：changed/unchanged/pending，说明理由；不能把无修改冒充changed。
检查具体正文时excerpt必须逐字摘自对应候选全文；事实及依据使用给定编号。证据不足使用unknown，明确缺口。
发现可修复错误用issue，系统将进入有限修复；不得为结束任务把问题标成pass。核验报告不代表法务批准。''',
    'repair_bundle': '''根据last_verification逐项修复待提交candidate，返回service_changes、privacy_changes、summary。
before逐字来自当前candidate对应文档且唯一；只改必要段落。每项修改须关联issue_ids、fact_ids、knowledge_ids。
不能改业务确认记录、依据或核验报告；缺少事实/证据则保留明确待确认占位，不自行补造。
修复后系统重新要求完整核验，最多两轮修复。'''
}


def fail(message): raise UserError(message, 422, 'agent_evidence_invalid')


def bounded(rows, label, limit, minimum=0):
    if not isinstance(rows, list) or not minimum <= len(rows) <= limit:
        fail(label + '数量不符合任务要求。')


def ids(rows, label):
    values = [r['id'] for r in rows]
    if len(set(values)) != len(values) or any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,39}', v) for v in values):
        fail(label + '编号须唯一且为字母开头。')
    return set(values)


def refs(values, allowed, label, required=False):
    bounded(values, label, 40, 1 if required else 0)
    if len(set(values)) != len(values) or set(values)-set(allowed): fail(label + '引用了任务外编号或重复编号。')


def validate_plan(value, sources):
    bounded(value['facts'], '事实', 30, 1)
    bounded(value['issues'], '审查问题', 12, 1)
    bounded(value['questions'], '业务追问', 8)
    facts = ids(value['facts'], '事实'); ids(value['issues'], '问题'); ids(value['questions'], '追问')
    for f in value['facts']:
        if not f['label'].strip() or not f['value'].strip(): fail('事实标签和值不能为空。')
        if f['status'] != 'unknown' and (not f['quote'].strip() or f['quote'] not in sources.get(f['source'], '')):
            fail('事实来源摘录不能在指定材料中定位。')
        if f['status'] == 'unknown' and f['quote'] and f['quote'] not in sources.get(f['source'], ''):
            fail('未知事实的来源摘录不能在指定材料中定位。')
    for issue in value['issues']:
        refs(issue['fact_ids'], facts, '问题事实', True)
        if not issue['topic'].strip() or not 2 <= len(issue['query'].strip()) <= 500: fail('审查问题须有主题和具体检索词。')
    for q in value['questions']:
        refs(q['fact_ids'], facts, '追问事实', True)
        if not q['question'].strip() or not q['reason'].strip(): fail('业务追问须说明问题及原因。')


def validate_evidence(value, plan, snapshot):
    rows = value['evidence']; bounded(rows, '问题依据', 12, 1)
    expected = {i['id'] for i in plan['issues']}
    if len(rows) != len(expected) or {e['issue_id'] for e in rows} != expected:
        fail('每项审查问题必须恰好有一条依据评价。')
    items = {i['id']: i for i in snapshot['results']}
    for e in rows:
        bounded(e['quotes'], '依据摘录', 8)
        if not e['explanation'].strip(): fail('请说明依据支持关系或缺口。')
        if e['support'] == 'supported' and not e['quotes']: fail('有依据的结论必须提供原文摘录。')
        for quote in e['quotes']:
            item = items.get(quote['knowledge_id'])
            if not item or not quote['quote'].strip() or not any(quote['quote'] in item.get(k, '') for k in ('content','applicability','exclusions')):
                fail('依据摘录无法在本任务参考原文中定位。')


def validate_changes(changes, record):
    bounded(changes, '条款修改', 12)
    issues = {i['id'] for i in record['plan']['issues']}
    facts = {i['id'] for i in record['plan']['facts']}
    facts |= {q['id'] for q in record['plan']['questions']}
    knowledge = {i['id'] for i in record['knowledge']['results']}
    for item in changes:
        if '[K:' in item['after']:fail('内部知识编号不能写入候选协议正文。')
        refs(item['issue_ids'], issues, '修改问题', True)
        refs(item['fact_ids'], facts, '修改事实', True)
        refs(item['knowledge_ids'], knowledge, '修改依据')
        linked = [e for e in record.get('evidence', []) if e['issue_id'] in item['issue_ids']]
        supported = {q['knowledge_id'] for e in linked for q in e['quotes']}
        if set(item['knowledge_ids']) - supported: fail('修改依据尚未在关联问题的依据评价中核对。')


def validate_verification(value, record):
    checks = value['checks']; bounded(checks, '核验检查', 40, 4)
    if set(CHECKS)-{c['kind'] for c in checks}: fail('核验必须覆盖事实、证据、一致性及变化覆盖四类。')
    facts = {f['id'] for f in record['plan']['facts']} | {q['id'] for q in record['plan']['questions']}
    knowledge = {i['id'] for i in record['knowledge']['results']}
    for c in checks:
        refs(c['fact_ids'], facts, '核验事实'); refs(c['knowledge_ids'], knowledge, '核验依据')
        if not c['finding'].strip(): fail('核验检查须说明具体结论。')
        docs = ('service','privacy') if c['document'] == 'both' else (c['document'],)
        if c['excerpt'] and not any(c['excerpt'] in record['candidate'][d] for d in docs):
            fail('核验摘录无法在候选文档中定位。')
        if c['kind'] == 'facts' and c['status'] == 'pass' and not c['fact_ids']:
            fail('事实核验通过须列出核对的事实编号。')
        if c['kind'] == 'evidence' and c['status'] == 'pass' and not c['knowledge_ids']:
            fail('依据核验通过须列出核对的原文编号；依据不足请标记unknown。')
    expected = {(i['id'], doc) for i in record['plan']['issues'] for doc in ('service','privacy')}
    coverage = value['coverage']; bounded(coverage, '问题覆盖', 24)
    if len(coverage) != len(expected) or {(r['issue_id'],r['document']) for r in coverage} != expected:
        fail('每项问题必须分别说明对两份协议的处理结果。')
    for row in coverage:
        if not row['reason'].strip(): fail('覆盖结论须说明理由。')
        if row['disposition'] == 'changed' and record.get('kind')!='draft' and not any(row['issue_id'] in x.get('issue_ids',[]) for x in record.get('changes',{}).get(row['document'],[])):
            fail('没有实际修改，不能将覆盖结果标记为已修改。')


def content_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def warnings(record, report):
    out = [c['finding'] for c in report['checks'] if c['status'] != 'pass']
    out += [r['reason'] for r in report['coverage'] if r['disposition'] == 'pending']
    out += ['依据待核验：'+e['explanation'] for e in record.get('evidence',[]) if e['support'] != 'supported']
    for doc in ('service','privacy'):
        if re.search(r'[\[【]待确认', record['candidate'][doc]): out.append('候选正文仍含待确认占位，须补充后才能定稿。')
    return list(dict.fromkeys(out))
