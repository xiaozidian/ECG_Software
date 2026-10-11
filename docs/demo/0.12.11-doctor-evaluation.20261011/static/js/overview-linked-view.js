"use strict";
/* Read-only projections of one exact cohort. Original RR neighbours stay intact. */
((root)=>{
  const E=root.ECGOverviewEngine||(typeof require==='function'?require('./overview-engine.js'):null);
  const sameSamples=(a,b)=>Array.isArray(a)&&Array.isArray(b)&&a.length===b.length&&a.every((s,i)=>s===b[i]);
  const scopeKey=c=>c?JSON.stringify([c.caseId,c.caseToken,c.analysis_basis,c.analysis_revision,c.beatRevision]):'';
  function indexRows(rows){
    const bySample=new Map(rows.map(r=>[r.sample_index,r]));
    const samples=Object.freeze([...bySample.keys()].filter(s=>Number.isInteger(s)&&s>=0).sort((a,b)=>a-b));
    const histograms=new Map(),pairs=new Map();
    function histogram(ratio=false){if(!histograms.has(ratio))histograms.set(ratio,E.histogram(rows,ratio));return histograms.get(ratio);}
    function originalPairs(mode='rr',hour=0){const key=mode+':'+(mode==='hour'?hour:0);if(!pairs.has(key))pairs.set(key,E.pairs(rows,mode,hour));return pairs.get(key);}
    function selected(snapshot){return snapshot?.kind==='samples'?snapshot.samples.filter(s=>bySample.has(s)):samples;}
    function selectedHistogram(snapshot,ratio=false){const original=histogram(ratio),set=new Set(selected(snapshot));return {...original,bins:original.bins.map(b=>{const members=b.samples.filter(s=>set.has(s));return {...b,samples:members,count:members.length};})};}
    return {rows,bySample,samples,histogram,originalPairs,selected,selectedHistogram,
      selectedPairs:(snapshot,mode='rr',hour=0)=>{const set=new Set(selected(snapshot));return originalPairs(mode,hour).filter(r=>set.has(r.sample_index));},
      interval:(start,end)=>samples.filter(s=>s/200>=start&&s/200<end)};
  }
  function create(options){
    const {getState,api,qs,esc,formatTime,formatNumber,drawChanged,drawStrip}=options;
    const central=()=>root.ECGLinkedSelection;
    const plots=new WeakMap(),bitmaps=new WeakMap(),cache=new Map(),pending=new Map(),failed=new Set();
    let context=null,index=null,snapshot=null,unsubscribe=null,densityKey='',data={},message='尚未读取',phase='loading',miniKey='',gateBox=null,refreshRun=0;
    const lanes=new Map();
    const active=()=>context&&index&&scopeKey(snapshot?.scope)===scopeKey(context)&&getState().caseId===context.caseId&&getState().caseRequestId===context.caseToken;
    const presented=()=>active()&&getState().currentPage==='review';
    const cohort=()=>active()?index.selected(snapshot):[];
    const currentSet=()=>new Set(cohort());
    function cancel(){refreshRun++;for(const name of lanes.keys())central()?.cancelLane(name);lanes.clear();pending.clear();}
    function resetVisible(reason='当前依据尚未核对'){
      cancel();densityKey='';data={};phase='loading';message=reason;gateBox=null;
      const state=getState();state.scatterSelectedSamples=[];state.scatterSelectedSet=new Set();state.scatterFocusedSample=null;
      renderMini();draw();
    }
    function assertIdentity(result,c){
      if(result?.analysis_basis!==c.analysis_basis||result?.analysis_revision!==c.analysis_revision||result?.beat_revision!==c.beatRevision)throw Error('联动图表依据已变化，请重新载入病例');
    }
    function receive(next,event={}){
      snapshot=next;
      if(!active()){resetVisible();return;}
      const state=getState();
      if(event.change!=='focus'){
        cancel();
        options.invalidateLegacy?.();
        state.scatterSelectedSamples=next.kind==='samples'?[...cohort()]:[];
        state.scatterSelectedSet=new Set(state.scatterSelectedSamples);
        if(qs('#scatterSelectionList'))qs('#scatterSelectionList').scrollTop=0;
        gateBox=null;failed.clear();
      }
      state.scatterFocusedSample=next.focusSample;
      options.onSnapshot?.(next,event);
      renderMini();drawChanged?.();
      if(event.change!=='focus')refresh();else draw();
    }
    function attach(c,rows){
      if(scopeKey(context)!==scopeKey(c)){cancel();cache.clear();failed.clear();data={};densityKey='';miniKey='';}
      context={...c};index=indexRows(rows);
      if(!unsubscribe&&central())unsubscribe=central().subscribe(receive);
      central()?.setScope(c);
      const next=central()?.snapshot()||null;
      if(!snapshot||scopeKey(snapshot.scope)!==scopeKey(next?.scope)||snapshot.selectionGeneration!==next?.selectionGeneration||snapshot.focusGeneration!==next?.focusGeneration)receive(next,{change:'attach'});
      else {renderMini();drawChanged?.();refresh();}
    }
    function invalidate(reason){context=null;index=null;resetVisible(reason);}
    function select(samples,details={}){
      if(!active())return false;
      const exact=[...new Set(samples)].filter(s=>index.bySample.has(s)).sort((a,b)=>a-b);
      return central().select({samples:exact,timeBounds:details.timeBounds||null,sourcePopulation:details.sourcePopulation||{view:'overview',mode:options.getMode?.()||'rr',fullCount:index.samples.length},origin:details.origin||'overview-selection',focusSample:details.focusSample??null},{expectedScope:context});
    }
    function clear(origin='overview-clear'){if(active())central().clear({expectedScope:context,origin});}
    function focus(sample,origin='overview-card'){if(active()&&index.bySample.has(sample))central().focus(sample,{expectedScope:context,origin});}
    function timeInterval(start,end,origin='overview-time-range'){
      if(!active())return;
      const a=Math.max(0,Math.min(start,end)),b=Math.max(a,Math.max(start,end));
      select(index.interval(a,b),{timeBounds:{start_s:a,end_s:b},origin});
    }
    function bitmap(d){
      if(bitmaps.has(d))return bitmaps.get(d);const canvas=document.createElement('canvas');canvas.width=d.width;canvas.height=d.height;
      const ctx=canvas.getContext('2d'),pixels=ctx.createImageData(d.width,d.height),max=Math.max(1,...d.bins);
      d.bins.forEach((v,i)=>{if(!v)return;const f=Math.log1p(v)/Math.log1p(max),o=i*4;pixels.data[o]=f<.5?Math.round(f*470):255;pixels.data[o+1]=f<.5?220:Math.round(240*(1-(f-.5)*2));pixels.data[o+2]=0;pixels.data[o+3]=255;});
      ctx.putImageData(pixels,0,0);bitmaps.set(d,canvas);return canvas;
    }
    function drawDensity(canvas,d){
      if(!canvas?.getClientRects().length)return;
      const rect=canvas.getBoundingClientRect(),width=rect.width,height=rect.height,dpr=Math.min(devicePixelRatio||1,2);
      canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
      const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);ctx.fillStyle='#020b09';ctx.fillRect(0,0,width,height);ctx.fillStyle='#dcebe5';ctx.font='11px '+(root.UI_FONT||'sans-serif');
      if(!d){ctx.fillText(message,9,height/2);plots.delete(canvas);canvas.setAttribute('aria-description',message);return;}
      const g={l:38,t:5,w:Math.max(1,width-46),h:Math.max(1,height-26),limit:d.amplitude_limit,data:d};
      ctx.imageSmoothingEnabled=false;ctx.drawImage(bitmap(d),g.l,g.t,g.w,g.h);ctx.strokeStyle='#71897e';ctx.setLineDash([2,3]);ctx.beginPath();ctx.moveTo(g.l+g.w/2,g.t);ctx.lineTo(g.l+g.w/2,g.t+g.h);ctx.stroke();ctx.setLineDash([]);
      ctx.fillText('+'+Math.round(g.limit),2,13);ctx.fillText('−'+Math.round(g.limit),2,g.t+g.h);ctx.fillText('−1 s',g.l,height-4);ctx.textAlign='center';ctx.fillText('R · 0',g.l+g.w/2,height-4);ctx.textAlign='right';ctx.fillText('+1 s',g.l+g.w,height-4);ctx.textAlign='left';
      if(!d.included)ctx.fillText(d.total?'完整边界不足':'当前选集为空',g.l+8,height/2);
      if(gateBox?.lead===d.lead){const [a,b]=gateBox.points;ctx.strokeStyle='#fff';ctx.lineWidth=1.3;ctx.strokeRect(g.l+Math.min(a.x,b.x)*g.w,g.t+Math.min(a.y,b.y)*g.h,Math.abs(a.x-b.x)*g.w,Math.abs(a.y-b.y)*g.h);}
      plots.set(canvas,g);canvas.setAttribute('aria-description',`${d.lead}；集合 ${d.total} 搏，参与密度 ${d.included} 搏；边界不足 ${d.skipped_edges} 搏；幅度 ±${g.limit} 设备单位，未校准`);
      canvas.dataset.populationCount=String(d.total);canvas.dataset.includedCount=String(d.included);
    }
    function draw(){
      for(const lead of ['II','V1']){drawDensity(qs('#ovLinkedDensity'+lead),active()?data[lead]:null);const output=qs('[data-ov-density-count="'+lead+'"]');if(output)output.textContent=data[lead]&&active()?`${formatNumber(data[lead].included)} / ${formatNumber(data[lead].total)} 搏`:'';}
      const status=qs('#ovLinkedStatus');if(status){status.textContent=active()?`${snapshot.kind==='none'?'全量':'已选'} ${formatNumber(cohort().length)} 搏 · ${message}`:message;status.dataset.state=phase;status.dataset.generation=String(snapshot?.selectionGeneration??'');}
    }
    async function densityRequest(lead,c,selected,ticket,viewKey,gate=null,limit=null){
      const params=new URLSearchParams({class_code:'all',lead});if(gate)params.set('gate',gate.join(','));
      const body={revision:c.beatRevision,analysis_basis:c.analysis_basis,analysis_revision:c.analysis_revision,...(selected===null?{}:{samples:selected}),...(limit===null?{}:{amplitude_limit:limit})};
      const d=await api('/api/cases/'+encodeURIComponent(c.caseId)+'/waveform-density?'+params,{method:'POST',signal:ticket.signal,body:JSON.stringify(body)});
      if(!active()||!central().isCurrent(ticket,viewKey)||!presented())return null;
      assertIdentity(d,c);const expected=selected===null?index.samples:selected;
      if(!sameSamples(d.population_samples,expected)||d.total!==expected.length||d.lead!==lead)throw Error('密度返回的心搏集合不一致，未显示旧结果');
      return d;
    }
    async function refresh(force=false){
      if(!presented()||!central())return;
      const key=scopeKey(context)+':'+snapshot.selectionGeneration;
      const liveDensity=[...lanes.entries()].filter(([name])=>name.startsWith('overview.density.')).some(([,entry])=>central().isCurrent(entry.ticket,entry.viewKey));
      if(!force&&densityKey===key&&(phase!=='loading'||liveDensity)){draw();return;}
      const run=++refreshRun;
      densityKey=key;data={};phase='loading';message='正在统计两导联完整集合…';draw();
      const c={...context},selected=snapshot.kind==='samples'?[...cohort()]:null;
      if(selected?.length>250000){phase='error';message='选集超过当前密度接口上限；完整心搏仍保留，未截断统计';draw();return;}
      try{
        await Promise.all(['II','V1'].map(async lead=>{
          const viewKey=key+':'+lead,lane='overview.density.'+lead;
          const ticket=central().beginLane(lane,viewKey,{focusSensitive:false});
          lanes.set(lane,{ticket,viewKey});
          const fullKey=scopeKey(c)+':full:'+lead;
          const d=selected===null&&cache.has(fullKey)?cache.get(fullKey):await densityRequest(lead,c,selected,ticket,viewKey);
          if(!d||!active()||!central().isCurrent(ticket,viewKey)||densityKey!==key||run!==refreshRun)return;
          if(selected===null)cache.set(fullKey,d);data[lead]=d;draw();
        }));
        if(active()&&densityKey===key&&run===refreshRun&&Object.keys(data).length===2){phase='ready';message='II / V1 同一集合 · R 对齐 ±1 s · 设备单位未校准';draw();}
      }catch(error){if(active()&&densityKey===key&&run===refreshRun&&error.name!=='AbortError'){refreshRun++;for(const name of lanes.keys())if(name.startsWith('overview.density.'))central().cancelLane(name);data={};phase='error';message=error.message+'；可重新读取';draw();}}
    }
    function gatePoint(event,canvas){const g=plots.get(canvas);if(!g)return null;const r=canvas.getBoundingClientRect();return {x:Math.max(0,Math.min(1,(event.clientX-r.left-g.l)/g.w)),y:Math.max(0,Math.min(1,(event.clientY-r.top-g.t)/g.h))};}
    function previewGate(canvas,a,b){const g=plots.get(canvas);if(!g)return;gateBox={lead:g.data.lead,points:[a,b]};draw();}
    function clearGatePreview(){gateBox=null;draw();}
    async function gate(canvas,a,b){
      const g=plots.get(canvas);if(!active()||!g||!data[g.data.lead])return;
      const c={...context},members=[...cohort()],lead=g.data.lead,viewKey=scopeKey(c)+':'+snapshot.selectionGeneration+':'+lead+':gate',lane='overview.gate';
      const ticket=central().beginLane(lane,viewKey,{focusSensitive:false});
      lanes.set(lane,{ticket,viewKey});
      const bounds=[Math.min(a.x,b.x)*2-1,Math.max(a.x,b.x)*2-1,(1-Math.max(a.y,b.y)*2)*g.limit,(1-Math.min(a.y,b.y)*2)*g.limit];
      message='正在核对密度框内真实心搏…';draw();
      try{const d=await densityRequest(lead,c,members,ticket,viewKey,bounds,g.limit);if(d&&central().isCurrent(ticket,viewKey))select(d.sample_indices,{origin:'overview-density-gate',sourcePopulation:{view:'overview',mode:options.getMode?.()||'rr',lead,gate:bounds,fullCount:index.samples.length}});}
      catch(error){if(active()&&central().isCurrent(ticket,viewKey)&&error.name!=='AbortError'){message=error.message;draw();}}
    }
    function stripViewKey(){return scopeKey(context)+':'+getState().filter;}
    async function loadMini(samples){
      if(!presented()||!samples.length)return;
      const c={...context},viewBase=stripViewKey(),generation=snapshot.selectionGeneration,viewKey=viewBase+':'+generation+':'+samples.join(','),lane='overview.strips.'+samples[0];
      const ticket=central().beginLane(lane,viewKey,{focusSensitive:false});lanes.set(lane,{ticket,viewKey});samples.forEach(s=>pending.set(s,ticket));
      try{
        const result=await api('/api/cases/'+encodeURIComponent(c.caseId)+'/waveform-strips',{method:'POST',signal:ticket.signal,body:JSON.stringify({sample_indices:samples,pre_s:1.5,post_s:2.5,leads:['II','V1','V5'],max_points:800,filter:getState().filter,analysis_basis:c.analysis_basis,analysis_revision:c.analysis_revision,revision:c.beatRevision})});
        if(!presented()||stripViewKey()!==viewBase||!central().isCurrent(ticket,viewKey))return;
        assertIdentity(result,c);if(!sameSamples(result.items?.map(r=>r.sample_index),samples))throw Error('小波形返回的心搏集合不一致');
        for(const item of result.items){cache.set('strip:'+viewBase+':'+item.sample_index,item);failed.delete(item.sample_index);}
        while(cache.size>1024){const oldest=[...cache.keys()].find(k=>k.startsWith('strip:'));if(!oldest)break;cache.delete(oldest);}
      }catch(error){if(presented()&&stripViewKey()===viewBase&&central().isCurrent(ticket,viewKey)&&error.name!=='AbortError'){samples.forEach(s=>failed.add(s));message='小波形读取失败：'+error.message;draw();}}
      finally{for(const s of samples)if(pending.get(s)===ticket)pending.delete(s);if(lanes.get(lane)?.ticket===ticket)lanes.delete(lane);if(presented()&&stripViewKey()===viewBase&&central().isCurrent(ticket,viewKey))renderMini();}
    }
    function renderMini(){
      const viewport=qs('#scatterSelectionList'),empty=qs('#scatterSelectionEmpty'),virtual=qs('#scatterSelectionVirtual');if(!viewport||!empty||!virtual)return;
      const samples=cohort(),state=getState(),explicit=active()&&snapshot.kind==='samples';
      const count=qs('#scatterSelectionCount');if(count)count.textContent=(explicit?'已选 ':'全量 ')+formatNumber(samples.length)+' 搏';
      const clear=qs('#clearScatterSelection');if(clear)clear.disabled=!explicit;
      if(!active()||!samples.length){empty.hidden=false;virtual.hidden=true;virtual.innerHTML='';virtual.style.height='0';empty.innerHTML='<strong>'+(!active()?'当前依据尚未核对':explicit?'当前选集为空':'当前来源没有心搏')+'</strong><p>'+(!active()?'重新载入后显示真实小波形。':'清除选区可恢复全量浏览。')+'</p>';return;}
      const key=stripViewKey();if(miniKey!==key){miniKey=key;for(const [name] of lanes)if(name.startsWith('overview.strips.')){central().cancelLane(name);lanes.delete(name);}pending.clear();failed.clear();}
      for(const [sample,ticket] of pending)if(!central().isCurrent(ticket))pending.delete(sample);
      empty.hidden=true;virtual.hidden=false;const height=options.getMiniHeight?.()||154;virtual.style.height=samples.length*height+'px';
      const start=Math.max(0,Math.floor(viewport.scrollTop/height)-2),end=Math.min(samples.length,start+Math.ceil(viewport.clientHeight/height)+5),visible=samples.slice(start,end);
      const focused=document.activeElement?.closest?.('[data-scatter-sample]')?.dataset.scatterSample;
      virtual.innerHTML=visible.map((sample,offset)=>{const strip=cache.get('strip:'+key+':'+sample),row=index.bySample.get(sample),activeCard=sample===state.scatterFocusedSample,label=row.class_code||'',failure=failed.has(sample);return `<button type="button" class="scatter-strip-card${activeCard?' active':''}" style="top:${(start+offset)*height+4}px" data-scatter-sample="${sample}" data-jump-time="${sample/200}"${activeCard?' aria-current="true"':''} aria-label="${formatTime(sample/200)}，${esc(label)}，RR ${row.rr_ms||'—'} ms，${explicit?'选集':'全量'}第 ${start+offset+1} 搏"><div class="scatter-strip-meta"><span class="scatter-beat-badge ${esc(label)}">${esc(label)}</span><strong>${formatTime(sample/200)}</strong><small title="RR ${row.rr_ms||'—'} ms · ${start+offset+1}/${samples.length}">RR ${row.rr_ms||'—'} ms</small></div>${strip?`<canvas data-strip-canvas="${sample}" aria-hidden="true"></canvas>`:`<div class="scatter-strip-placeholder">${failure?'读取失败，点击重试':'正在读取真实三导联…'}</div>`}</button>`;}).join('');
      if(focused)virtual.querySelector('[data-scatter-sample="'+focused+'"]')?.focus({preventScroll:true});
      for(const canvas of virtual.querySelectorAll('canvas[data-strip-canvas]'))drawStrip(canvas,cache.get('strip:'+key+':'+canvas.dataset.stripCanvas));
      const rect=viewport.getBoundingClientRect?.(),layoutVisible=viewport.clientHeight>0&&(!viewport.getClientRects||viewport.getClientRects().length>0),onScreen=layoutVisible&&(!rect||rect.bottom>0&&rect.top<(root.innerHeight||Infinity)&&rect.right>0&&rect.left<(root.innerWidth||Infinity));
      if(presented()&&onScreen){const missing=visible.filter(s=>!cache.has('strip:'+key+':'+s)&&!pending.has(s)&&!failed.has(s));if(missing.length&&new Set(pending.values()).size<2)loadMini(missing.slice(0,16));}
    }
    function retryMini(sample){failed.delete(sample);renderMini();}
    function inspect(){return {scope:context?{...context}:null,kind:snapshot?.kind||null,generation:snapshot?.selectionGeneration??null,focusGeneration:snapshot?.focusGeneration??null,samples:[...cohort()],density:Object.fromEntries(Object.entries(data).map(([lead,d])=>[lead,{lead,total:d.total,included:d.included,skipped_edges:d.skipped_edges,amplitude_limit:d.amplitude_limit,population_samples:[...d.population_samples],bins:[...d.bins]}])),phase};}
    return {attach,invalidate,select,focus,clear,timeInterval,refresh,draw,renderMini,retryMini,gatePoint,previewGate,clearGatePreview,gate,
      index:()=>index,snapshot:()=>snapshot,active,cohort,currentSet,inspect,
      dispose:()=>{cancel();unsubscribe?.();}};
  }
  const api={indexRows,sameSamples,scopeKey,create};root.ECGOverviewLinkedView=api;if(typeof module!=='undefined')module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
