// Controlled fixture results test transport and human gates, not model quality.
const {chromium,request}=require('playwright');const fs=require('fs');const path=require('path');const assert=require('assert/strict');
(async()=>{
 const base=process.env.WORKBENCH_URL||'http://127.0.0.1:8774';
 const api=await request.newContext({baseURL:base,extraHTTPHeaders:{Authorization:'Bearer '+'b'.repeat(40),'X-Workspace-Request':'1'}});
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:900},reducedMotion:'reduce'});
 const errors=[],jobs=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/\/jobs\/(analyze|draft|revise|chat)$/.test(r.url()))jobs.push(r.url());});
 const seed=JSON.parse(fs.readFileSync(path.join(__dirname,'../demo.json'),'utf8'));
 async function call(route,body){const r=body===undefined?await api.get(route):await api.post(route,{data:body});const result=await r.json();assert(r.ok(),JSON.stringify({route,status:r.status(),error:result.error}));return result;}
 try{
  let {project:p}=await call('/api/harness/projects',{name:'Harness 浏览器验收'});
  ({project:p}=await call(`/api/harness/projects/${p.id}/material`,{revision:p.revision,material:fs.readFileSync(path.join(__dirname,'fixtures/追剧时光PRD.md'),'utf8')}));
  let task=await call(`/api/harness/projects/${p.id}/prepare`,{revision:p.revision,kind:'analyze'});
  const analysis={...seed.analysis};delete analysis.provenance;
  ({project:p}=await call(`/api/harness/tasks/${task.task_id}/submit`,{stage:'analyze',result:analysis}));
  await page.goto(base+'/?project='+p.id);await page.locator('#confirmed-by').waitFor();
  assert((await page.locator('.statusbar').innerText()).includes('Harness 账号模型'));
  assert(await page.locator('#chat-input').count()===0);
  for(const q of analysis.questions)await page.locator(`[data-field="answer:${q.id}"]`).fill(seed.answers[q.id]);
  await page.locator('#confirmed-by').fill('浏览器人工确认测试');
  await page.locator('[data-action="confirm"]').first().click();
  await page.locator('.workflow-guide [data-action="harness-info"]').waitFor();
  await page.locator('.workflow-guide [data-action="harness-info"]').click();
  assert((await page.locator('#modal').innerText()).includes('不使用工作台的硅基流动密钥'));
  await page.locator('[data-action="close"]').click();
  ({project:p}=await call(`/api/harness/projects/${p.id}`));
  task=await call(`/api/harness/projects/${p.id}/prepare`,{revision:p.revision,kind:'draft'});
  task=await call(`/api/harness/tasks/${task.task_id}/submit`,{stage:task.stage,result:{document:seed.draft.service,reviews:seed.draft.reviews,blockers:seed.draft.blockers}});
  const result=await call(`/api/harness/tasks/${task.task_id}/submit`,{stage:task.stage,result:{document:seed.draft.privacy,reviews:[],blockers:[]}});
  assert(result.status==='done');await page.reload();await page.locator('#rich-editor').waitFor();
  assert((await page.locator('#rich-editor').innerText()).includes('S-01'));
  await page.locator('[data-ai-tab="review"]').click();await page.locator('.review-check').first().waitFor();
  assert(await page.locator('.flow-step').count()===6);
  await page.locator('[data-action="settings"]').click();assert(await page.locator('#key').count()===0);
  await page.locator('[data-action="close"]').click();
  const out=path.join(__dirname,'../test-results');fs.mkdirSync(out,{recursive:true});
  await page.screenshot({path:path.join(out,'harness-workbench.png')});
  await page.locator('.review-check>summary').first().click();
  await page.locator('[data-action="discuss-review"]').first().click();
  assert((await page.locator('#harness-question').inputValue()).includes(p.id));
  await page.locator('[data-action="close"]').click();
  await page.locator('[data-action="new"]').click();await page.locator('#new-name').fill('旧项目切换验收');
  await page.locator('[data-action="create"]').click();
  await page.waitForFunction(()=>document.querySelector('#project-select')?.selectedOptions[0]?.textContent==='旧项目切换验收'&&!document.querySelector('#modal')?.open);
  await page.locator('[data-action="settings"]').click();await page.locator('[data-action="connect-harness"]').click();
  await page.locator('#harness-consent').check();await page.locator('[data-action="confirm-harness"]').click();
  await page.waitForFunction(()=>document.querySelector('.statusbar')?.innerText.includes('Harness 账号模型')&&!document.querySelector('#modal')?.open);
  const listed=await call('/api/harness/projects');assert(listed.some(project=>project.name==='旧项目切换验收'));
  assert.deepEqual(errors,[]);assert.deepEqual(jobs,[]);
  console.log(JSON.stringify({ok:true,flows:['plugin-project','long-prd','analysis-import','human-confirmation','two-stage-draft','harness-guidance','legal-review-question','human-project-handoff','no-server-generation-requests'],pageErrors:errors,serverModelJobs:jobs.length}));
 }catch(error){
  console.error(JSON.stringify({pageErrors:errors,body:(await page.locator('body').innerText()).slice(0,1600)}));
  throw error;
 }finally{await browser.close();await api.dispose();}
})().catch(e=>{console.error(e);process.exitCode=1;});
