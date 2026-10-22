const {chromium}=require('playwright');
const assert=require('assert/strict');
const fs=require('fs');const path=require('path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:900}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(process.env.WORKBENCH_URL||'http://127.0.0.1:8768');
  await page.locator('#project-select').waitFor();
  await page.locator('[data-action="new"]').click();
  await page.locator('#new-name').fill('编辑空间验收');
  await page.locator('[data-action="create"]').click();
  await page.waitForFunction(()=>document.querySelector('#project-select')?.selectedOptions[0]?.textContent==='编辑空间验收');
  await page.locator('#rich-editor').fill('# 测试 PRD\n这是保留的业务材料。');
  await page.locator('[data-action="guide-help"]').click();
  assert(await page.locator('#flow-description').isVisible());
  assert((await page.locator('#rich-editor').innerText()).includes('保留的业务材料'));
  await page.locator('[data-action="guide-help"]').click();
  await page.locator('[data-action="save"]').click();
  await page.reload();await page.locator('#rich-editor').waitFor();
  assert((await page.locator('#rich-editor').innerText()).includes('保留的业务材料'));
  const measurements=[];
  for(const viewport of [{width:1440,height:900},{width:1280,height:720},{width:375,height:812}]){
   await page.setViewportSize(viewport);
   const result=await page.evaluate(()=>{
    const c=document.querySelector('.center-panel').getBoundingClientRect();
    const s=document.querySelector('.editor-scroll').getBoundingClientRect();
    const p=document.querySelector('.paper').getBoundingClientRect();
    const e=document.querySelector('#rich-editor').getBoundingClientRect();
    return {editorShare:s.height/c.height,paperShare:p.width/s.width,visibleTextHeight:Math.max(0,Math.min(e.bottom,s.bottom)-Math.max(e.top,s.top)),overflow:document.documentElement.scrollWidth>innerWidth};
   });
   assert(result.editorShare>.53,JSON.stringify({viewport,...result}));
   assert(result.paperShare>.90,JSON.stringify({viewport,...result}));
   assert(!result.overflow,JSON.stringify({viewport,...result}));
   assert(await page.locator('.flow-step').count()===6);
   assert(await page.locator('.workflow-guide [data-action="analyze"]').isVisible());
   measurements.push({viewport,...result});
  }
  await page.setViewportSize({width:1440,height:900});
  await page.route('**/api/status',r=>r.fulfill({contentType:'application/json',body:JSON.stringify({ready:true,local_config:false,connection_scope:'server',model:'test-deepseek',format:'auto'})}));
  await page.locator('[data-action="settings"]').click();
  assert((await page.locator('#modal').innerText()).includes('服务器共享模型'));
  assert((await page.locator('#modal').innerText()).includes('无需提供个人密钥'));
  assert(await page.locator('#key').count()===0);
  await page.locator('[data-action="close"]').click();
  await page.locator('[data-action="focus"]').click();
  assert(await page.locator('.center-panel').evaluate(el=>el.getBoundingClientRect().width)>1400);
  const out=path.join(__dirname,'../test-results');fs.mkdirSync(out,{recursive:true});
  await page.screenshot({path:path.join(out,'editor-space-focus.png')});
  await page.locator('[data-action="focus"]').click();
  await page.screenshot({path:path.join(out,'editor-space-desktop.png')});
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({ok:true,measurements,pageErrors:errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
