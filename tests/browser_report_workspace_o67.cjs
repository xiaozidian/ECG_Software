'use strict';
const assert=require('node:assert/strict');
require('../static/js/report-workspace.js');
global.formatElapsed=n=>'D1 '+n.toFixed(3);
const api=global.ECGReportWorkspace;
function editor(value,start,end=start){return {value,selectionStart:start,selectionEnd:end,maxLength:12000,readOnly:false,disabled:false,inputs:0,focus(){this.focused=true},setRangeText(t,a,b){this.value=this.value.slice(0,a)+t+this.value.slice(b);this.selectionStart=this.selectionEnd=a+t.length},setSelectionRange(a,b){this.selectionStart=a;this.selectionEnd=b},dispatchEvent(e){assert.equal(e.type,'input');assert(e.bubbles);this.inputs++}};}
const e=editor('医生正文：保留选区文字。',5,9),before=e.value;
const insertion=api.insertSelectedText(e,'手动所选术语');
assert.equal(e.value,before.slice(0,9)+'手动所选术语'+before.slice(9));
assert.equal(e.inputs,1);assert.equal(api.undoInsertedText(e,insertion),true);assert.equal(e.value,before);assert.equal(e.selectionStart,5);assert.equal(e.selectionEnd,9);
const second=api.insertSelectedText(e,'术语');e.value+='继续手动编辑';const changed=e.value;
assert.equal(api.undoInsertedText(e,second),false);assert.equal(e.value,changed);
e.readOnly=true;assert.equal(api.insertSelectedText(e,'不应写入'),null);assert.equal(api.undoInsertedText(e,second),false);e.readOnly=false;e.maxLength=e.value.length;assert.equal(api.insertSelectedText(e,'超限'),null);assert.equal(api.insertSelectedText(e,''),null);
const sections=Object.freeze([{key:'summary',available:true},{key:'af',available:true},{key:'hrv_frequency',available:true},{key:'vlp',available:false,reason:'条件不足'}].map(Object.freeze));
const groups=api.pageGroups(sections);assert.deepEqual(groups.map(g=>g.items.map(s=>s.key)),[['summary'],['af'],['hrv_frequency','vlp']]);assert.equal(groups[2].items[1],sections[3]);assert.equal(groups[2].items[1].reason,'条件不足');
let activeFocus=null,windowPosition=[],dialogs=[];
class Node{
 constructor(){this.dataset={};this.isConnected=true;this.attrs={};this.children=[];this.events={};this.scrollTop=0;this.scrollLeft=0;}
 setAttribute(k,v){this.attrs[k]=v}getAttribute(k){return this.attrs[k]}hasAttribute(k){return k in this.attrs}removeAttribute(k){delete this.attrs[k]}
 focus(){activeFocus=this}closest(selector){return selector==='#reportV2Content'?root:null}contains(node){return node===button||node===focus||node===replacement}
 querySelector(selector){if(selector==='[data-rw-event-preview]')return null;return this.parts?.[selector]||null}
 querySelectorAll(selector){return this.all?.[selector]||[]}
 prepend(node){button=node}append(node){this.children.push(node)}remove(){this.isConnected=false}
 addEventListener(name,fn){this.events[name]=fn}showModal(){this.open=true}close(){this.open=false;this.events.close?.()}
 set innerHTML(value){this.html=value;if(value.includes('rwEventPreviewTitle'))this.parts={'[data-rw-close]':new Node(),'[data-rw-preview-wave]':new Node()}}
 get innerHTML(){return this.html}
}
const root=new Node(),host=new Node(),list=new Node(),waveScroll=new Node();let button;
const focus=new Node();focus.attrs['data-caption']='4';root.all={'.v2-event-list':[list],'.rw-wave-scroll':[waveScroll],'[data-caption]':[focus]};
root.scrollTop=91;list.scrollTop=217;waveScroll.scrollLeft=143;global.scrollX=0;global.scrollY=300;global.scrollTo=(x,y)=>windowPosition=[x,y];
global.document={get activeElement(){return activeFocus},querySelector:()=>null,body:{append(d){dialogs.push(d)}},createElement:()=>new Node()};activeFocus=focus;
focus.selectionStart=3;focus.selectionEnd=8;focus.selectionDirection='backward';focus.scrollTop=42;focus.setSelectionRange=function(a,b,d){this.selectionStart=a;this.selectionEnd=b;this.selectionDirection=d;};
const position=api.capturePosition(root);root.scrollTop=0;list.scrollTop=0;waveScroll.scrollLeft=0;api.restorePosition(position);assert.equal(root.scrollTop,91);assert.equal(list.scrollTop,217);assert.equal(waveScroll.scrollLeft,143);assert.equal(activeFocus,focus);assert.deepEqual(windowPosition,[0,300]);
focus.selectionStart=0;focus.selectionEnd=0;focus.scrollTop=0;api.restorePosition(position);assert.equal(focus.selectionStart,3);assert.equal(focus.selectionEnd,8);assert.equal(focus.selectionDirection,'backward');assert.equal(focus.scrollTop,42);
const replacement=new Node();replacement.attrs['data-caption']='4';focus.isConnected=false;root.all['[data-caption]']=[replacement];api.restorePosition(position);assert.equal(activeFocus,replacement,'focus restores after node redraw');
let current=true,resolves=[],calls=0,renders=0;
const settings=Object.freeze({category:'S',mode:'single',timeRange:Object.freeze([0,3600]),spacing:30,selected:'synthetic-event'}),snapshot=JSON.stringify(settings);
const options={event:{event_id:'synthetic-event',basis_version:'b1',label:'合成候选',time_s:42},loadWave:()=>{calls++;return new Promise(resolve=>resolves.push(resolve))},renderWave:w=>{renders++;assert.equal(Object.keys(w.leads).length,12);return '<svg aria-label="12 导联合成波形"></svg>'},isCurrent:()=>current};
const wave={start_s:39,duration_s:7,beats:[1,2,3,4,5],leads:Object.fromEntries(['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'].map(k=>[k,[]]))};
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{
 let open=api.mountEventPreview(host,options);activeFocus=host;open();await tick();assert.equal(calls,1);const d=dialogs.at(-1);assert.equal(d.open,true);assert.match(d.html,/返回事件列表/);
 resolves.shift()(wave);await tick();assert.equal(renders,1);assert.match(d.parts['[data-rw-preview-wave]'].html,/7.000 秒/);assert.match(d.parts['[data-rw-preview-wave]'].html,/电压未校准/);
 list.scrollTop=0;waveScroll.scrollLeft=0;d.close();assert.equal(d.isConnected,false);assert.equal(list.scrollTop,217);assert.equal(waveScroll.scrollLeft,143);assert.equal(activeFocus,host);assert.equal(JSON.stringify(settings),snapshot);
 open();await tick();const late=dialogs.at(-1);late.close();resolves.shift()(wave);await tick();assert.equal(renders,1,'closed preview ignores late results');
 open();await tick();const stale=dialogs.at(-1);current=false;resolves.shift()(wave);await tick();assert.match(stale.parts['[data-rw-preview-wave]'].textContent,/依据已变化/);activeFocus=replacement;stale.close();assert.equal(activeFocus,replacement,'old case preview cannot steal focus');assert.equal(renders,1);
 current=true;open=api.mountEventPreview(host,{...options,loadWave:()=>Promise.reject(Error('合成读取失败'))});open();await tick();const failed=dialogs.at(-1).parts['[data-rw-preview-wave]'];assert.match(failed.textContent,/合成读取失败/);assert.equal(failed.children[0].textContent,'重试 12 导联');dialogs.at(-1).close();
 assert.equal(JSON.stringify(settings),snapshot);
 console.log('O6/O7: selection-preserving insertion/guarded undo, page availability, scroll/focus restore, 12-lead return, stale/late reads and retry passed');
})().catch(error=>{console.error(error);process.exitCode=1});
