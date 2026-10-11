'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const app=fs.readFileSync('static/js/app.js','utf8'),listeners=new Map(),attrs=new Map();
const host={dataset:{},innerHTML:''};
const track={parentElement:{querySelector:()=>({textContent:'II'})},closest:()=>track,
  getAttribute:name=>attrs.get(name),setAttribute:(name,value)=>attrs.set(name,value),removeAttribute:name=>attrs.delete(name),getBoundingClientRect:()=>({left:100,width:300})};
const root={querySelector:selector=>selector==='#sttCurrentContext'?host:null,querySelectorAll:()=>[track],contains:node=>node===track,
  classList:{toggle(){},remove(){}},addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:name=>listeners.delete(name)};
const state={caseId:'synthetic-navigation',leads:['II','V1','V5'],sttStart:120,sttDuration:10};
const environment=vm.createContext({state,ALL_LEADS:['II','V1','V5'],$:()=>root,setSttStart:value=>{state.sttStart=Math.max(0,Math.min(value,290));}});
vm.runInContext(fs.readFileSync('static/js/stt-review-layout.js','utf8'),environment);
vm.runInContext(app.slice(app.indexOf('function sttReviewLayout('),app.indexOf('function sttSelectionSnapshot(')),environment);
const layout=environment.sttReviewLayout();
for(const [key,start,expected] of [['ArrowRight',120,136],['ArrowLeft',120,104],['Enter',120,120],[' ',120,120],['ArrowLeft',0,0],['ArrowRight',290,290]]){
  state.sttStart=start;
  layout.render({caseId:state.caseId,status:'ready',start_s:start,duration_s:10,total_s:300,leadNames:state.leads,measurementMs:60});
  let prevented=false;listeners.get('keydown')({target:track,key,preventDefault(){prevented=true;}});
  assert.equal(state.sttStart,expected,`${key} moved the production window incorrectly`);assert.equal(prevented,true);
}
listeners.get('click')({target:track,clientX:250});assert.equal(state.sttStart,145,'trend click must center the requested point');
layout.clear('正在读取另一病例');listeners.get('keydown')({target:track,key:'ArrowRight',preventDefault(){assert.fail('stale trend handled key');}});
assert.equal(state.sttStart,145);
console.log('ST production trend navigation: exact ±16s, Enter/Space preserve window, center click, bounds and stale basis passed');
