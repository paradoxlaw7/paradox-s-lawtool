const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const errors=[],badAssets=[];page.on('pageerror',e=>errors.push(e.message));
 page.on('response',r=>{if(/\/(motion\.(js|css)|assets\/companion-)/.test(r.url())&&r.status()>=400)badAssets.push(r.url());});
 await page.goto('http://127.0.0.1:8766');await page.locator('#project-select').waitFor();
 await page.locator('[data-action="new"]').click();await page.locator('#new-name').fill('界面回归 · 动效验收');await page.locator('#new-mode').selectOption('demo');await page.locator('[data-action="create"]').click();
 await page.waitForFunction(()=>document.querySelector('#project-select')?.selectedOptions[0]?.textContent==='界面回归 · 动效验收'&&!document.querySelector('#modal')?.open);
 await page.locator('.companion-image').waitFor();
 assert((await page.locator('.companion-image').getAttribute('src')).endsWith('.webp'));
 assert(await page.locator('.flow-step').count()===6);
 const out=path.join(__dirname,'../test-results');fs.mkdirSync(out,{recursive:true});
 await page.screenshot({path:path.join(out,'workbench-motion-desktop.png')});
 await page.locator('[data-action="toggle-motion"]').click();
 assert((await page.locator('.companion-image').getAttribute('src')).endsWith('.png'));
 assert(await page.locator('html').getAttribute('data-motion')==='paused');
 await page.reload();await page.locator('.companion-image').waitFor();
 assert(await page.locator('html').getAttribute('data-motion')==='paused');
 await page.locator('[data-action="toggle-motion"]').click();
 await page.emulateMedia({reducedMotion:'reduce'});
 await page.waitForFunction(()=>document.documentElement.dataset.motion==='paused');
 assert((await page.locator('.companion-image').getAttribute('src')).endsWith('.png'));
 assert(await page.locator('[data-action="toggle-motion"]').isDisabled());
 assert(await page.locator('.companion-image').evaluate(el=>getComputedStyle(el).animationName)==='none');
 await page.emulateMedia({reducedMotion:'no-preference'});
 await page.waitForFunction(()=>document.documentElement.dataset.motion==='running');
 await page.locator('[data-action="focus"]').click();
 assert((await page.locator('.companion-image').getAttribute('src')).endsWith('.png'));
 await page.locator('[data-action="focus"]').click();
 // A fixture job exercises polling and failure presentation, with no model request.
 let fail=false;const job={id:'motion-fixture',action:'analyze',status:'running',progress:{},error:''};
 await page.route('**/jobs/analyze',r=>r.fulfill({status:202,contentType:'application/json',body:JSON.stringify(job)}));
 await page.route('**/jobs',r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify([{...job,status:fail?'failed':'running',error:fail?'动效测试：任务失败，业务材料保留。':''}])}));
 await page.locator('[data-action="analyze"]').click();
 await page.waitForFunction(()=>document.querySelector('.companion')?.dataset.state==='busy');
 await page.evaluate(()=>window.motionImage=document.querySelector('.companion-image'));
 await page.waitForTimeout(1800);
 assert(await page.evaluate(()=>window.motionImage===document.querySelector('.companion-image')),'Polling restarted the animation element');
 // Pausing remains available while document actions are locked by a running job.
 await page.locator('[data-action="toggle-motion"]').click();
 assert(await page.locator('html').getAttribute('data-motion')==='paused');
 await page.locator('[data-action="toggle-motion"]').click();
 fail=true;await page.waitForFunction(()=>document.querySelector('.companion')?.dataset.state==='attention');
 assert(!(await page.locator('.companion-copy').innerText()).includes('已完成'));
 await page.setViewportSize({width:390,height:844});
 await page.waitForFunction(()=>document.querySelector('.companion-image')?.getAttribute('src').endsWith('.png'));
 await page.locator('.top-actions [data-action="toggle-files"]').click();
 await page.waitForFunction(()=>document.querySelector('.companion-image')?.getAttribute('src').endsWith('.webp'));
 assert(await page.locator('.companion').isVisible());
 await page.screenshot({path:path.join(out,'workbench-motion-mobile.png')});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.setViewportSize({width:1440,height:1000});
 await page.locator('.top-actions [data-action="toggle-files"]').evaluate(el=>el.click());
 await page.unroute('**/jobs');await page.unroute('**/jobs/analyze');
 for(let n=1;n<=3;n++){
  await page.locator('#chat-input').fill('示例动效验收 '+n+'：请核对业务承诺');
  await page.locator('[data-action="send"]').click();
  try{await page.waitForFunction(n=>document.querySelectorAll('.message.assistant').length===n,n);}catch(e){console.log(await page.evaluate(()=>({error:S.error,busy:locked(),pending:pendingDocuments()})));throw e;}
  assert(await page.locator('.companion').getAttribute('data-state')==='complete');
  assert(await page.locator('.flow-step[aria-current="step"]').getAttribute('data-step')==='0','Animation changed legal workflow progress');
 }
 assert.deepStrictEqual(errors,[]);assert.deepStrictEqual(badAssets,[]);
 console.log(JSON.stringify({ok:true,checks:['animated-asset-load','six-step-preservation','pause-and-resume','preference-persistence','reduced-motion','focus-mode','working-state','polling-does-not-restart-GIF','pause-during-work','failure-not-success','mobile-file-drawer','no-overflow','three-demo-chat-rounds','completion-feedback-does-not-approve'],errors}));
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
