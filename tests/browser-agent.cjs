// Controlled outputs exercise the real HTTP/UI flow; no paid inference.
const {chromium,request}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{
 const base='http://127.0.0.1:18778',out=path.join(__dirname,'../test-results');
 const fixture=JSON.parse(fs.readFileSync(path.join(out,'agent-browser-fixture.json'),'utf8')),pid=fixture.project_id;
 const client=await request.newContext({baseURL:base,extraHTTPHeaders:{Authorization:'Bearer '+'c'.repeat(40),'X-Workspace-Request':'1'}});
 async function call(route,body){const r=body===undefined?await client.get(route):await client.post(route,{data:body});const v=await r.json();assert(r.ok(),JSON.stringify(v));return v;}
 const existing=(await call('/api/harness/projects/'+pid)).project;
 if(existing.draft&&!existing.draft.archived_as)await call(`/api/projects/${pid}/archive`,{revision:existing.revision,hash:existing.draft.hash,approver:'受控浏览器回归',note:'仅用于重新运行隔离样例',confirmed:true});
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'}),errors=[],modelRequests=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/\/jobs\/(analyze|draft|revise|chat)$/.test(r.url()))modelRequests.push(r.url());});
 try{
  await page.goto(base+'/?project='+pid);await page.locator('[data-action="agent-open"]').first().waitFor();
  await page.locator('[data-action="agent-open"]').first().click();await page.locator('[data-action="agent-new"]').click();
  await page.locator('#agent-change').fill('更换SDK，具体数据接收范围待确认。');await page.locator('#agent-source').fill('产品负责人提供变更说明。');
  await page.locator('[data-action="agent-create"]').click();await page.locator('#agent-body').getByText('等待 Harness 执行',{exact:false}).waitFor();
  let list=await call('/api/harness/agent/tasks?project_id='+pid),t=await call('/api/harness/tasks/'+list.tasks[0].task_id);
  const tid=t.task_id;assert.equal(t.stage,'assess_change');
  async function submit(value){t=await call(`/api/harness/tasks/${tid}/submit`,{stage:t.stage,result:value});return t;}
  await submit({summary:'核对供应商变化',facts:[{id:'F1',label:'供应商变化 <img src=x onerror=alert(1)>',value:'计划更换SDK',status:'material',source:'change',quote:'更换SDK'}],
   issues:[{id:'I1',topic:'第三方数据处理',query:'SDK 供应商 第三方 数据',priority:'critical',fact_ids:['F1']}],
   questions:[{id:'Q1',question:'实际接收哪些数据？',reason:'避免补造范围',fact_ids:['F1']}]});
  await submit({evidence:[{issue_id:'I1',support:'gap',explanation:'实际数据范围待确认，仍需核验依据适用条件。',quotes:[]}]});
  assert.equal(t.status,'waiting_human');await page.locator('[data-action="agent-refresh"]').click();await page.locator('#agent-person').waitFor();
  assert.equal(await page.locator('#agent-body img').count(),0);
  await page.locator('#agent-answer-Q1').fill('仅接收业务确认的数据字段；受控测试。');await page.locator('#agent-person').fill('业务验收人');
  await page.locator('#agent-note').fill('已核对变更材料，未明确事项保留待确认。');
  await page.locator('[data-action="agent-confirm"]').click();await page.waitForFunction(()=>document.querySelector('#toast')?.textContent.includes('人工勾选'));
  assert.equal(await page.locator('#agent-person').inputValue(),'业务验收人');
  await page.screenshot({path:path.join(out,'agent-confirmation.png'),fullPage:false});
  await page.locator('#agent-consent').check();await page.locator('[data-action="agent-confirm"]').click();
  await page.locator('#agent-person').waitFor({state:'detached'});t=await call('/api/harness/tasks/'+tid);assert.equal(t.stage,'revise_service');
  for(const doc of ['service','privacy'])await submit({reviews:[],blockers:[],changes:[]});
  assert.equal(t.stage,'verify_bundle');const current=await call('/api/harness/projects/'+pid);assert.equal(current.project.draft.hash,fixture.baseline_hash);
  const checks=['facts','evidence','consistency','coverage'].map(kind=>({kind,status:kind==='evidence'?'unknown':'pass',document:'both',clause:'整体',excerpt:'',
   finding:kind==='evidence'?'依据适用关系仍待人工核验':'受控样例核对记录',fact_ids:kind==='facts'?['F1']:[],knowledge_ids:[]}));
  await submit({summary:'受控流程验收，不作为法律准确率证明',checks,coverage:['service','privacy'].map(document=>({issue_id:'I1',document,disposition:'unchanged',reason:'受控样例保留正文，依据缺口进入待决事项。'}))});
  assert.equal(t.status,'done');assert(t.project.draft.provenance.quality.warnings.length);
  await page.locator('[data-action="agent-refresh"]').click();await page.locator('[data-action="agent-show-draft"]').waitFor();
  await page.locator('[data-action="agent-show-draft"]').click();await page.locator('[data-action="agent-report"]').click();
  await page.locator('#agent-body').getByText('依据适用关系仍待人工核验',{exact:true}).first().waitFor();
  await page.screenshot({path:path.join(out,'agent-verification.png'),fullPage:false});
  await page.locator('[data-action="close"]').click();await page.setViewportSize({width:390,height:844});
  await page.locator('[data-action="agent-open"]').first().click();assert(await page.locator('#agent-body').isVisible());
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  assert.deepEqual(errors,[]);assert.deepEqual(modelRequests,[]);
  const report={ok:true,createFromWeb:true,groundedPlan:true,humanGate:true,inputPreserved:true,candidateCommitAfterVerification:true,
   escapedContent:true,desktopAndMobile:true,pageErrors:errors,serverModelRequests:modelRequests.length,paidModelCalls:0};
  fs.writeFileSync(path.join(out,'agent-browser-check.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close();await client.dispose();}
})().catch(e=>{console.error(e);process.exitCode=1;});
