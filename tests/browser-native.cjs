const {chromium}=require('playwright');const fs=require('fs');const path=require('path');const assert=require('assert');
(async()=>{
const browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto('http://127.0.0.1:8766');await page.locator('#project-select').waitFor();
await page.locator('[data-action="new"]').click();await page.locator('#new-name').fill('原生Word回归');await page.locator('[data-action="create"]').click();
await page.waitForFunction(()=>document.querySelector('#project-select')?.selectedOptions[0]?.textContent==='原生Word回归'&&!document.querySelector('#modal')?.open);
await page.locator('.doc-menu>summary').click();await page.locator('[data-action="word-replace"]').click();
await page.locator('#word-picker').setInputFiles(path.join(__dirname,'../test-results/追剧时光-导出校验.docx'));
await page.waitForFunction(()=>document.querySelector('#rich-editor')?.innerText.includes('十二、协议生成要求'));
const [download]=await Promise.all([page.waitForEvent('download'),page.locator('[data-action="export-word"]').click()]);
assert.deepStrictEqual(fs.readFileSync(await download.path()),fs.readFileSync(path.join(__dirname,'../test-results/追剧时光-导出校验.docx')));
assert(!(await page.locator('#file-tree').innerText()).includes('.md'));
await page.locator('[data-ai-tab="review"]').click();assert(await page.locator('#chat-input').count()===0);await page.locator('[data-ai-tab="chat"]').click();assert(await page.locator('#chat-input').isVisible());
await page.locator('[data-action="focus"]').click();assert(!(await page.locator('.files-panel').isVisible()));assert(!(await page.locator('.assistant-panel').isVisible()));await page.locator('[data-action="focus"]').click();assert(await page.locator('.files-panel').isVisible());
await page.screenshot({path:path.join(__dirname,'../test-results/workbench-clean.png')});
assert.deepStrictEqual(errors,[]);console.log(JSON.stringify({ok:true,flows:['word-reimport','native-byte-roundtrip','hide-markdown','review-chat-tabs','focus-mode'],errors}));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
