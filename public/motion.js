'use strict';

// Presentation only: no task is submitted and no review is approved by motion.
const Motion=(()=>{
 const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
 let preference='running', lastView='', completedProject='', completedUntil=0, timer;
 const seenReplies=new Set();
 try{preference=localStorage.getItem('agreement-motion')||'running';}catch{}
 const enabled=()=>preference!=='paused'&&!reduced.matches;
 function state(){
  const p=S.p,job=activeJob();
  if(job)return {kind:'busy',title:'约定正在协作',detail:jobProgress(job)};
  if(S.busy)return {kind:'busy',title:'正在同步项目',detail:'保存工作进度，稍等片刻'};
  if(completedProject===p.id&&Date.now()<completedUntil)return {kind:'complete',title:'这一步，已完成',detail:'继续按照上方流程推进'};
  if(S.jobs[0]?.status==='failed')return {kind:'attention',title:'这一步需要再试一次',detail:'请查看右侧任务原因'};
  const stage=workflowStage();
  const copy=[['一起理清业务事实','准备 PRD，或导入业务材料'],['把事实确认清楚','补充关键问题与确认来源'],['准备起草两份协议','业务事实已确认，随时开始'],['让每一条约定更稳妥','逐项审阅，再记录法律取舍'],['审阅已确认','记录定稿结论并保存版本'],['本轮定稿已归档','留意变化，按计划复核']][stage];
  return {kind:stage===5?'archived':'idle',title:copy[0],detail:copy[1]};
 }
 function imageSource(){
  const visible=!document.hidden&&!S.focus&&(innerWidth>650||S.filesOpen);
  return enabled()&&visible?'/assets/companion-idle.webp':'/assets/companion-still.png';
 }
 function buttonLabel(){return reduced.matches?'系统设置已减少动态效果':enabled()?'暂停动效':'恢复动效';}
 function companion(){
  const s=state();
  return `<section class="companion" data-state="${s.kind}" aria-label="约定动态助手"><div class="companion-top"><span><i class="companion-dot"></i> 约定 · 工作陪伴</span><button class="motion-toggle" data-action="toggle-motion" aria-label="${buttonLabel()}" title="${buttonLabel()}" aria-pressed="${!enabled()}" ${reduced.matches?'disabled':''}>${reduced.matches?'—':enabled()?'Ⅱ':'▷'}</button></div><div class="companion-stage" aria-hidden="true"><div class="companion-halo"></div><div class="companion-orbit"></div><img class="companion-image" src="${imageSource()}" alt="" width="160" height="160"><span class="companion-spark spark-one">✦</span><span class="companion-spark spark-two">✧</span><span class="companion-ground"></span></div><div class="companion-copy"><strong>${s.title}</strong><small>${s.detail}</small></div></section>`;
 }
 function refresh(){
  document.documentElement.dataset.motion=enabled()?'running':'paused';
  const card=document.querySelector('.companion');if(!card||!S.p)return;
  const s=state();card.dataset.state=s.kind;
  const title=card.querySelector('.companion-copy strong'),detail=card.querySelector('.companion-copy small');
  if(title.textContent!==s.title)title.textContent=s.title;
  if(detail.textContent!==s.detail)detail.textContent=s.detail;
  const image=card.querySelector('img'),src=imageSource();
  // Preserve the decoded animation across task polling and progress updates.
  if(image.getAttribute('src')!==src)image.src=src;
  const control=card.querySelector('.motion-toggle');
  control.disabled=reduced.matches;control.setAttribute('aria-label',buttonLabel());control.title=buttonLabel();
  control.setAttribute('aria-pressed',String(!enabled()));control.textContent=reduced.matches?'—':enabled()?'Ⅱ':'▷';
 }
 function entrance(){const key=[S.p.id,S.view,S.version?.number||'current'].join(':');const changed=key!==lastView;lastView=key;return changed?'view-enter':'';}
 function replyClass(message){
  if(message.role!=='assistant')return '';
  const key=S.p.id+':'+message.id;if(seenReplies.has(key))return '';
  seenReplies.add(key);return message===S.p.messages.at(-1)?'reply-enter':'';
 }
 function toggle(){
  preference=enabled()?'paused':'running';
  try{localStorage.setItem('agreement-motion',preference);}catch{toast('当前动效设置已生效，浏览器暂时无法保存偏好。');}
  refresh();
 }
 function complete(project){
  completedProject=project;completedUntil=Date.now()+6000;clearTimeout(timer);
  timer=setTimeout(refresh,6100);refresh();
 }
 reduced.addEventListener('change',refresh);
 document.addEventListener('visibilitychange',refresh);
 window.addEventListener('resize',refresh);
 window.addEventListener('storage',e=>{if(e.key==='agreement-motion'){preference=e.newValue||'running';refresh();}});
 // Establish the preference before the first screen paints.
 document.documentElement.dataset.motion=enabled()?'running':'paused';
 return {companion,refresh,entrance,replyClass,toggle,complete};
})();
