'use strict';
// Exercise the shipped decision dialog in a real DOM, without clinical data or a service.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.ECG_PLAYWRIGHT_CORE||process.env.PLAYWRIGHT_CORE||'playwright-core');
(async()=>{
 const browser=await chromium.launch({headless:true,chromiumSandbox:true,executablePath:process.env.ECG_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 try{
  const page=await browser.newPage();await page.setContent('<button id="origin">Origin</button>');
  await page.addScriptTag({content:fs.readFileSync(path.join(__dirname,'../static/js/report-range-editor.js'),'utf8')});
  async function open(mode='success'){
   await page.evaluate(mode=>{document.querySelector('#origin').focus();window.saves=0;window.discards=0;window.owner=true;window.done=null;
    window.task=ECGUnsavedNavigation.resolve({title:'Unsaved range',detail:'Synthetic interval',saveLabel:'Save',discardLabel:'Discard',isCurrent:()=>owner,
     save:async()=>{saves++;if(mode==='failure')throw Error('save failed');if(mode==='late')await new Promise(r=>window.finishSave=r);},discard:()=>{discards++;}}).then(value=>{done=value;});
   },mode);await page.locator('#unsavedChangesDialog').waitFor();
  }
  await open();await page.locator('[data-unsaved-stay]').click();assert.deepEqual(await page.evaluate(()=>[done,saves,discards]),[false,0,0]);assert.equal(await page.evaluate(()=>document.activeElement.id),'origin');
  await open();assert.equal(await page.evaluate(()=>ECGUnsavedNavigation.resolve({title:'second'})),false);assert.equal(await page.locator('dialog').count(),1);await page.locator('[data-unsaved-save]').click();assert.deepEqual(await page.evaluate(()=>[done,saves,discards]),[true,1,0]);
  await open();await page.locator('[data-unsaved-discard]').click();assert.deepEqual(await page.evaluate(()=>[done,saves,discards]),[true,0,1]);
  await open('failure');await page.locator('[data-unsaved-save]').click();assert.equal(await page.locator('[role=alert]').innerText(),'save failed');assert.equal(await page.evaluate(()=>done),null);assert(await page.locator('#unsavedChangesDialog').isVisible());await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>done),false);
  await open();await page.evaluate(()=>owner=false);await page.locator('[data-unsaved-save]').click();assert.deepEqual(await page.evaluate(()=>[done,saves]),[false,0]);
  await open('late');await page.locator('[data-unsaved-save]').click();assert(await page.locator('[data-unsaved-discard]').isDisabled());await page.evaluate(()=>{owner=false;finishSave();});await page.locator('dialog').waitFor({state:'detached'});assert.equal(await page.evaluate(()=>done),false);
  async function prepareConfirmation(){
   await page.evaluate(()=>{
    window.saves=0;
    window.preparing=ECGUnsavedNavigation.resolve({title:'Review',detail:'Preparing evidence',
     prepare:()=>new Promise((resolve,reject)=>{window.ready=()=>resolve({detail:'Validated',save:async()=>{saves++;}});window.failPreparation=reject;})});
   });
   assert(await page.locator('#unsavedChangesDialog').isVisible());
   assert(await page.locator('[data-unsaved-save]').isDisabled());
  }
  await prepareConfirmation();await page.evaluate(()=>{window.firstReady=ready;});
  await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>preparing),false);
  await prepareConfirmation();await page.evaluate(()=>firstReady());assert(await page.locator('[data-unsaved-save]').isDisabled());
  await page.evaluate(()=>ready());await page.locator('[data-unsaved-save]').click();
  assert.equal(await page.evaluate(()=>preparing),true);assert.equal(await page.evaluate(()=>saves),1);
  await prepareConfirmation();await page.evaluate(()=>failPreparation(Error('Evidence changed')));
  assert.equal(await page.locator('[role=alert]').innerText(),'Evidence changed');assert(await page.locator('[data-unsaved-save]').isDisabled());
  await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>preparing),false);
  console.log('Unsaved dialog: stay/save/discard, deduplication, errors, Escape, focus, owner changes and late save passed');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
