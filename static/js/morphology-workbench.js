"use strict";
/* Two views of one remainder, four disjoint review groups. No raw-beat writes. */
const morphologyWorkbench=(()=>{
  const G=ECGMorphologyGroups,qs=s=>document.querySelector(s),esc=escapeHtml;
  const sessions=new Map(),plots=new Map(),bitmaps=new WeakMap(),leads=['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'];
  const sourceIds={top:'editDensityPrimary',bottom:'editDensitySelection'};
  let current=null,requestToken=0,selectionToken=0,busy=false,selecting=false,saving=false,drag=null,selection=null,box=null,activeSlot=6,formSlot=null;
  const view={top:'II',bottom:'V1',groups:'II'};
  let drawFrame=0;
  function scheduleDraw(){if(!drawFrame)drawFrame=requestAnimationFrame(()=>{drawFrame=0;drawAll()})}
  function context(){
    const source=state.editSelectedClass||'source-N',filter=qs('#occTemplate')?.value;
    const template=source.startsWith('custom-')?source.slice(7):filter&&filter!=='all'?filter:null;
    const params=template?{template_id:template}:{class_code:source.startsWith('source-')?source.slice(7):'N'};
    return {id:state.caseId,revision:state.caseData?.analysis_revision??0,source:template?'custom-'+template:source,params};
  }
  const key=c=>[c.id,c.revision,c.source].join('|');
  const isCurrent=s=>current===s&&key(context())===s.key;
  const status=(message,error=false)=>{const el=qs('#morphStatus');if(el){el.textContent=message;el.dataset.error=String(error)}};
  function clearSelection(){selectionToken++;if(selecting){selecting=false;busy=false}selection=null;box=null;drag=null;controls();drawAll();}
  function sourceCanvas(slot){return qs('#'+sourceIds[slot]);}
  function closeForm(){formSlot=null;qs('#morphTemplateForm').hidden=true;}
  async function request(s,lead,payload={},gate=null){
    const params=new URLSearchParams({...s.params,lead});if(gate)params.set('gate',gate.join(','));
    const d=await api('/api/cases/'+encodeURIComponent(s.id)+'/waveform-density?'+params,{method:'POST',body:JSON.stringify({revision:s.revision,...payload})});
    if(d.revision!==s.revision)throw Error('心搏修订版本已变化，请刷新病例后重新框选');
    return d;
  }
  function controls(){
    if(!qs('#morphGroups'))return;
    const ready=!!current?.groups&&!busy&&!saving,count=selection?.samples.length||0,remaining=current?.groups?current.groups.source.length-Object.values(current.groups.slots).reduce((sum,values)=>sum+values.length,0):undefined;
    qs('#editMorphologyCount').textContent=remaining===undefined?'正在统计…':'剩余 '+fmtNumber(remaining)+' / '+fmtNumber(current.groups.source.length)+' 搏';
    qs('#editMorphSelectionLabel').textContent=selection?view[selection.slot]+' 已框选 '+fmtNumber(count)+' 搏':'尚未框选';
    qs('#clearEditSelection').disabled=!selection&&!box||saving;
    qs('#morphUndo').disabled=!ready||!current.groups.history.length;
    qs('#morphRetry').disabled=busy||saving;
    qs('#applyEditRange').disabled=!ready;
    for(const id of ['morphLeadTop','morphLeadBottom','morphLeadGroups'])qs('#'+id).disabled=busy||saving;
    G.slots.forEach(n=>{
      const values=current?.groups?.slots[n]||[],saved=current?.saved[n];
      const card=qs('[data-morph-group="'+n+'"]');card.dataset.active=String(n===activeSlot);
      card.querySelector('[data-group-count]').textContent=fmtNumber(values.length)+' 搏';
      card.querySelector('[data-group-select]').setAttribute('aria-pressed',String(n===activeSlot));
      const move=card.querySelector('[data-group-move]');move.disabled=!ready||!count||!!saved;
      move.title=saved?'已保存的组不能追加；可归还左侧后重新建组':'将左侧当前框选移入 '+n+' 组';
      card.querySelector('[data-group-select]').title=n+' 组 · '+(saved?saved.name:'未保存模板');
    });
    const saved=current?.saved[activeSlot],populated=!!current?.groups?.slots[activeSlot]?.length;
    qs('#morphActiveGroup').textContent=activeSlot+' 组 · '+(saved?saved.name:'未保存模板');
    qs('#morphGroupTemplate').textContent=saved?'编辑模板':'设为模板';
    qs('#morphGroupTemplate').disabled=qs('#morphGroupRestore').disabled=!ready||!populated;
    qs('#morphTemplateForm').querySelectorAll('input,select,button').forEach(el=>el.disabled=saving);
  }
  function bitmap(d){
    if(bitmaps.has(d))return bitmaps.get(d);
    const canvas=document.createElement('canvas');canvas.width=d.width;canvas.height=d.height;
    const ctx=canvas.getContext('2d'),pixels=ctx.createImageData(d.width,d.height),max=Math.max(1,...d.bins);
    d.bins.forEach((v,i)=>{if(!v)return;const f=Math.log1p(v)/Math.log1p(max),o=i*4;pixels.data[o]=f<.5?Math.round(f*470):255;pixels.data[o+1]=f<.5?220:Math.round(240*(1-(f-.5)*2));pixels.data[o+2]=0;pixels.data[o+3]=255});
    ctx.putImageData(pixels,0,0);bitmaps.set(d,canvas);return canvas;
  }
  function draw(canvas,data,message='正在读取…'){
    if(!canvas?.getClientRects().length)return;
    const rect=canvas.getBoundingClientRect(),width=rect.width,height=rect.height,dpr=Math.min(devicePixelRatio||1,2);
    const pixelWidth=Math.round(width*dpr),pixelHeight=Math.round(height*dpr);
    if(canvas.width!==pixelWidth)canvas.width=pixelWidth;if(canvas.height!==pixelHeight)canvas.height=pixelHeight;
    const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);ctx.fillStyle='#020b09';ctx.fillRect(0,0,width,height);
    ctx.fillStyle='#cbdcd5';ctx.font='11px '+UI_FONT;
    if(!data){ctx.fillText(message,10,height/2);plots.delete(canvas);return}
    const compact=!canvas.dataset.morphSource,pad=compact?3:8,foot=compact?12:24;
    const g={l:pad,t:pad,w:Math.max(1,width-pad*2),h:Math.max(1,height-pad-foot),limit:data.amplitude_limit,data};
    ctx.imageSmoothingEnabled=false;ctx.drawImage(bitmap(data),g.l,g.t,g.w,g.h);
    ctx.strokeStyle='#758d82';ctx.setLineDash([2,3]);ctx.beginPath();ctx.moveTo(g.l+g.w/2,g.t);ctx.lineTo(g.l+g.w/2,g.t+g.h);ctx.stroke();ctx.setLineDash([]);
    if(compact)ctx.font='9px '+UI_FONT;
    ctx.fillText('−1s',g.l,height-3);if(!compact){ctx.textAlign='center';ctx.fillText('R · 0',width/2,height-3)}ctx.textAlign='right';ctx.fillText('+1s',width-pad,height-3);ctx.textAlign='left';
    if(!data.included)ctx.fillText(data.total?'边界不足，无法叠加':'没有心搏',10,height/2);
    if(box&&canvas.dataset.morphSource===box.slot){const [a,b]=box.points;ctx.strokeStyle='#fff';ctx.lineWidth=1.5;ctx.strokeRect(g.l+Math.min(a.x,b.x)*g.w,g.t+Math.min(a.y,b.y)*g.h,Math.abs(a.x-b.x)*g.w,Math.abs(a.y-b.y)*g.h);}
    plots.set(canvas,g);
    canvas.setAttribute('aria-description',data.lead+'；'+data.included+' 搏参与密度统计；边界不足 '+data.skipped_edges+' 搏；幅度范围 ±'+Math.round(data.amplitude_limit)+' 设备单位');
  }
  function drawAll(){
    const s=current;
    for(const slot of ['top','bottom']){
      const d=s?.data[slot];draw(sourceCanvas(slot),d,busy?'正在统计…':'请重新读取');
      qs('[data-morph-count="'+slot+'"]').textContent=d?fmtNumber(d.included)+' 搏':'';
      qs(slot==='top'?'#editDensityPrimaryLabel':'#morphSecondaryLabel').textContent=view[slot]+' · 剩余心搏';
    }
    for(const n of G.slots)draw(qs('#morphSlot'+n),s?.data[n],s?.groups?.slots[n]?.length?'正在统计…':'框选后按 '+n);
  }
  async function refresh(force=false){
    if(!state.caseId||state.currentPage!=='edit'||!qs('#morphGroups'))return;
    const c=context(),k=key(c);
    if(current?.key===k&&!force){drawAll();controls();return;}
    if(current?.key!==k){clearSelection();closeForm();current=sessions.get(k)||{...c,key:k,groups:null,limits:{},base:{},data:{},saved:{}};sessions.set(k,current);}
    while(sessions.size>6)sessions.delete(sessions.keys().next().value);
    const s=current,token=++requestToken;selectionToken++;selecting=false;busy=true;s.data={};controls();drawAll();status('正在统计完整心搏集合…');
    try{
      // Unique leads run together. Reuse in-flight work during a refresh and show
      // each source as soon as it arrives rather than waiting for every group.
      s.pending ||= new Map();
      const needed=new Set([view.top,view.bottom]);if(Object.values(s.groups?.slots||{}).some(v=>v.length))needed.add(view.groups);
      await Promise.all([...needed].map(async lead=>{
        if(!s.base[lead]){
          if(!s.pending.has(lead))s.pending.set(lead,request(s,lead).finally(()=>s.pending.delete(lead)));
          const d=await s.pending.get(lead);if(token!==requestToken||!isCurrent(s))return;
          if(!s.groups)s.groups=new G.Groups(d.population_samples);
          s.limits[lead]=d.amplitude_limit;s.base[lead]=d;
        }
        if(token===requestToken&&isCurrent(s)&&!Object.values(s.groups.slots).some(v=>v.length)){
          for(const slot of ['top','bottom'])if(view[slot]===lead)s.data[slot]=s.base[lead];
          controls();scheduleDraw();
        }
      }));
      if(token!==requestToken||!isCurrent(s))return;
      const excluded=Object.values(s.groups.slots).flat(),payload={exclude_samples:excluded};
      const jobs=['top','bottom'].map(async slot=>[slot,excluded.length?await request(s,view[slot],{...payload,amplitude_limit:s.limits[view[slot]]}):s.base[view[slot]]]);
      for(const n of G.slots)if(s.groups.slots[n].length)jobs.push(request(s,view.groups,{samples:s.groups.slots[n],amplitude_limit:s.limits[view.groups]}).then(d=>[n,d]));
      const data=await Promise.all(jobs);if(token!==requestToken||!isCurrent(s))return;
      s.data=Object.fromEntries(data);
      const skipped=s.data.top?.skipped_edges||0;status('左侧 '+fmtNumber(s.groups.remaining().length)+' 搏；已剥离 '+fmtNumber(excluded.length)+' 搏。'+(skipped?'其中 '+skipped+' 搏边界不足，未绘入密度。':'可在任一左图框选。'));
      qs('#morphMethod').textContent='R 峰对齐 ±1s；绿→黄→红为对数密度。去固定基线，不逐搏归一化；幅度为设备单位，未作临床校准。两左图同一集合。剥离不删除心搏；分组仅暂存在本页面，保存模板才会保留。';
    }catch(error){if(token===requestToken&&isCurrent(s)){status('密度读取失败：'+error.message+'。可点“重新读取”；若版本变化请刷新病例。',true);s.data={}}}
    finally{if(token===requestToken&&isCurrent(s)){busy=false;controls();drawAll();}}
  }
  async function choose(slot,a,b){
    const s=current,g=plots.get(sourceCanvas(slot));if(!s?.groups||!g||busy||saving)return;
    const token=++selectionToken;selection=null;box={slot,points:[a,b]};busy=true;selecting=true;controls();drawAll();status('正在按 '+view[slot]+' 在剩余集合中精确匹配…');
    const gate=[Math.min(a.x,b.x)*2-1,Math.max(a.x,b.x)*2-1,(1-2*Math.max(a.y,b.y))*g.limit,(1-2*Math.min(a.y,b.y))*g.limit];
    try{
      const d=await request(s,view[slot],{exclude_samples:Object.values(s.groups.slots).flat(),amplitude_limit:g.limit},gate);
      if(token!==selectionToken||!isCurrent(s))return;
      selection={slot,samples:d.sample_indices};
      status(d.sample_indices.length?'已匹配 '+fmtNumber(d.sample_indices.length)+' 搏。按 6 / 7 / 8 / 9，或点击右侧“移入”。':'此区域没有匹配心搏，请换一个区域。');
    }catch(error){if(token===selectionToken&&isCurrent(s))status('框选失败：'+error.message,true)}
    finally{if(token===selectionToken&&isCurrent(s)){busy=false;selecting=false;controls();drawAll();}}
  }
  async function move(n){
    if(busy||saving||!selection?.samples.length)return;
    if(current.saved[n]){status('该组已有模板；请先归还左侧或选择其他空组。',true);return;}
    current.groups.move(n,selection.samples);activeSlot=n;clearSelection();closeForm();await refresh(true);
  }
  async function restore(n){
    if(busy||saving||!current?.groups?.restore(n))return;
    delete current.saved[n];clearSelection();closeForm();await refresh(true);
    status(n+' 组已归还左侧。已经保存的模板仍保留在模板库。');
  }
  async function undo(){
    if(busy||saving||!current?.groups?.undo())return;
    for(const n of G.slots){const saved=current.saved[n];if(saved&&saved.samples.join(',')!==current.groups.slots[n].join(','))delete current.saved[n];}
    clearSelection();closeForm();await refresh(true);status('已撤销上一次剥离 / 归还；已保存的模板不会被删除。');
  }
  function templateForm(n){
    if(busy||saving||!current?.groups?.slots[n].length)return;activeSlot=n;formSlot=n;
    const saved=current.saved[n];qs('#morphTemplateTitle').textContent=n+' 组 · '+fmtNumber(current.groups.slots[n].length)+' 搏 · '+(saved?'编辑模板':'设置模板');
    qs('#morphTemplateName').value=saved?.name||'';qs('#morphTemplateFamily').value=saved?.family||'自定义';
    qs('#morphTemplateForm').hidden=false;controls();qs('#morphTemplateName').focus();
  }
  async function saveTemplate(event){
    event.preventDefault();const s=current,n=formSlot;if(!s||n===null||saving||busy)return;
    const name=qs('#morphTemplateName').value.trim(),family=qs('#morphTemplateFamily').value,samples=[...s.groups.slots[n]],lead=view.groups;
    if(!name||!samples.length){status('请填写模板名称，并先剥离心搏到该组。',true);return;}
    const existing=s.saved[n];saving=true;controls();
    try{
      const data=await api(existing?'/api/beat-templates/'+existing.id:'/api/cases/'+encodeURIComponent(s.id)+'/beat-templates',{method:existing?'PATCH':'POST',body:JSON.stringify({name,rhythm_family:family,lead,source_class:s.source,sample_indices:samples,revision:s.revision,note:'密度图 '+n+' 组；'+lead+' 导联；形态分组，未修改心搏分类'})});
      s.saved[n]={id:data.id,name:data.name,family:data.rhythm_family,samples};
      if(isCurrent(s)){
        state.editTemplates=[data,...state.editTemplates.filter(t=>String(t.id)!==String(data.id))];renderEditClasses();
        if(typeof clinicalUI!=='undefined')await clinicalUI.loadOccurrences();
        closeForm();status(n+' 组模板“'+data.name+'”已保存，共 '+fmtNumber(samples.length)+' 搏；心搏分类未改变。');
      }
    }catch(error){if(isCurrent(s))status('模板未保存：'+error.message,true)}
    finally{saving=false;controls();}
  }
  function point(event,canvas){
    const g=plots.get(canvas),r=canvas.getBoundingClientRect();if(!g)return null;
    return {x:Math.max(0,Math.min(1,(event.clientX-r.left-g.l)/g.w)),y:Math.max(0,Math.min(1,(event.clientY-r.top-g.t)/g.h))};
  }
  function mount(){
    if(!qs('#morphGroups'))return;
    qs('#morphGroups').innerHTML=G.slots.map(n=>'<section class="morph-group" data-morph-group="'+n+'"><header><button type="button" data-group-select="'+n+'" aria-label="查看 '+n+' 组" aria-pressed="'+(n===6)+'"><b>'+n+'</b> <span data-group-count>0 搏</span></button><button type="button" data-group-move="'+n+'" disabled>移入 '+n+'</button></header><canvas id="morphSlot'+n+'" aria-label="'+n+' 组剥离心搏密度"></canvas></section>').join('');
    for(const [id,slot] of [['morphLeadTop','top'],['morphLeadBottom','bottom'],['morphLeadGroups','groups']]){
      const el=qs('#'+id);el.innerHTML=leads.map(l=>'<option value="'+l+'">'+l+'</option>').join('');el.value=view[slot];
      el.onchange=()=>{view[slot]=el.value;clearSelection();closeForm();refresh(true)};
    }
    qs('#morphTemplateFamily').innerHTML=['自定义','单发','成对','连续三发','连续多发','房速','室速','二联律','三联律(NNP)','三联律(NPP)','四联律','全部'].map(x=>'<option>'+esc(x)+'</option>').join('');
    qs('#morphTemplateForm').onsubmit=saveTemplate;qs('#morphTemplateCancel').onclick=closeForm;
    qs('#morphGroups').onclick=event=>{
      const b=event.target.closest('button');if(!b)return;
      if(b.dataset.groupMove)move(Number(b.dataset.groupMove)).catch(handleError);
      if(b.dataset.groupSelect){activeSlot=Number(b.dataset.groupSelect);controls();}
    };
    qs('#morphGroupTemplate').onclick=()=>templateForm(activeSlot);
    qs('#morphGroupRestore').onclick=()=>restore(activeSlot).catch(handleError);
    qs('#morphRetry').onclick=()=>{clearSelection();if(current){current.base={};current.limits={}}refresh(true)};
    qs('#morphUndo').onclick=()=>undo().catch(handleError);
    qs('#clearEditSelection').addEventListener('click',event=>{event.preventDefault();event.stopImmediatePropagation();clearSelection();status('已清除框选；分组保持不变。')},true);
    qs('#applyEditRange').addEventListener('click',event=>{
      event.preventDefault();event.stopImmediatePropagation();
      const values=['editRangeStart','editRangeEnd','editRangeTop','editRangeBottom'].map(id=>Number(qs('#'+id).value));
      if(values.some(v=>!Number.isFinite(v)||v<0||v>100)||values[0]===values[1]||values[2]===values[3]){status('请输入 0–100 的百分比范围，起止点不能相同。',true);return;}
      choose(qs('#morphRangeLead').value,{x:values[0]/100,y:values[2]/100},{x:values[1]/100,y:values[3]/100});
    },true);
    document.addEventListener('keydown',event=>{
      if(state.currentPage!=='edit'||!qs('#editWorkbench')?.getClientRects().length||event.target.closest('input,select,textarea,[contenteditable="true"],dialog,[role="dialog"]')||document.querySelector('dialog[open]'))return;
      const n=G.shortcut(event);if(n!==null){event.preventDefault();event.stopImmediatePropagation();if(!selection?.samples.length)status('请先在任一左侧密度图框选心搏，再按 '+n+'。');else move(n).catch(handleError);}
      if(event.key==='Escape'&&event.target.closest('.edit-density-panel')){event.preventDefault();event.stopImmediatePropagation();clearSelection();closeForm();}
    },true);
    for(const slot of ['top','bottom']){
      const canvas=sourceCanvas(slot);
      canvas.addEventListener('pointerdown',event=>{
        if(busy||saving||event.button!==0||!plots.has(canvas))return;
        event.preventDefault();canvas.focus({preventScroll:true});canvas.setPointerCapture(event.pointerId);
        const p=point(event,canvas);drag={slot,canvas,id:event.pointerId,a:p,b:p};selection=null;box={slot,points:[p,p]};controls();
      });
      canvas.addEventListener('pointermove',event=>{
        const p=point(event,canvas),g=plots.get(canvas);if(!p||!g)return;
        if(drag?.canvas===canvas){drag.b=p;box={slot,points:[drag.a,p]};scheduleDraw();}
        else canvas.title=view[slot]+' · '+(p.x*2-1).toFixed(3)+' s · '+((1-p.y*2)*g.limit).toFixed(0)+' 设备单位；拖动框选';
      });
      canvas.addEventListener('pointerup',event=>{
        if(drag?.canvas!==canvas||drag.id!==event.pointerId)return;
        const job=drag;drag=null;if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId);
        if(Math.abs(job.a.x-job.b.x)<.01||Math.abs(job.a.y-job.b.y)<.01){clearSelection();status('请拖出一个矩形范围。');return;}
        choose(slot,job.a,job.b);
      });
      canvas.addEventListener('pointercancel',()=>clearSelection());
      canvas.addEventListener('contextmenu',event=>{event.preventDefault();clearSelection();status('已取消框选；分组保持不变。')});
    }
    new ResizeObserver(scheduleDraw).observe(qs('.edit-density-panel'));
    refresh();
  }
  renderEditDensity=()=>{refresh()};
  document.addEventListener('DOMContentLoaded',mount);
  return {refresh};
})();
