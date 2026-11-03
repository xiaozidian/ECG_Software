"use strict";
/* Report actions own report evidence; viewing a trace never edits its beats. */
const ECGReportWaveMenu=(()=>{
  let menu=null,context=null,tool=null;
  const ns='http://www.w3.org/2000/svg',ranges=new WeakMap();
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const actions=[['插入图条(S)','insert'],['插入缩略图条(Y)','short'],['即时打印图条','print'],['选择起始位置(T)','anchor'],['测量尺(R)','measure'],['分规尺(F)','divider'],['平行尺(P)','parallel'],['跳转到时间','jump'],['转到诊断图(D)','diagnostic'],['转到全览图(E)','overview'],['设为最快心率(K)','fastest'],['设为最慢心率(L)','slowest'],['设为最快窦性心率','fastest_nn'],['设为最慢窦性心率','slowest_nn'],['重分析房早(A)','pac'],['检查选项','settings']];
  const keys={s:'insert',y:'short',t:'anchor',r:'measure',f:'divider',p:'parallel',d:'diagnostic',e:'overview',k:'fastest',l:'slowest',a:'pac'};
  function fail(error){if(typeof handleError==='function')handleError(error);else if(typeof toast==='function')toast(error.message,'error');}
  function current(c){
    if(!c||!c.host.isConnected||c.isCurrent?.()===false||typeof state==='undefined')return false;
    return state.caseId===c.case_id&&state.caseRequestId===c.case_token&&state.currentPage==='report';
  }
  function assertCurrent(c){
    if(!current(c))throw Error('病例或波形已变化，请重新右击当前图条');
    if(c.wave.case_id!==undefined&&c.wave.case_id!==c.case_id)throw Error('图条来自其他病例，未执行操作');
    if(c.wave.analysis_basis!==undefined&&state.caseData?.clinical_identity)ECGAnalysisConsistency.assertSame(c.wave,state.caseData.clinical_identity);
  }
  function close(){if(menu){menu.hidden=true;try{menu.hidePopover?.();}catch(_){}}context=null;}
  function box(c){
    const svg=c.host.matches?.('svg[data-plot-left]')?c.host:c.host.querySelector('svg[data-plot-left]');
    if(!svg)throw Error('此图尚未提供可核对的时间坐标，请重新读取');
    const rect=svg.getBoundingClientRect(),view=svg.viewBox.baseVal;
    if(!rect.width||!rect.height||!view.width||!view.height)throw Error('图条尚未显示');
    return {svg,rect,width:view.width,height:view.height,sx:rect.width/view.width,sy:rect.height/view.height,
      left:Number(svg.dataset.plotLeft),plotWidth:Number(svg.dataset.plotWidth),start:Number(svg.dataset.displayStart),duration:Number(svg.dataset.displayDuration)};
  }
  function position(c,x,y){
    const g=box(c),localX=(x-g.rect.left)/g.sx,localY=(y-g.rect.top)/g.sy;
    const fs=Number(c.wave.sample_rate_hz)||200,time=Math.round((g.start+Math.max(0,Math.min(1,(localX-g.left)/g.plotWidth))*g.duration)*fs)/fs;
    const lead=[...g.svg.querySelectorAll('[data-wave-lead]')].find(n=>localY>=Number(n.dataset.signalTop)&&localY<=Number(n.dataset.signalBottom));
    return {time,lead:lead?.dataset.waveLead||null,value:lead?(Number(lead.dataset.waveBaseline)-localY)/Number(lead.dataset.waveScale):null};
  }
  const stamp=time=>typeof formatElapsedPrecise==='function'?formatElapsedPrecise(time):time.toFixed(3)+' s';
  function selection(c){const r=ranges.get(c.host);return r&&r.case_id===c.case_id&&r.case_token===c.case_token&&r.basis===c.wave.analysis_basis?r:null;}
  function stopTool(){if(!tool)return;tool.observer?.disconnect();tool.resize?.disconnect();tool.layer?.remove();tool.status?.remove();tool=null;}
  function line(layer,x1,y1,x2,y2){const node=document.createElementNS(ns,'line');for(const [k,v]of Object.entries({x1,y1,x2,y2}))node.setAttribute(k,String(v));layer.append(node);}
  function paintTool(){
    const t=tool;if(!t)return;if(!current(t.context)){stopTool();return;}
    const c=t.context,g=box(c),hostBox=c.host.getBoundingClientRect();
    Object.assign(t.layer.style,{left:g.rect.left-hostBox.left+'px',top:g.rect.top-hostBox.top+'px',width:g.rect.width+'px',height:g.rect.height+'px'});
    t.layer.setAttribute('viewBox',`0 0 ${g.width} ${g.height}`);t.layer.replaceChildren();
    const xAt=time=>g.left+(time-g.start)/g.duration*g.plotWidth;
    if(t.mode==='anchor'){
      const a=t.points[0].time,b=t.points[1]?.time;
      if(b!==undefined){const rect=document.createElementNS(ns,'rect');rect.setAttribute('x',String(xAt(Math.min(a,b))));rect.setAttribute('y','0');rect.setAttribute('width',String(Math.abs(xAt(b)-xAt(a))));rect.setAttribute('height',String(g.height));t.layer.append(rect);}
      for(const p of t.points)line(t.layer,xAt(p.time),0,xAt(p.time),g.height);
      t.output.textContent=b===undefined?`起点 ${stamp(a)} · 点击终点`:`已选 ${stamp(Math.min(a,b))} — ${stamp(Math.max(a,b))} · ${Math.abs(b-a).toFixed(3)} 秒`;
      return;
    }
    const points=t.points,delta=points.length>1?Math.abs(points[1].time-points[0].time):0;
    if(t.mode==='parallel'){
      for(const p of points){const lead=[...g.svg.querySelectorAll('[data-wave-lead]')].find(n=>n.dataset.waveLead===p.lead);if(lead){const y=Number(lead.dataset.waveBaseline)-p.value*Number(lead.dataset.waveScale);line(t.layer,g.left,y,g.left+g.plotWidth,y);}}
    }else if(t.mode==='divider'&&delta>0){
      const first=points[0].time-Math.ceil((points[0].time-g.start)/delta)*delta;
      for(let i=0;i<200;i++){const time=first+i*delta;if(time>g.start+g.duration)break;if(time>=g.start)line(t.layer,xAt(time),0,xAt(time),g.height);}
    }else for(const p of points)line(t.layer,xAt(p.time),0,xAt(p.time),g.height);
    const title={measure:'测量尺',divider:'分规尺',parallel:'平行尺'}[t.mode];
    if(points.length<2){t.output.textContent=title+' · 点击'+(points.length?'第二个':'第一个')+'位置';return;}
    const same=points[0].lead&&points[0].lead===points[1].lead;
    const amplitude=same?Math.abs(points[0].value-points[1].value):null;
    const units=amplitude===null?'':globalThis.ECGVoltage?ECGVoltage.amplitude(amplitude,c.wave):amplitude.toFixed(2)+' u';
    t.output.textContent=t.mode==='parallel'?`${points[0].lead} · Δ幅度 ${units}`:`Δt ${(delta*1000).toFixed(0)} ms${delta>0?' · '+(60/delta).toFixed(1)+' bpm':''}${same?' · Δ幅度 '+units:''}`;
  }
  function startTool(c,mode){
    assertCurrent(c);stopTool();
    const layer=document.createElementNS(ns,'svg'),status=document.createElement('div'),output=document.createElement('output'),dismiss=document.createElement('button');
    layer.classList.add('report-wave-ruler-layer');layer.setAttribute('aria-hidden','true');status.className='report-wave-tool-status';status.setAttribute('role','status');dismiss.type='button';dismiss.textContent='×';dismiss.setAttribute('aria-label','关闭图条测量');dismiss.onclick=()=>{ranges.delete(c.host);stopTool();};status.append(output,dismiss);c.host.classList.add('report-wave-tool-host');c.host.append(layer,status);
    tool={context:c,mode,layer,status,output,points:mode==='anchor'?[{time:c.time}]:[],done:false};ranges.delete(c.host);
    if(typeof ResizeObserver!=='undefined'){tool.resize=new ResizeObserver(()=>{if(tool?.context===c)paintTool();});tool.resize.observe(c.host);}
    if(typeof MutationObserver!=='undefined'){tool.observer=new MutationObserver(changes=>{if(tool?.context===c&&changes.some(r=>[...r.addedNodes].some(n=>n.nodeType===1&&n.matches?.('svg[data-plot-left]'))))paintTool();});tool.observer.observe(c.host,{childList:true,subtree:true});}
    if(!c.host._reportWaveToolsBound){
      c.host._reportWaveToolsBound=true;
      const capture=event=>{if(tool?.context.host!==c.host||tool.done||!current(tool.context)||event.target.closest('button,input,select,textarea'))return;event.preventDefault();event.stopImmediatePropagation();};
      c.host.addEventListener('pointerdown',capture,true);
      c.host.addEventListener('click',event=>{
        const t=tool;if(t?.context.host!==c.host||t.done||!current(t.context)||event.target.closest('button,input,select,textarea'))return;
        capture(event);const point=position(t.context,event.clientX,event.clientY);
        if(t.mode!=='anchor'&&!point.lead)return;
        if(t.points.length===2)t.points=[];
        if(t.mode==='parallel'&&t.points.length&&t.points[0].lead!==point.lead){if(typeof toast==='function')toast('请在同一导联放置两条平行线','info');return;}
        t.points.push(point);
        if(t.mode==='anchor'&&t.points.length===2){t.done=true;const [a,b]=t.points.map(p=>p.time).sort((a,b)=>a-b);ranges.set(c.host,{case_id:t.context.case_id,case_token:t.context.case_token,basis:t.context.wave.analysis_basis,a,b});}
        paintTool();
      },true);
    }
    c.host.focus({preventScroll:true});paintTool();
  }
  async function navigate(c,kind){
    assertCurrent(c);await goPage('review');if(state.caseId!==c.case_id||state.caseRequestId!==c.case_token||state.currentPage!=='review')return;
    if(kind==='overview'||kind==='diagnostic'){
      const af=document.querySelector('#ovAF');if(af&&!af.hidden&&getComputedStyle(af).display!=='none')document.querySelector('[data-ov="af-close"]')?.click();
      jumpTo(c.time);return;
    }
    return overviewWorkbench.waveAction(kind==='pac'?'pac-screen':'bookmark-'+kind,{time:c.time,bounds:[c.wave.start_s,c.wave.start_s+c.wave.duration_s],caseId:c.case_id,caseToken:c.case_token});
  }
  async function dispatch(c,action){
    close();assertCurrent(c);const chosen=selection(c),range=chosen?{start_s:chosen.a,end_s:chosen.b}:{};
    const args={wave:c.wave,time:c.time,case_id:c.case_id,case_token:c.case_token,...range};
    if(action==='insert'||action==='short'){await clinicalUI.insertWaveStrip({...args,short:action==='short',caption:action==='short'?'人工缩略图条':'人工图条'});ranges.delete(c.host);stopTool();return;}
    if(action.startsWith('print:'))return clinicalUI.printWaveStrip({...args,leads:action==='print:3'?['II','V1','V5']:['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6']});
    if(['anchor','measure','divider','parallel'].includes(action))return startTool(c,action);
    if(action==='settings')return beatEditor.openSettings();
    if(action==='jump'){
      const node=document.createElement('dialog');node.className='report-wave-jump';node.setAttribute('aria-label','跳转到时间');node.innerHTML='<form><label>记录开始后秒数<input name="time" type="number" min="0" step="0.005" required></label><footer><button type="button" data-close>取消</button><button type="submit">定位</button></footer><p role="status"></p></form>';
      node.querySelector('input').max=String(state.caseData.technical.duration_seconds_raw);node.querySelector('input').value=c.time.toFixed(3);node.querySelector('[data-close]').onclick=()=>node.close();node.onclose=()=>node.remove();node.querySelector('form').onsubmit=async event=>{event.preventDefault();try{assertCurrent(c);const time=Number(new FormData(event.target).get('time'));if(!Number.isFinite(time)||time<0||time>Number(state.caseData.technical.duration_seconds_raw))throw Error('时间超出当前记录');node.close();await navigate({...c,time},'diagnostic');}catch(error){if(node.isConnected)node.querySelector('[role=status]').textContent=error.message;else fail(error);}};document.body.append(node);node.showModal();return;
    }
    return navigate(c,action);
  }
  function ensureMenu(){
    if(menu)return menu;menu=document.createElement('div');menu.id='reportWaveMenu';menu.className='report-wave-menu';menu.setAttribute('role','menu');menu.setAttribute('aria-label','报告波形操作');menu.setAttribute('popover','manual');menu.hidden=true;
    menu.innerHTML=actions.map(([label,action],i)=>action==='print'?'<details><summary role="menuitem">即时打印图条<span aria-hidden="true">›</span></summary><div role="menu"><button type="button" role="menuitem" data-report-wave-action="print:12">十二导联图条</button><button type="button" role="menuitem" data-report-wave-action="print:3">三导联图条</button></div></details>':`<button type="button" role="menuitem" data-report-wave-action="${action}"${[3,7,10,14,15].includes(i)?' class="report-wave-menu-group"':''}>${esc(label)}</button>`).join('');
    const print=menu.querySelector('details'),summary=print.querySelector('summary'),sub=print.querySelector('[role=menu]');summary.setAttribute('aria-haspopup','menu');
    print.ontoggle=()=>{summary.setAttribute('aria-expanded',String(print.open));if(!print.open)return;const row=summary.getBoundingClientRect(),root=menu.getBoundingClientRect(),size=sub.getBoundingClientRect();sub.style.left=Math.max(6,root.right+size.width+6<=innerWidth?root.right-1:root.left-size.width+1)+'px';sub.style.top=Math.max(6,Math.min(row.top,innerHeight-size.height-6))+'px';};
    summary.onpointerenter=()=>{print.open=true;};menu.querySelectorAll(':scope>button').forEach(button=>button.onpointerenter=()=>{print.open=false;});
    menu.onclick=event=>{const button=event.target.closest('[data-report-wave-action]');if(button&&context){const c=context;Promise.resolve(dispatch(c,button.dataset.reportWaveAction)).catch(fail);}};document.body.append(menu);return menu;
  }
  function open({event,host,wave,isCurrent=()=>true,keyboard=false}={}){
    if(!host||!wave||isCurrent()===false)return;
    close();if(tool&&!current(tool.context))stopTool();
    const legacy=document.querySelector('#beatRelabelMenu');if(legacy){legacy.hidden=true;try{legacy.hidePopover?.();}catch(_){}}
    const c={host,wave,isCurrent,case_id:state.caseId,case_token:state.caseRequestId};assertCurrent(c);
    const rect=host.getBoundingClientRect(),x=keyboard?rect.left+rect.width/2:event.clientX,y=keyboard?rect.top+40:event.clientY;c.time=position(c,x,y).time;
    const node=ensureMenu();node.querySelectorAll('details').forEach(d=>d.open=false);context=c;node.hidden=false;try{node.showPopover?.();}catch(_){}
    const size=node.getBoundingClientRect();node.style.left=Math.max(6,Math.min(x,innerWidth-size.width-6))+'px';node.style.top=Math.max(6,Math.min(y,innerHeight-size.height-6))+'px';node.querySelector('button')?.focus({preventScroll:true});
  }
  if(typeof document!=='undefined'){
    document.addEventListener('pointerdown',event=>{if(menu&&!menu.hidden&&!menu.contains(event.target))close();},true);
    document.addEventListener('keydown',event=>{
      if(menu&&!menu.hidden){
        if(event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();const host=context?.host;close();host?.focus({preventScroll:true});return;}
        if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){const nodes=[...menu.querySelectorAll('button,summary')].filter(n=>n.getClientRects().length);const i=nodes.indexOf(document.activeElement),next=event.key==='Home'?0:event.key==='End'?nodes.length-1:(i+(event.key==='ArrowUp'?-1:1)+nodes.length)%nodes.length;nodes[next]?.focus();event.preventDefault();event.stopImmediatePropagation();return;}
        if(event.key==='ArrowRight'&&document.activeElement===menu.querySelector('summary')){menu.querySelector('details').open=true;menu.querySelector('details button')?.focus();event.preventDefault();event.stopImmediatePropagation();return;}
        if(event.key==='ArrowLeft'&&menu.querySelector('details').contains(document.activeElement)){menu.querySelector('details').open=false;menu.querySelector('summary').focus();event.preventDefault();event.stopImmediatePropagation();return;}
        if(!event.ctrlKey&&!event.metaKey&&!event.altKey&&keys[event.key.toLowerCase()]&&context){event.preventDefault();event.stopImmediatePropagation();const c=context;Promise.resolve(dispatch(c,keys[event.key.toLowerCase()])).catch(fail);return;}
      }
      if(event.key==='Escape'&&tool&&current(tool.context)&&tool.context.host.contains(document.activeElement)){event.preventDefault();event.stopImmediatePropagation();ranges.delete(tool.context.host);stopTool();}
    },true);
    globalThis.addEventListener?.('resize',()=>{close();if(tool)paintTool();});
  }
  const api={open,close,stopTool,position,actions};if(typeof module!=='undefined')module.exports=api;return api;
})();
globalThis.ECGReportWaveMenu=ECGReportWaveMenu;
