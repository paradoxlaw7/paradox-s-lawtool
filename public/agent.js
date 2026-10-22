'use strict';
// The task panel never starts model requests or impersonates human confirmation.
window.YuedingAgent=(()=>{
 let env=null,pid=null,selected=null,timer=null,last='',busy=false;
 const drafts=new Map(),$=s=>document.querySelector(s);
 const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const status={ready:'等待 Harness 执行',waiting_human:'需要你确认事实',needs_repair:'候选稿待修复',blocked:'需要人工处理',done:'候选稿已保存',stale:'项目已变化',cancelled:'已取消'};
 const source={material:'原业务材料',change:'本次业务变化',confirmation:'变更来源说明'};
 const kinds={facts:'事实依据',evidence:'法律与规则依据',consistency:'两份协议一致性',coverage:'变化处理覆盖'};
 const support={supported:'已摘录支持原文 · 待法务核验',partial:'依据部分支持',gap:'依据有缺口'};
 const button=(a,t,extra='')=>`<button type="button" class="btn" data-action="${a}" ${extra}>${t}</button>`;
 const safe=x=>{try{const u=new URL(x);return u.protocol==='https:'?u.href:'#';}catch{return '#';}};
 function capture(){if(!selected)return;const values={};document.querySelectorAll('#agent-body [data-agent-input]').forEach(e=>values[e.id]=e.type==='checkbox'?e.checked:e.value);drafts.set(selected,values);}
 function restore(){for(const [id,value] of Object.entries(drafts.get(selected)||{})){const el=document.getElementById(id);if(el){if(el.type==='checkbox')el.checked=value;else el.value=value;}}}
 function shell(body){return `<div id="agent-body"><p class="small subtle">目标、阶段成果与核验记录保存在工作台。模型执行由 Harness 当前会话承担，人工确认后在同一任务继续。</p>${body}</div>`;}
 function report(v){return `<p>${esc(v.summary)}</p>${(v.checks||[]).map(c=>`<div class="agent-item"><strong>${esc(kinds[c.kind]||c.kind)} · ${esc(({pass:'模型未发现问题',issue:'需修复',unknown:'仍需核实'})[c.status])}</strong><p>${esc(c.finding)}</p>${c.excerpt?`<blockquote>${esc(c.excerpt)}</blockquote>`:''}<small>${esc(c.clause)} ${esc((c.fact_ids||[]).join('、'))} ${esc((c.knowledge_ids||[]).join('、'))}</small></div>`).join('')}<details><summary>逐项处理记录</summary>${(v.coverage||[]).map(c=>`<p>${esc(c.issue_id)} · ${c.document==='service'?'服务协议':'隐私政策'} · ${esc(({changed:'已修改',unchanged:'无需修改',pending:'待确认'})[c.disposition])}<br>${esc(c.reason)}</p>`).join('')}</details>`;}
 function detail(t){
  const active=['ready','waiting_human','needs_repair','blocked','stale'].includes(t.status),plan=t.plan;
  return shell(`<div class="agent-toolbar">${button('agent-open','← 所有任务')}${button('agent-refresh','刷新状态')}${active?button('agent-cancel','取消任务'):''}${t.status==='done'?button('agent-show-draft','查看候选稿'):''}</div><h3>${esc(t.goal)}</h3><div class="notice">${esc(status[t.status]||t.status)} · ${esc(t.stage_label)}${['ready','needs_repair'].includes(t.status)?'<p>在 Harness 中说“读取约定待办任务并继续”，即可沿用本任务；不必复制材料或重新生成已完成阶段。</p>':''}${t.status==='blocked'?'<p>已达到两轮修复上限。请检查核验问题；可取消后补充材料重新准备，正文及旧定稿保留。</p>':''}</div>
   ${plan?`<section><h3>事实与问题清单</h3><p>${esc(plan.summary)}</p>${plan.facts.map(f=>`<details class="agent-item"><summary>${esc(f.id)} · ${esc(f.label)} · ${esc(({material:'材料记载',unknown:'未知',conflict:'冲突',confirmed:'材料记载',pending:'待确认'})[f.status]||f.status)}</summary><p>${esc(f.value)}</p>${f.quote?`<blockquote>${esc(f.quote)}</blockquote>`:''}<small>${esc(source[f.source]||f.source)}</small></details>`).join('')}${plan.issues.map(i=>`<div class="agent-item"><strong>${esc(i.id)} · ${esc(i.topic)}</strong><p>检索问题：${esc(i.query)}</p><small>关联事实 ${esc(i.fact_ids.join('、'))}</small></div>`).join('')}</section>`:''}
   ${t.evidence?.length?`<section><h3>问题依据与缺口</h3>${t.evidence.map(e=>`<div class="agent-item"><strong>${esc(e.issue_id)} · ${esc(support[e.support])}</strong><p>${esc(e.explanation)}</p>${e.quotes.map(x=>{const ref=t.references.find(i=>i.id===x.knowledge_id);return `<blockquote>${esc(x.quote)}</blockquote><small>${esc(ref?.title||x.knowledge_id)} · ${esc(ref?.locator||'')}${ref?.source_url?` <a href="${esc(safe(ref.source_url))}" target="_blank" rel="noopener">核对来源</a>`:''}</small>`;}).join('')}</div>`).join('')}</section>`:''}
   ${t.status==='waiting_human'?`<section class="agent-confirm"><h3>确认本轮业务事实</h3><p>请核对材料中的描述，明确未知及冲突如何处理。这里只确认业务事实；依据的法律适用仍需法务审阅。</p>${plan.questions.map(x=>`<label class="field-label" for="agent-answer-${esc(x.id)}">${esc(x.question)}</label><p class="small">${esc(x.reason)}</p><textarea class="field" id="agent-answer-${esc(x.id)}" data-agent-input data-question="${esc(x.id)}"></textarea>`).join('')}<label class="field-label" for="agent-person">业务确认人或责任岗位</label><input id="agent-person" data-agent-input><label class="field-label" for="agent-note">事实取舍、未明确事项及来源说明</label><textarea class="field" id="agent-note" data-agent-input></textarea><label class="agent-check"><input type="checkbox" id="agent-consent" data-agent-input>我已核对本轮事实与问题；不确定的事项已如实说明。</label>${button('agent-confirm','确认事实，允许继续修订')}</section>`:''}
   ${t.human_confirmation?`<details class="agent-item"><summary>本轮业务确认记录</summary><p>${esc(t.human_confirmation.confirmed_by)} · ${esc(t.human_confirmation.at)}</p><p>${esc(t.human_confirmation.note)}</p>${Object.entries(t.human_confirmation.answers).map(([k,v])=>`<p>${esc(k)}：${esc(v)}</p>`).join('')}</details>`:''}
   ${t.verification?`<section><h3>模型核验记录 · 修复 ${t.repair_count} 轮</h3><p class="small">程序检查引用、原文定位与覆盖完整性；语义结论仍需人工核验。</p>${report(t.verification)}</section>`:''}
   <details><summary>任务进度记录</summary>${t.events.map(e=>`<p class="small">${esc(new Date(e.at).toLocaleString('zh-CN'))} · ${esc(e.detail)}</p>`).join('')}</details>`);
 }
 async function load(force=false){
  const dialog=$('#modal');if(!dialog?.open||!$('#agent-body')){clearTimeout(timer);return;}
  const target=`/api/projects/${pid}/agent`+(selected?'/'+selected:'');
  const value=await env.api(target);const signature=JSON.stringify(value);
  if(force||signature!==last){capture();last=signature;
   const content=selected?detail(value):shell(`<div class="agent-toolbar">${button('agent-new','＋ 新建业务变更任务')}${button('agent-start-draft','起草并核验两份协议')}${button('agent-refresh','刷新')}</div>${value.tasks.length?value.tasks.map(t=>`<div class="agent-item"><strong>${esc(t.goal)}</strong><p>${esc(status[t.status]||t.status)} · ${esc(t.stage_label)}</p>${button('agent-select','查看任务',`data-task="${esc(t.task_id)}"`)}</div>`).join(''):'<p>尚无质量任务。可以提交业务变化，也可以在 Harness 中准备起草任务。</p>'}`);
   $('#agent-body').outerHTML=content;restore();
  }
  clearTimeout(timer);timer=setTimeout(()=>load().catch(()=>{const b=$('#agent-body');if(b&&!b.querySelector('.agent-network'))b.insertAdjacentHTML('afterbegin','<p class="notice agent-network">暂时无法读取任务。已输入的回答保留，请点击刷新。</p>');}),2500);
 }
 async function open(){clearTimeout(timer);selected=null;last='';env.openModal('Agent 任务',shell('<p>正在读取任务…</p>'));$('#modal').classList.add('agent-dialog');await load(true);}
 async function create(kind,data){env.cache();const value=await env.api(`/api/projects/${pid}/agent`,{kind,revision:env.project.revision,...data});selected=value.task_id;last='';env.openModal('Agent 任务',shell('<p>任务已建立，正在读取…</p>'));$('#modal').classList.add('agent-dialog');await load(true);}
 async function action(a,el,context){
  if(busy)return;env=context;pid=env.project.id;
  try{busy=true;
   if(a==='agent-open')return await open();
   if(a==='agent-select'){capture();selected=el.dataset.task;last='';$('#agent-body').innerHTML='<p>正在读取任务…</p>';return await load(true);}
   if(a==='agent-refresh')return await load(true);
   if(a==='agent-start-draft')return await create('draft',{});
   if(a==='agent-start-revise')return await create('revise',{change:env.form('change',''),confirmation:env.form('change_confirmation','')});
   if(a==='agent-new'){
    clearTimeout(timer);selected=null;env.openModal('新建业务变更任务',shell('<label class="field-label" for="agent-change">本次业务变化</label><textarea id="agent-change" class="field"></textarea><label class="field-label" for="agent-source">确认来源、材料出处及尚不确定的事项</label><textarea id="agent-source" class="field"></textarea>'+button('agent-create','建立分析与修订任务')));$('#modal').classList.add('agent-dialog');return;
   }
   if(a==='agent-create')return await create('revise',{change:$('#agent-change').value,confirmation:$('#agent-source').value});
   if(a==='agent-confirm'){
    capture();const current=await env.api(`/api/projects/${pid}/agent/${selected}`),answers={};document.querySelectorAll('[data-question]').forEach(x=>answers[x.dataset.question]=x.value);
    await env.api(`/api/projects/${pid}/agent/${selected}/confirm`,{revision:current.revision,plan_hash:current.plan_hash,answers,confirmed_by:$('#agent-person').value,note:$('#agent-note').value,confirmed:$('#agent-consent').checked});drafts.delete(selected);return await load(true);
   }
   if(a==='agent-cancel'){await env.api(`/api/projects/${pid}/agent/${selected}/cancel`,{});return await load(true);}
   if(a==='agent-show-draft'){clearTimeout(timer);return await env.refresh();}
   if(a==='agent-report'){
    clearTimeout(timer);const d=env.draft,quality=d?.provenance?.quality;
    if(!quality)throw Error('当前文档还没有Agent核验记录。');
    const stale=quality.candidate_hash!==d.hash;
    env.openModal('本轮质量核验',shell(`<div class="notice">${stale?'正文在核验后发生变化，此记录仅对应原候选稿。':'核验记录对应当前候选正文。'} 模型核验记录供法务审阅，不能代替批准。</div>${report(quality.verification)}${quality.warnings.length?`<h3>待核实事项</h3>${quality.warnings.map(w=>`<p>${esc(w)}</p>`).join('')}`:''}`));$('#modal').classList.add('agent-dialog');return;
   }
  }finally{busy=false;}
 }
 return {action};
})();
