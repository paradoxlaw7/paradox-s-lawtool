const {chromium}=require('playwright');const assert=require('assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const base=process.env.WORKBENCH_URL||'http://127.0.0.1:8769';
 const errors=[];const results=[];
 async function session(options={}){const c=await browser.newContext(options);const p=await c.newPage();p.on('pageerror',e=>errors.push(e.message));return {c,p};}
 try{
  let {c,p}=await session();await p.goto(base);
  await p.locator('.entrance-video').waitFor();
  await p.waitForFunction(()=>document.querySelector('video')?.readyState>=2);
  const metadata=await p.locator('video').evaluate(v=>({duration:v.duration,width:v.videoWidth,height:v.videoHeight,muted:v.muted,playsInline:v.playsInline}));
  assert(Math.abs(metadata.duration-4.6)<.04);assert.equal(metadata.width,1280);assert.equal(metadata.height,720);assert(metadata.muted&&metadata.playsInline);
  assert(await p.locator('#app').getAttribute('inert')!==null);
  await p.locator('.entrance').waitFor({state:'detached',timeout:7500});await p.locator('#project-select').waitFor();
  assert(await p.locator('#app').getAttribute('inert')===null);
  await p.reload();await p.locator('#project-select').waitFor();assert.equal(await p.locator('.entrance').count(),0);
  results.push({normalPlayback:true,metadata,refreshDoesNotReplay:true});await c.close();
  ({c,p}=await session());await p.goto(base);await p.locator('.entrance-skip').click();await p.locator('.entrance').waitFor({state:'detached'});assert(await p.locator('#app').getAttribute('inert')===null);results.push('skip-button');await c.close();
  ({c,p}=await session());await p.goto(base);await p.locator('.entrance-skip').waitFor();await p.keyboard.press('Escape');await p.locator('.entrance').waitFor({state:'detached'});results.push('escape-to-skip');await c.close();
  ({c,p}=await session({reducedMotion:'reduce'}));let requested=false;p.on('request',r=>{if(r.url().endsWith('.mp4'))requested=true;});await p.goto(base);await p.locator('#project-select').waitFor();assert.equal(await p.locator('.entrance').count(),0);assert(!requested);results.push('reduced-motion-no-video-download');await c.close();
  ({c,p}=await session());await p.route('**/entrance-v1.mp4',r=>r.abort());await p.goto(base);await p.locator('.entrance').waitFor({state:'detached',timeout:3500});await p.locator('#project-select').waitFor();assert(await p.locator('#app').getAttribute('inert')===null);results.push('video-failure-restores-workbench');await c.close();
  ({c,p}=await session());await p.addInitScript(()=>{HTMLMediaElement.prototype.play=function(){return Promise.reject(new Error('Playback disabled'));};});await p.goto(base);await p.locator('#project-select').waitFor();await p.locator('.entrance').waitFor({state:'detached'});results.push('autoplay-rejection');await c.close();
  ({c,p}=await session({viewport:{width:375,height:812}}));await p.goto(base);await p.locator('.entrance-skip').waitFor();assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await p.locator('.entrance-skip').click();await p.locator('.entrance').waitFor({state:'detached'});results.push('mobile-no-overflow');await c.close();
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,results,pageErrors:errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
