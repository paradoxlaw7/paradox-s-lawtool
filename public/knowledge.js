/* Reference library opens separately, preserving document space and the six-step workflow. */
window.YuedingKnowledge=(()=>{
 const state={tab:'library',items:[],selected:null,query:'',scenario:'all'};
 const kinds={legislation:'法规依据',playbook:'审查规则',clause:'条款范例',case:'复盘案例',reference:'参考资料'};
 const scopes={general:'通用',streaming:'短剧播放',ai_generation:'AI 生成'};
 const states={active:'可检索参考',pending:'待审核',rejected:'未采纳',retired:'已撤下'};
 const effects={in_force:'已核实生效',not_applicable:'非规范性资料',draft:'征求意见稿',superseded:'已失效',unknown:'效力待核实'};
 const field=(key,label,value='',type='text')=>`<label class="field-label" for="kb-${key}">${label}</label><input id="kb-${key}" type="${type}" value="${esc(value)}">`;
 const area=(key,label,value='')=>`<label class="field-label" for="kb-${key}">${label}</label><textarea id="kb-${key}" class="field">${esc(value)}</textarea>`;
 const select=(key,label,options,value)=>`<label class="field-label" for="kb-${key}">${label}</label><select id="kb-${key}" class="field">${Object.entries(options).map(([v,t])=>`<option value="${v}" ${v===value?'selected':''}>${t}</option>`).join('')}</select>`;
 function snapshot(){
  // Never display current-project references as evidence for an older, uninstrumented document.
  if(S.version)return S.version.draft?.provenance?.knowledge;
  if(S.p?.draft)return S.p.draft.provenance?.knowledge;
  return S.p?.analysis?.provenance?.knowledge;
 }
 function shell(body){
  openModal('知识与依据',`<div class="kb-caption"><img src="/assets/companion-still.png" alt="约定助手"><div>先确认适用场景，再使用依据。<small>内置资料是整理样本，新增资料经法务审核后才参与检索。</small></div></div><nav class="kb-tabs">${[['library','资料检索'],['pending','候选审核'],['used','本次依据'],['guide','采集指引']].map(([k,t])=>`<button class="btn ${state.tab===k?'primary':''}" data-action="kb-tab" data-tab="${k}">${t}</button>`).join('')}<span></span>${btn('kb-new','＋ 添加资料')}</nav><div id="kb-body">${body}</div>`);
  modal.classList.add('knowledge-dialog');
 }
 function card(i,frozen=false){return `<button class="kb-card" data-action="kb-detail" data-id="${esc(i.id)}" ${frozen?'data-frozen="1"':''}><span class="kb-meta">${esc(kinds[i.kind]||i.kind)} · ${esc(i.review_label)} · ${esc(states[i.state]||i.state)}</span><strong>${esc(i.title)}</strong><p>${esc(i.applicability)}</p><small>${esc(i.locator)} · 核验 ${esc(i.checked_on)}</small>${i.freshness_warning?`<small class="kb-warning">${esc(i.freshness_warning)}</small>`:''}</button>`;}
 function draw(){
  if(state.tab==='new')return editor();
  if(state.tab==='guide')return shell(`<div class="kb-guide"><h3>把一份文件，整理成可使用的知识</h3><ol><li>优先从人大、政府和主管部门官网找正式文本，记录来源链接、条号、生效日期与核验日期。征求意见稿单独保留，不能当现行依据。</li><li>按一个主题拆成一条：写明触发条件、例外、需要追问的事实和审查动作。不要整部法律或整份PRD直接当通用指令。</li><li>内部指引和已批准条款保留原件位置、适用项目与版本；复盘案例先脱敏。竞品协议只作参考，不是法律依据。</li><li>上传Word或粘贴摘录，补齐元数据后提交候选。网页法务审核通过后，Agent才能检索；改版时新增条目并撤下旧条目。</li><li>起草时只按需注入相关条目；知识库更新不回写既有定稿。每轮任务保留自己的依据快照。</li></ol><p>当前检索采用中文双字词 BM25、同义词扩展和标题加权，不使用付费向量模型。支持指定场景筛选；场景提示不是法律适用结论。</p><p>本版不自动抓取网址、不收取邮件、不做实时法规巡检。可以让 Harness 搜集官方材料后提交候选，并由法务核验。</p></div>`);
  if(state.tab==='used'){
   const snap=snapshot();state.items=snap?.results||[];
   return shell(`<p class="kb-help">${snap?`任务依据快照 · ${esc(stamp(snap.captured_at))} · 场景提示：${esc(scopes[snap.scenario]||snap.scenario)}。这是当时的参考资料，不表示全部被模型采用，也不表示已完成法务核验。`:'当前文档尚无知识依据快照。Harness 新任务完成后在这里回查。旧稿不会自动补写依据。'}</p><div class="kb-grid">${state.items.map(i=>card(i,true)).join('')}</div>`);
  }
  const pending=state.tab==='pending';
  shell(`${pending?'<p class="kb-help">只展示待审核资料。审核记录会保留；通过后可供对应连接或工作台共享检索。</p>':`<div class="kb-search"><input id="kb-query" placeholder="例如：新增声音克隆，需要确认哪些授权？" value="${esc(state.query)}"><select id="kb-scenario" aria-label="知识检索场景"><option value="all">全部场景</option>${Object.entries(scopes).map(([k,t])=>`<option value="${k}" ${state.scenario===k?'selected':''}>${t}</option>`).join('')}</select>${btn('kb-search','检索','primary')}</div><p class="kb-help">结果按相关性排序。未审核、已撤下、尚未生效和失效资料不用于检索；资料覆盖不足时需补充查证。</p>`}<div class="kb-grid">${state.items.length?state.items.map(i=>card(i)).join(''):'<p class="kb-help">暂无符合条件的资料。可以换个具体问题，或添加资料。</p>'}</div>`);
 }
 async function open(tab='library'){
  state.tab=tab;
  if(['used','guide','new'].includes(tab)){draw();return;}
  const all=(await api('/api/knowledge')).entries;
  state.items=all.filter(i=>tab==='pending'?i.state==='pending':i.state==='active');draw();
 }
 function editor(prefill={}){
  shell(`<p class="kb-help">一条资料只处理一个主题；不会自动访问来源网址。上传只提取正文供整理，不会直接入库。网页提交的审核通过资料为工作台共享参考。</p><div class="kb-import">${btn('kb-upload','从 Word 提取正文')}<input id="kb-file" type="file" accept=".docx,.txt,.md" hidden><span id="kb-upload-name"></span></div><form id="kb-form" class="kb-form">${field('title','标题',prefill.title)}<div class="kb-columns">${select('kind','资料类型',kinds,prefill.kind||'playbook')}${select('scenario','适用场景',scopes,prefill.scenarios?.[0]||'general')}</div>${area('content','主题摘录或审查规则（最多6000字）',prefill.content)}${area('applicability','什么时候适用',prefill.applicability)}${area('exclusions','例外及不适用情形',prefill.exclusions)}${field('source_url','官方或原始来源 HTTPS 链接；内部资料可留空',prefill.source_url)}<div class="kb-columns">${field('publisher','发布机关或内部资料来源',prefill.publisher)}${field('locator','条号、章节或原件位置',prefill.locator)}</div><div class="kb-columns">${field('checked_on','人工核验日期',today(),'date')}${select('legal_status','效力状态',effects,prefill.legal_status||'not_applicable')}</div><div class="kb-columns">${field('effective_on','生效日期（如适用）',prefill.effective_on||'','date')}${field('valid_until','失效日期（如适用）',prefill.valid_until||'','date')}</div>${field('tags','关键词（逗号分隔）',prefill.tags?.join('，'))}<div class="card-actions">${btn('kb-save','提交候选，等待审核','primary')}</div></form>`);
 }
 async function detail(id,frozen=false){
  const i=frozen?state.items.find(i=>i.id===id):await api('/api/knowledge/'+id);state.selected=i;
  const source=i.source_url?`<a href="${esc(safeUrl(i.source_url))}" target="_blank" rel="noopener noreferrer">打开来源原文 ↗</a>`:'内部原件，按下列位置回查';
  const controls=!frozen&&(i.state==='pending'||i.state==='active')?`<div class="kb-review"><h3>${i.state==='pending'?'法务审核':'撤下参考资料'}</h3>${field('reviewer','审核人')}${area('note','核对结果或撤下原因')}<label class="checkline"><input id="kb-confirmed" type="checkbox">我已核对来源、效力及适用边界，并确认本次操作。</label><div class="card-actions">${i.state==='pending'?btn('kb-review','审核通过，纳入检索','primary','data-decision="approve"')+btn('kb-review','不采纳','','data-decision="reject"'):btn('kb-review','撤下，不用于后续检索','','data-decision="retire"')}</div></div>`:'';
  shell(`<div class="kb-detail"><div class="card-actions">${btn('kb-back','← 返回列表')}${!frozen?btn('kb-history','审核记录'):''}${btn('kb-copy-entry','整理为新版候选')}</div><span class="kb-meta">${esc(kinds[i.kind])} · ${esc(i.review_label)}${frozen?' · 历史快照':''}</span><h3>${esc(i.title)}</h3><p class="kb-help">效力：${esc(effects[i.legal_status])} · 核验 ${esc(i.checked_on)} · 生效 ${esc(i.effective_on||'未设置')} · 失效 ${esc(i.valid_until||'未设置')}</p><h4>参考内容</h4><div class="kb-copy">${esc(i.content)}</div><h4>适用条件</h4><p>${esc(i.applicability)}</p><h4>例外与边界</h4><p>${esc(i.exclusions||'未补充，使用前需核对。')}</p><h4>来源与定位</h4><p>${source}<br>${esc(i.publisher)}<br>${esc(i.locator)}</p><code>${esc(i.citation)}</code><p class="kb-help">引用标记用于内部审阅意见；不要放进面向用户的协议正文。</p>${controls}</div>`);
 }
 async function action(a,el){
  if(a==='kb-open')return open();
  if(a==='kb-tab')return open(el.dataset.tab);
  if(a==='kb-new'){state.tab='new';return editor();}
  if(a==='kb-back')return open(state.tab==='new'?'pending':state.tab);
  if(a==='kb-detail')return detail(el.dataset.id,el.dataset.frozen==='1');
  if(a==='kb-search'){
   state.query=$('#kb-query').value;state.scenario=$('#kb-scenario').value;
   const out=await api('/api/knowledge/search',{query:state.query,scenario:state.scenario});state.items=out.results;draw();return;
  }
  if(a==='kb-upload'){return $('#kb-file').click();}
  if(a==='kb-save'){
   const keys=['title','kind','content','applicability','exclusions','source_url','locator','publisher','checked_on','effective_on','valid_until','legal_status'];
   const value=Object.fromEntries(keys.map(k=>[k,$('#kb-'+k).value]));value.scenarios=[$('#kb-scenario').value];value.tags=$('#kb-tags').value.split(/[,，]/).map(x=>x.trim()).filter(Boolean);
   await api('/api/knowledge/propose',value);toast('已提交候选；审核前不参与生成。');return open('pending');
  }
  if(a==='kb-review'){
   await api('/api/knowledge/'+state.selected.id+'/review',{revision:state.selected.revision,decision:el.dataset.decision,reviewer:$('#kb-reviewer').value,note:$('#kb-note').value,confirmed:$('#kb-confirmed').checked});
   toast('审核操作已记录。既有任务和定稿保持原依据快照。');return open(state.tab);
  }
  if(a==='kb-copy-entry'){state.tab='new';return editor(state.selected);}
  if(a==='kb-history'){
   const out=await api('/api/knowledge/'+state.selected.id+'/history');
   const old=$('#kb-history');if(old)old.remove();$('#kb-body').insertAdjacentHTML('beforeend',`<div id="kb-history" class="kb-help">${out.events.length?out.events.map(e=>`<p>${esc(stamp(e.at))} · ${esc(e.event)} · ${esc(e.actor==='harness'?'Harness 提交':e.actor)}<br>${esc(JSON.parse(e.payload).note||'已保留操作记录')}</p>`).join(''):'内置资料，无人工审核记录。'}</div>`);return;
  }
 }
 document.addEventListener('submit',e=>{if(e.target.id==='kb-form')e.preventDefault();});
 document.addEventListener('change',async e=>{
  if(e.target.id!=='kb-file')return;
  try{
   const file=e.target.files[0];if(!file)return;if(file.size>3000000)throw Error('请选择3MB以内的文档。');
   const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let n=0;n<bytes.length;n+=8192)binary+=String.fromCharCode(...bytes.subarray(n,n+8192));
   const out=await api('/api/upload',{name:file.name,content:btoa(binary)});
   if(out.text.length>6000){toast('原文较长，已提取前6000字供整理，请按主题拆分并核对原件。');}
   $('#kb-content').value=out.text.slice(0,6000);$('#kb-locator').value=out.name;$('#kb-upload-name').textContent=out.name;
  }catch(error){toast(error.message);}
 });
 document.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.id==='kb-query'){e.preventDefault();action('kb-search').catch(error=>toast(error.message));}});
 return {open,action};
})();
