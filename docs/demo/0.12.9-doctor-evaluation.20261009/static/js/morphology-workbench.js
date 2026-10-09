"use strict";
/* Two views of one remainder, four disjoint review groups. No raw-beat writes. */
const morphologyWorkbench=(()=>{
  const G=ECGMorphologyGroups,qs=s=>document.querySelector(s),esc=escapeHtml;
  const sessions=new Map(),plots=new Map(),bitmaps=new WeakMap(),leads=['I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'];
  const sourceIds={top:'editDensityPrimary',bottom:'editDensitySelection'};
  let current=null,requestToken=0,selectionToken=0,busy=false,selecting=false,saving=false,drag=null,selection=null,box=null,activeSlot=6,formSlot=null,formContext=null,saveReload=null;
  const view={top:'II',bottom:'V1',groups:'II'};
  const leadPositions=[['top','左上密度'],['bottom','左下密度'],['groups','右侧分组']],defaultLeads={top:'II',bottom:'V1',groups:'II'};
  let leadPicker=null,leadPickerOwner=null,leadPickerRead=null,leadPickerWatch=null;
  function closeLeadPicker(){
    leadPickerWatch?.disconnect();leadPickerWatch=null;
    leadPickerRead?.abort();leadPickerRead=null;leadPickerOwner=null;
    if(leadPicker?.open)leadPicker.close();
  }
  function leadPickerCurrent(owner){return leadPickerOwner===owner&&leadPicker?.open&&isCurrent(owner.session)&&owner.key===key(context());}
  function updateLeadPicker(){
    const owner=leadPickerOwner;if(!owner)return;
    leadPicker.querySelectorAll('[data-morph-lead-choice]').forEach(el=>{el.disabled=!owner.available.includes(el.value);el.checked=owner.selected.includes(el.value);});
    for(const [slot] of leadPositions){const el=leadPicker.querySelector('[data-morph-lead-position="'+slot+'"]');el.innerHTML=owner.selected.map(lead=>'<option>'+lead+'</option>').join('');el.value=owner.draft[slot];el.disabled=owner.loading||!owner.selected.length;}
    leadPicker.querySelector('[data-morph-lead-confirm]').disabled=owner.loading||!owner.selected.length;
    leadPicker.querySelector('[data-morph-lead-default]').disabled=owner.loading||!owner.available.length;
    leadPicker.querySelector('[data-morph-lead-status]').textContent=owner.loading?'正在核对当前病例的可用波形…':!owner.available.length?'未读到可用导联；请取消后重新读取。':'已选 '+owner.selected.length+' 个导联；显示位置 '+leadPositions.map(([slot,label])=>label+' '+owner.draft[slot]).join(' / ')+'。';
  }
  async function openLeadPicker(trigger){
    if(!leadPicker||leadPicker.open||!available(current))return;
    const s=current,owner={session:s,key:s.key,trigger,draft:{...view},selected:[...new Set(Object.values(view))],available:[],loading:true};
    leadPickerOwner=owner;leadPickerRead=new AbortController();const signal=leadPickerRead.signal;
    leadPicker.querySelector('[data-morph-lead-source]').textContent='正在读取本病例导联来源。';
    updateLeadPicker();leadPicker.showModal();
    leadPickerWatch=new MutationObserver(()=>{if(leadPickerOwner===owner&&(!isCurrent(s)||state.currentPage!=='edit'))closeLeadPicker();});
    leadPickerWatch.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['class','hidden','aria-busy']});
    try{
      const total=Number(state.caseData?.technical?.duration_seconds_raw)||1,params=new URLSearchParams({start:Math.max(0,Math.min(Number(state.editStart)||0,total-1)),duration:1,leads:leads.join(','),max_points:200,filter:'raw',...(s.basis?{analysis_basis:s.basis}:{}),...(s.analysisRevision!==undefined?{analysis_revision:s.analysisRevision}:{})});
      const data=await api('/api/cases/'+encodeURIComponent(s.id)+'/waveform?'+params,{signal});
      if(!leadPickerCurrent(owner))return;
      if(String(data.analysis_basis)!==String(s.basis)||String(data.analysis_revision)!==String(s.analysisRevision))throw Error('导联读取依据已变化，请重新读取密度后选择');
      owner.available=leads.filter(lead=>Array.isArray(data.leads?.[lead])&&data.leads[lead].length&&data.leads[lead].every(value=>Number.isFinite(value)));
      for(const [slot] of leadPositions)if(!owner.available.includes(owner.draft[slot]))owner.draft[slot]=owner.available.includes(defaultLeads[slot])?defaultLeads[slot]:owner.available[0]||'';
      owner.selected=[...new Set(Object.values(owner.draft).filter(Boolean))];owner.loading=false;updateLeadPicker();
      leadPicker.querySelector('[data-morph-lead-source]').textContent='可用项来自本病例服务返回的实际波形；'+(Number(state.caseData?.technical?.independent_channels)||8)+' 个存储通道派生显示导联，非新增采集信号。';
    }catch(error){
      if(!leadPickerCurrent(owner)||error.name==='AbortError')return;
      owner.loading=false;owner.available=[];owner.selected=[];updateLeadPicker();leadPicker.querySelector('[data-morph-lead-status]').textContent='导联读取失败：'+error.message+'；取消后可重新读取。';
    }
  }
  function mountLeadPicker(){
    // The native dialog is optional in isolated VM fixtures; browser behavior uses the real DOM.
    if(!globalThis.HTMLDialogElement||!document.body?.appendChild||leadPicker)return;
    leadPicker=document.createElement('dialog');leadPicker.id='morphLeadDialog';leadPicker.className='morph-lead-dialog';leadPicker.setAttribute('aria-labelledby','morphLeadDialogTitle');
    leadPicker.innerHTML='<header><h2 id="morphLeadDialogTitle">模板导联</h2><button type="button" data-morph-lead-cancel aria-label="关闭模板导联">×</button></header><p>勾选最多三个可用导联，再设置三个显示位置；同一导联可重复显示。确认后统一应用。</p><fieldset class="morph-lead-choices"><legend>可用导联</legend>'+leads.map(lead=>'<label><input type="checkbox" value="'+lead+'" data-morph-lead-choice>'+lead+'</label>').join('')+'</fieldset><div class="morph-lead-positions">'+leadPositions.map(([slot,label])=>'<label>'+label+'<select data-morph-lead-position="'+slot+'" aria-label="模板导联 '+label+'"></select></label>').join('')+'</div><p data-morph-lead-status role="status" aria-live="polite"></p><small data-morph-lead-source>正在读取本病例导联来源。</small><footer><button type="button" data-morph-lead-default>默认</button><span></span><button type="button" data-morph-lead-confirm>确定</button><button type="button" data-morph-lead-cancel>取消</button></footer>';
    document.body.appendChild(leadPicker);
    const trigger=document.createElement('button');trigger.type='button';trigger.id='morphLeadPicker';trigger.className='morph-lead-picker';trigger.textContent='模板导联…';trigger.setAttribute('aria-haspopup','dialog');trigger.setAttribute('aria-controls','morphLeadDialog');trigger.onclick=()=>openLeadPicker(trigger);qs('.morph-leads').after(trigger);
    leadPicker.querySelectorAll('[data-morph-lead-cancel]').forEach(el=>el.onclick=closeLeadPicker);
    leadPicker.addEventListener('cancel',event=>{event.preventDefault();closeLeadPicker();});
    leadPicker.addEventListener('keydown',event=>event.stopPropagation());
    leadPicker.addEventListener('close',()=>{leadPickerWatch?.disconnect();leadPickerWatch=null;leadPickerRead?.abort();leadPickerRead=null;leadPickerOwner=null;});
    leadPicker.addEventListener('change',event=>{
      const owner=leadPickerOwner;if(!owner||owner.loading)return;
      const choice=event.target.closest('[data-morph-lead-choice]'),position=event.target.closest('[data-morph-lead-position]');
      if(choice){
        if(choice.checked){
          if(owner.selected.length>=3){choice.checked=false;leadPicker.querySelector('[data-morph-lead-status]').textContent='最多选择三个不同导联；请先取消一个已选导联。';return;}
          if(!owner.available.includes(choice.value))return;
          owner.selected.push(choice.value);const slot=[...leadPositions].reverse().find(([slot])=>Object.values(owner.draft).filter(lead=>lead===owner.draft[slot]).length>1)?.[0]||'groups';owner.draft[slot]=choice.value;
        }else{owner.selected=owner.selected.filter(lead=>lead!==choice.value);for(const [slot] of leadPositions)if(owner.draft[slot]===choice.value)owner.draft[slot]=owner.selected[0]||'';}
      }
      if(position)owner.draft[position.dataset.morphLeadPosition]=position.value;
      updateLeadPicker();
    });
    leadPicker.querySelector('[data-morph-lead-default]').onclick=()=>{const owner=leadPickerOwner;if(!owner||owner.loading)return;owner.draft=Object.fromEntries(leadPositions.map(([slot])=>[slot,owner.available.includes(defaultLeads[slot])?defaultLeads[slot]:owner.available[0]||'']));owner.selected=[...new Set(Object.values(owner.draft).filter(Boolean))];updateLeadPicker();};
    leadPicker.querySelector('[data-morph-lead-confirm]').onclick=()=>{
      const owner=leadPickerOwner;if(!owner||owner.loading||!leadPickerCurrent(owner)||!available(owner.session)||leadPositions.some(([slot])=>!owner.available.includes(owner.draft[slot])))return;
      const changed=leadPositions.some(([slot])=>view[slot]!==owner.draft[slot]);Object.assign(view,owner.draft);
      for(const [id,slot] of [['morphLeadTop','top'],['morphLeadBottom','bottom'],['morphLeadGroups','groups']])qs('#'+id).value=view[slot];
      closeLeadPicker();if(changed){clearSelection();if(formSlot!==null)qs('#morphTemplateTitle').textContent=formSlot+' 组 · '+fmtNumber(current.groups.slots[formSlot].length)+' 搏 · '+view.groups+' · r'+current.revision+' · '+(current.saved[formSlot]?'编辑模板':'设置模板');refresh(true);}else controls();
    };
  }
  const linkedListeners=new Set();let linkedNotifyQueued=false,linkedSubscribed=false;
  function notifyLinked(){if(!linkedNotifyQueued){linkedNotifyQueued=true;Promise.resolve().then(()=>{linkedNotifyQueued=false;const snapshot=privateSnapshot();for(const fn of linkedListeners)fn(snapshot);});}}
  function privateSnapshot(){
    const s=current;if(!s||!isCurrent(s))return null;
    const frozen=values=>Object.freeze([...(values||[])]);
    return Object.freeze({caseId:s.id,caseToken:s.caseToken,analysis_basis:s.basis,analysis_revision:s.analysisRevision,beatRevision:s.revision,sourceKey:s.key,source:s.source,phase:s.phase,ready:available(s),sourcePopulation:frozen(s.groups?.source),remainder:frozen(s.groups?.remaining()),groups:Object.freeze(Object.fromEntries(G.slots.map(n=>[n,frozen(s.groups?.slots[n])]))),partitionGeneration:s.partitionGeneration||0,viewedScope:Object.freeze({...s.viewedScope||{kind:'remainder'}}),leads:Object.freeze({...view}),limits:Object.freeze({...s.limits}),linked:s.linked?Object.freeze({phase:s.linked.phase,count:s.linked.count??null,crossSource:s.linked.crossSource??null,otherGroups:s.linked.otherGroups??null,top:s.linked.data?.top?Object.freeze({total:s.linked.data.top.total,included:s.linked.data.top.included,skipped_edges:s.linked.data.top.skipped_edges}):null,bottom:s.linked.data?.bottom?Object.freeze({total:s.linked.data.bottom.total,included:s.linked.data.bottom.included,skipped_edges:s.linked.data.bottom.skipped_edges}):null}):null});
  }
  const linkedViewKey=s=>JSON.stringify([s?.key,s?.revision,s?.partitionGeneration||0,s?.viewedScope?.kind||'remainder',s?.viewedScope?.slot??null,view.top,view.bottom]);
  function linkedPopulation(s,snap){
    const population=new Set(s.groups.source),partition=new Set(s.viewedScope?.kind==='group'?s.groups.slots[s.viewedScope.slot]:s.groups.remaining());
    const exact=snap.kind==='samples'?snap.samples:s.groups.source,inSource=exact.filter(x=>population.has(x)),samples=inSource.filter(x=>partition.has(x));
    return {samples,crossSource:exact.length-inSource.length,otherGroups:inSource.length-samples.length};
  }
  async function refreshLinked(){
    const C=globalThis.ECGLinkedSelection,s=current,snap=C?.snapshot();if(!C||!snap?.scope||!available(s))return;
    if(snap.scope.caseId!==s.id||snap.scope.caseToken!==s.caseToken||String(snap.scope.analysis_basis)!==String(s.basis)||String(snap.scope.analysis_revision)!==String(s.analysisRevision)||String(snap.scope.beatRevision)!==String(s.revision))return;
    const active=snap.kind==='samples'||s.viewedScope?.kind==='group',viewKey=linkedViewKey(s);
    if(!active){C.cancelLane('template.density');s.linked=null;controls();drawAll();notifyLinked();return;}
    const cacheKey=JSON.stringify([snap.selectionGeneration,viewKey]);if(s.linked?.key===cacheKey&&s.linked.phase==='ready'){drawAll();return;}
    const ticket=C.beginLane('template.density',viewKey,{focusSensitive:false}),counts=linkedPopulation(s,snap);s.linked={key:cacheKey,phase:'loading',data:{},...counts,count:counts.samples.length};controls();drawAll();notifyLinked();
    try{
      const pairs=await Promise.all(['top','bottom'].map(async slot=>[slot,await request(s,view[slot],{samples:counts.samples,amplitude_limit:s.limits[view[slot]]},null,{signal:ticket.signal})]));
      if(!C.isCurrent(ticket,linkedViewKey(current))||!isCurrent(s)||snap.selectionGeneration!==C.snapshot().selectionGeneration)return;
      s.linked={key:cacheKey,phase:'ready',data:Object.fromEntries(pairs),...counts,count:counts.samples.length};controls();drawAll();notifyLinked();
    }catch(error){if(error.name==='AbortError'||!C.isCurrent(ticket,linkedViewKey(current))||!isCurrent(s))return;s.linked={key:cacheKey,phase:'error',data:{},...counts,count:counts.samples.length};status('联动密度读取失败：'+error.message+'；原分组保留，可重新读取。',true);drawAll();notifyLinked();}
  }
  let drawFrame=0;
  function scheduleDraw(){if(!drawFrame)drawFrame=requestAnimationFrame(()=>{drawFrame=0;drawAll()})}
  function context(){
    const source=state.editSelectedClass||'source-N',filter=qs('#occTemplate')?.value;
    const template=source.startsWith('custom-')?source.slice(7):filter&&filter!=='all'?filter:null;
    const params=template?{template_id:template}:{class_code:source.startsWith('source-')?source.slice(7):'N'};
    const identity=state.editReadIdentity?.id===state.caseId&&state.editReadIdentity.caseToken===state.caseRequestId?state.editReadIdentity:null;
    return {id:state.caseId,caseToken:state.caseRequestId??0,revision:state.caseData?.analysis_revision??0,basis:identity?.analysis_basis||state.report?.current_analysis_basis?.digest||'',analysisRevision:identity?.analysis_revision,source:template?'custom-'+template:source,params};
  }
  const key=c=>[c.id,c.revision,c.source,c.basis,...(c.analysisRevision===undefined?[]:[c.analysisRevision])].join('|');
  const sameSamples=(a,b)=>Array.isArray(a)&&Array.isArray(b)&&a.length===b.length&&a.every((sample,i)=>sample===b[i]);
  function ownSaveTransition(c){
    const receipt=saveReload,s=receipt?.session;
    return !!receipt&&current===s&&formContext===receipt.owner&&s.key===receipt.key&&s.caseToken===c.caseToken&&s.id===c.id&&s.source===c.source&&s.revision===c.revision&&s.basis===c.basis&&Number.isSafeInteger(s.analysisRevision)&&c.analysisRevision===s.analysisRevision+1&&s.saved[receipt.slot]?.id===receipt.id&&sameSamples(s.groups.slots[receipt.slot],receipt.samples);
  }
  const isCurrent=s=>current===s&&s.caseToken===(state.caseRequestId??0)&&key(context())===s.key;
  const available=s=>!!s?.groups&&isCurrent(s)&&!['error','stale','loading'].includes(s.phase)&&!busy&&!saving;
  const status=(message,error=false)=>{const el=qs('#morphStatus');if(el){el.textContent=message;el.dataset.error=String(error)}};
  function clearSelection(){selectionToken++;if(selecting){selecting=false;busy=false}selection=null;box=null;drag=null;controls();drawAll();}
  function sourceCanvas(slot){return qs('#'+sourceIds[slot]);}
  function focusFormTrigger(mark){
    const trigger=mark?.trigger;
    if(mark&&mark.id===state.caseId&&mark.caseToken===(state.caseRequestId??0)&&mark.key===key(context())&&trigger?.isConnected&&trigger.getClientRects().length&&!trigger.disabled)trigger.focus();
  }
  function closeForm(returnFocus=false){
    const form=qs('#morphTemplateForm'),mark=formContext,ownedFocus=returnFocus===true&&form.contains(document.activeElement);
    formSlot=null;formContext=null;form.hidden=true;if(ownedFocus)focusFormTrigger(mark);
  }
  async function request(s,lead,payload={},gate=null,options={}){
    const params=new URLSearchParams({...s.params,lead});if(gate)params.set('gate',gate.join(','));
    const d=await api('/api/cases/'+encodeURIComponent(s.id)+'/waveform-density?'+params,{method:'POST',...options,body:JSON.stringify({revision:s.revision,beat_revision:s.revision,...(s.basis?{analysis_basis:s.basis}:{}),...(s.analysisRevision!==undefined?{analysis_revision:s.analysisRevision}:{}),...payload})});
    if(d.revision!==s.revision){const error=Error('心搏修订版本已变化，请刷新病例后重新框选');error.code='STALE_REVISION';throw error;}
    if(globalThis.ECGLinkedSelection&&s.analysisRevision!==undefined?(String(d.beat_revision)!==String(s.revision)||String(d.analysis_basis)!==String(s.basis)||String(d.analysis_revision)!==String(s.analysisRevision)):(d.analysis_basis!==undefined&&String(d.analysis_basis)!==String(s.basis)||d.analysis_revision!==undefined&&String(d.analysis_revision)!==String(s.analysisRevision))){const error=Error('密度临床依据已变化，请重新读取');error.code='STALE_REVISION';throw error;}
    return d;
  }
  function controls(){
    if(!qs('#morphGroups'))return;
    const ready=available(current),count=selection?.samples.length||0,remaining=current?.groups?current.groups.source.length-Object.values(current.groups.slots).reduce((sum,values)=>sum+values.length,0):undefined;
    document.querySelectorAll('[data-edit-mode]').forEach(tab=>tab.disabled=saving);
    qs('#editMorphologyCount').textContent=remaining===undefined?(busy?'正在统计…':'数量未读取'):'剩余 '+fmtNumber(remaining)+' / '+fmtNumber(current.groups.source.length)+' 搏';
    qs('#editMorphSelectionLabel').textContent=selection?view[selection.slot]+' 已框选 '+fmtNumber(count)+' 搏':'尚未框选';
    const unsaved=G.slots.filter(n=>current?.groups?.slots[n]?.length&&!current?.saved[n]);
    const source=current?.source||context().source,label=typeof editClassLabel==='function'?editClassLabel(source):source;
    const scope=qs('#morphScope');if(scope){
      scope.textContent='当前集合 '+label+' · 整组 '+(current?.groups?fmtNumber(current.groups.source.length)+' 搏':'—')+' · r'+(current?.revision??context().revision)+'；两图'+(current?.linked?'联动'+(current.viewedScope?.kind==='group'?current.viewedScope.slot+'组':'剩余')+'子集 '+fmtNumber(current.linked.count)+' 搏':'全量剩余集合')+'，非本页代表搏。导联 '+view.top+' / '+view.bottom+'；未保存分组 '+(unsaved.length?unsaved.map(n=>n+' 组（'+fmtNumber(current.groups.slots[n].length)+' 搏）').join('、'):'无')+'。';
      scope.dataset.state=current?.phase||'loading';
    }
    const summary=qs('#morphScopeSummary');if(summary){
      const phase=current?.phase||'loading',phaseLabel={loading:'正在读取',error:'读取失败',stale:'依据失效',empty:'空集合',insufficient:'边界不足'}[phase];
      summary.textContent=(source.startsWith('custom-')?'自定义模板':label)+' · '+(remaining===undefined?'—':fmtNumber(remaining)+' / '+fmtNumber(current.groups.source.length)+' 搏')+' · r'+(current?.revision??context().revision)+(phaseLabel?' · '+phaseLabel:'');
      summary.dataset.state=phase;
    }
    const sources=qs('#morphGroupSources');if(sources)sources.textContent=G.slots.map(n=>{
      const values=current?.groups?.slots[n]||[],saved=current?.saved[n];
      return n+' 组 · '+fmtNumber(values.length)+' 搏 · '+(saved?'已保存“'+saved.name+'”':values.length?'未保存':'空组')+' · 来源 '+label+' · '+view.groups+' · r'+(current?.revision??context().revision);
    }).join('；')+'。';
    const impact=qs('#morphImpact');if(impact)impact.textContent=saving?'正在保存形态模板…':busy?(selecting?'正在匹配框选，暂不能移入。':'正在读取密度，暂不能分组。'):!ready?'密度依据不可用；请重新读取，版本变化时先刷新病例。':count?'移入将影响框选的 '+fmtNumber(count)+' 搏（'+view[selection.slot]+' · r'+current.revision+'）；只调整形态分组，心搏分类不变。':'先在任一左图框选；分组可撤销，保存模板才会保留。';
    qs('#clearEditSelection').disabled=!selection&&!box||saving;
    qs('#morphUndo').disabled=!ready||!current.groups.history.length;
    qs('#morphRetry').disabled=busy||saving;
    if(qs('#workspaceDensityRetry'))qs('#workspaceDensityRetry').disabled=busy||saving;
    qs('#applyEditRange').disabled=!ready;
    for(const id of ['morphLeadTop','morphLeadBottom','morphLeadGroups'])qs('#'+id).disabled=busy||saving;
    if(qs('#morphLeadPicker'))qs('#morphLeadPicker').disabled=!ready;
    G.slots.forEach(n=>{
      const values=current?.groups?.slots[n]||[],saved=current?.saved[n];
      const card=qs('[data-morph-group="'+n+'"]');card.dataset.active=String(n===activeSlot);
      card.dataset.saved=String(!!saved);
      card.querySelector('[data-group-count]').textContent=fmtNumber(values.length)+'搏';
      card.querySelector('[data-group-state]').textContent=saved?'已存':values.length?'未存':'空';
      const select=card.querySelector('[data-group-select]');select.setAttribute('aria-pressed',String(n===activeSlot));
      select.setAttribute('aria-label','查看 '+n+' 组 · '+fmtNumber(values.length)+' 搏 · '+(saved?'已保存 '+saved.name:values.length?'未保存模板':'空组')+' · 来源 '+label);
      const move=card.querySelector('[data-group-move]');move.disabled=!ready||!count||!!saved;
      move.title=saved?'已保存的组不能追加；可归还左侧后重新建组':!ready?'请等待读取完成；失败时重新读取':!count?'请先框选心搏':'将 '+fmtNumber(count)+' 搏移入 '+n+' 组 · r'+current.revision+'；心搏分类不变';
      select.title=n+' 组 · '+fmtNumber(values.length)+' 搏 · '+(saved?'已保存 '+saved.name:values.length?'未保存模板':'空组')+' · 来源 '+label+' · '+view.groups+' · r'+(current?.revision??context().revision);
    });
    const saved=current?.saved[activeSlot],populated=!!current?.groups?.slots[activeSlot]?.length;
    qs('#morphActiveGroup').textContent=activeSlot+' 组 · '+fmtNumber(current?.groups?.slots[activeSlot]?.length||0)+' 搏 · '+view.groups+' · '+(saved?'已保存':populated?'未保存模板':'空组');
    qs('#morphActiveGroup').title=saved?'已保存“'+saved.name+'” · 来源 '+label:'来源 '+label;
    qs('#morphGroupTemplate').textContent=saved?'编辑模板':'设为模板';
    qs('#morphGroupTemplate').disabled=qs('#morphGroupRestore').disabled=!ready||!populated;
    qs('#morphGroupTemplate').title=populated?'保存 '+fmtNumber(current.groups.slots[activeSlot].length)+' 搏的形态模板；不改变心搏分类':'请先移入心搏到当前组';
    qs('#morphGroupRestore').title=populated?'将当前组全部 '+fmtNumber(current.groups.slots[activeSlot].length)+' 搏归还两左图；已保存模板保留':'当前组为空';
    qs('#morphUndo').title=ready&&current.groups.history.length?'撤销最近一次剥离或归还；已保存模板保留':'尚无可撤销的分组操作，或密度依据不可用';
    qs('#morphTemplateForm').querySelectorAll('input,select,button').forEach(el=>el.disabled=saving);
    const submit=qs('#morphTemplateForm').querySelector('button[type="submit"]');if(submit){submit.disabled=!ready;submit.title=ready?'保存当前组的形态模板；心搏分类不变':'密度依据不可用，请重新读取后保存';}
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
    ctx.fillStyle='#e5f0eb';ctx.font='12px '+UI_FONT;
    if(!data){ctx.fillText(message,10,height/2);canvas.setAttribute('aria-description',message);plots.delete(canvas);return}
    const group=!!canvas.dataset.morphGroupPlot,compact=!canvas.dataset.morphSource,pad=group?2:compact?3:8,foot=group?12:compact?20:24;
    const g={l:pad,t:pad,w:Math.max(1,width-pad*2),h:Math.max(1,height-pad-foot),limit:data.amplitude_limit,data};
    ctx.imageSmoothingEnabled=false;ctx.drawImage(bitmap(data),g.l,g.t,g.w,g.h);
    ctx.strokeStyle='#758d82';ctx.setLineDash([2,3]);ctx.beginPath();ctx.moveTo(g.l+g.w/2,g.t);ctx.lineTo(g.l+g.w/2,g.t+g.h);ctx.stroke();ctx.setLineDash([]);
    if(group)ctx.font='10px '+UI_FONT;
    ctx.fillText('−1s',g.l,height-(group?2:4));if(!compact||width>=100){ctx.textAlign='center';ctx.fillText('R · 0',width/2,height-(group?2:4))}ctx.textAlign='right';ctx.fillText('+1s',width-pad,height-(group?2:4));ctx.textAlign='left';
    if(!data.included)ctx.fillText(data.total?'边界不足，无法叠加':current?.groups?.source.length?'剩余集合为空':'当前集合没有心搏',10,height/2);
    if(box&&canvas.dataset.morphSource===box.slot){const [a,b]=box.points;ctx.strokeStyle='#fff';ctx.lineWidth=1.5;ctx.strokeRect(g.l+Math.min(a.x,b.x)*g.w,g.t+Math.min(a.y,b.y)*g.h,Math.abs(a.x-b.x)*g.w,Math.abs(a.y-b.y)*g.h);}
    plots.set(canvas,g);
    canvas.setAttribute('aria-description',data.lead+'；'+data.included+' 搏参与密度统计；边界不足 '+data.skipped_edges+' 搏；幅度范围 ±'+Math.round(data.amplitude_limit)+' 设备单位');
  }
  function drawAll(){
    const s=current;
    for(const slot of ['top','bottom']){
      const linked=!!s?.linked,d=linked?s.linked.phase==='ready'?s.linked.data[slot]:null:s?.data[slot];draw(sourceCanvas(slot),d,linked?(s.linked.phase==='loading'?'正在统计联动选集…':'联动读取失败 · 原分组保留'):busy?'正在统计…':s?.phase==='stale'?'依据失效 · 刷新病例':s?.phase==='error'?'读取失败 · 重新读取':'尚未读取');
      qs('[data-morph-count="'+slot+'"]').textContent=d?fmtNumber(d.included)+' 搏':'';
      qs(slot==='top'?'#editDensityPrimaryLabel':'#morphSecondaryLabel').textContent=view[slot]+' · '+(linked?'联动 '+(s.viewedScope?.kind==='group'?s.viewedScope.slot+'组':'剩余'):'剩余心搏');
    }
    for(const n of G.slots)draw(qs('#morphSlot'+n),s?.data[n],s?.groups?.slots[n]?.length?(busy?'正在统计…':s?.phase==='stale'?'依据失效':s?.phase==='error'?'读取失败':'尚未读取'):'空组 · 按 '+n);
    // Library mirrors use the full source population, never the visible cards
    // or peeled remainder. Both views share the same revision-scoped request.
    for(const [slot,id,labelId] of [['top','editLibraryDensityPrimary','editLibraryDensityLabel'],['bottom','editLibraryDensitySelection','editLibraryDensitySelectionLabel']]){
      const d=s&&isCurrent(s)&&!['stale','error'].includes(s.phase)?s.linked?(s.linked.phase==='ready'?s.linked.data[slot]:null):s.base[view[slot]]:null;
      const message=busy?'统计完整集合…':s?.phase==='error'?'读取失败 · 请重试':s?.phase==='stale'?'依据失效 · 刷新病例':'尚未读取';
      draw(qs('#'+id),d,message);
      const label=qs('#'+labelId);if(label)label.textContent=view[slot]+' · '+(s?.linked?'联动选集 · ':'来源全量 · ')+(d?fmtNumber(d.included)+' / '+fmtNumber(d.total)+' 搏':message);
    }
  }
  async function refresh(force=false){
    if(!state.caseId||state.currentPage!=='edit'||!qs('#morphGroups'))return;
    const c=context(),k=key(c);
    if(leadPickerOwner&&(leadPickerOwner.key!==k||leadPickerOwner.session.caseToken!==c.caseToken))closeLeadPicker();
    if(current?.key===k&&current.caseToken===c.caseToken&&!force&&current.analysisRevision===c.analysisRevision&&!['error','stale'].includes(current.phase)){drawAll();controls();notifyLinked();refreshLinked();return;}
    if(current?.key!==k||current.caseToken!==c.caseToken){
      const carry=ownSaveTransition(c),receipt=saveReload;clearSelection();
      if(carry){
        // Only the acknowledged save may advance this session by one review
        // revision. Fresh density must prove the complete source is unchanged.
        sessions.delete(current.key);
        Object.assign(current,c,{key:k,limits:{},base:{},data:{},pending:new Map(),phase:'loading',saveRebase:{receipt,population:[...current.groups.source]}});
        saveReload=null;
      }else{closeForm();current={...(sessions.get(k)||{groups:null,limits:{},base:{},data:{},saved:{},phase:'loading'}),...c,key:k,pending:new Map()};}
      sessions.set(k,current);
    }
    while(sessions.size>6)sessions.delete(sessions.keys().next().value);
    Object.assign(current,c);
    const s=current,token=++requestToken;let finishRefresh;s.refreshDone=new Promise(resolve=>{finishRefresh=resolve});selectionToken++;selecting=false;busy=true;s.phase='loading';s.data={};s.linked=null;globalThis.ECGLinkedSelection?.cancelLane('template.density');controls();drawAll();notifyLinked();status('正在统计完整心搏集合…');
    try{
      // Unique leads run together. Reuse in-flight work during a refresh and show
      // each source as soon as it arrives rather than waiting for every group.
      s.pending ||= new Map();
      const needed=new Set([view.top,view.bottom]);if(Object.values(s.groups?.slots||{}).some(v=>v.length))needed.add(view.groups);
      await Promise.all([...needed].map(async lead=>{
        if(!s.base[lead]){
          if(!s.pending.has(lead))s.pending.set(lead,request(s,lead).finally(()=>s.pending.delete(lead)));
          const d=await s.pending.get(lead);if(token!==requestToken||!isCurrent(s))return;
          if(s.saveRebase&&!sameSamples(d.population_samples,s.saveRebase.population)){const error=Error('保存后来源心搏成员已变化，原分组保留待复核');error.code='STALE_REVISION';throw error;}
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
      const remaining=s.groups.remaining().length;
      s.phase=!s.groups.source.length?'empty':remaining&&!s.data.top?.included&&!s.data.bottom?.included?'insufficient':'ready';
      if(s.saveRebase){
        const {receipt}=s.saveRebase;receipt.verified=true;
        if(formContext===receipt.owner)receipt.owner.key=s.key;
        delete s.saveRebase;
      }
      const edges=['top','bottom'].filter(slot=>s.data[slot]?.skipped_edges).map(slot=>view[slot]+' '+fmtNumber(s.data[slot].skipped_edges)+' 搏边界不足').join('；');
      status(s.phase==='empty'?'当前来源集合没有心搏；请选择其他源类别或模板。':!remaining?'剩余集合为空；全部 '+fmtNumber(excluded.length)+' 搏已移入分组，可归还或撤销。':s.phase==='insufficient'?'当前 '+fmtNumber(remaining)+' 搏均缺少完整边界，无法绘制密度；可切换来源查看。':'剩余 '+fmtNumber(remaining)+' 搏；已剥离 '+fmtNumber(excluded.length)+' 搏。'+(edges?edges+'，未绘入对应导联密度。':'可在任一左图框选。'));
      qs('#morphMethod').textContent='R 峰对齐 ±1s；绿→黄→红为对数密度。去固定基线，不逐搏归一化；幅度为设备单位，未作临床校准。两左图同一集合。剥离不删除心搏；分组仅暂存在本页面，保存模板才会保留。';
    }catch(error){if(token===requestToken&&isCurrent(s)){s.phase=error.code==='STALE_REVISION'?'stale':'error';status((s.phase==='stale'?'密度依据失效：':'密度读取失败：')+error.message+'。'+(s.phase==='stale'?'请刷新病例后重新复核。':'可点“重新读取”；分组与模板输入保留。'),true);s.data={}}}
    finally{if(token===requestToken&&isCurrent(s)){busy=false;controls();drawAll();notifyLinked();refreshLinked();}finishRefresh();}
  }
  async function choose(slot,a,b){
    const s=current,g=plots.get(sourceCanvas(slot));if(!available(s)||!g)return;
    if(s.viewedScope?.kind==='group'){status('当前查看已剥离组；请先点击“查看剩余”，再框选移入。');return;}
    const token=++selectionToken;selection=null;box={slot,points:[a,b]};busy=true;selecting=true;controls();drawAll();status('正在按 '+view[slot]+' 在剩余集合中精确匹配…');
    const gate=[Math.min(a.x,b.x)*2-1,Math.max(a.x,b.x)*2-1,(1-2*Math.max(a.y,b.y))*g.limit,(1-2*Math.min(a.y,b.y))*g.limit];
    try{
      const d=await request(s,view[slot],{samples:g.data.population_samples,exclude_samples:Object.values(s.groups.slots).flat(),amplitude_limit:g.limit},gate);
      if(token!==selectionToken||!isCurrent(s))return;
      selection={slot,samples:d.sample_indices};
      const C=globalThis.ECGLinkedSelection,expected=C?.snapshot().scope;if(expected&&expected.caseId===s.id&&String(expected.analysis_basis)===String(s.basis))C.select({samples:d.sample_indices,origin:'template.density-gate',sourcePopulation:s.groups.source.length},{expectedScope:expected});
      status(d.sample_indices.length?'已匹配 '+fmtNumber(d.sample_indices.length)+' 搏。按 6 / 7 / 8 / 9，或点击右侧“移入”。':'此区域没有匹配心搏，请换一个区域。');
    }catch(error){if(token===selectionToken&&isCurrent(s)){if(error.code==='STALE_REVISION'){s.phase='stale';s.data={};}status((s.phase==='stale'?'密度依据失效：':'框选失败：')+error.message,true)}}
    finally{if(token===selectionToken&&isCurrent(s)){busy=false;selecting=false;controls();drawAll();notifyLinked();refreshLinked();}}
  }
  async function move(n){
    if(!available(current)||!selection?.samples.length)return;
    if(current.saved[n]){status('该组已有模板；请先归还左侧或选择其他空组。',true);return;}
    current.groups.move(n,selection.samples);current.partitionGeneration=(current.partitionGeneration||0)+1;activeSlot=n;clearSelection();closeForm();await refresh(true);
  }
  async function restore(n){
    if(!available(current)||!current.groups.restore(n))return;
    current.partitionGeneration=(current.partitionGeneration||0)+1;
    delete current.saved[n];clearSelection();closeForm();await refresh(true);
    status(n+' 组已归还左侧。已经保存的模板仍保留在模板库。');
  }
  async function undo(){
    if(!available(current)||!current.groups.undo())return;
    current.partitionGeneration=(current.partitionGeneration||0)+1;
    for(const n of G.slots){const saved=current.saved[n];if(saved&&saved.samples.join(',')!==current.groups.slots[n].join(','))delete current.saved[n];}
    clearSelection();closeForm();await refresh(true);status('已撤销上一次剥离 / 归还；已保存的模板不会被删除。');
  }
  function templateForm(n,focus=true){
    if(!available(current)||!current.groups.slots[n].length)return;activeSlot=n;formSlot=n;
    formContext={id:current.id,caseToken:current.caseToken,key:current.key,trigger:qs('#morphGroupTemplate')};
    const saved=current.saved[n];qs('#morphTemplateTitle').textContent=n+' 组 · '+fmtNumber(current.groups.slots[n].length)+' 搏 · '+view.groups+' · r'+current.revision+' · '+(saved?'编辑模板':'设置模板');
    qs('#morphTemplateName').value=saved?.name||'';qs('#morphTemplateFamily').value=saved?.family||'自定义';
    qs('#morphTemplateForm').hidden=false;controls();if(focus)qs('#morphTemplateName').focus();
  }
  async function saveTemplate(event){
    event.preventDefault();const s=current,n=formSlot;if(!available(s)||n===null)return;
    const name=qs('#morphTemplateName').value.trim(),family=qs('#morphTemplateFamily').value,samples=[...s.groups.slots[n]],lead=view.groups;
    if(!name||!samples.length){status('请填写模板名称，并先剥离心搏到该组。',true);return;}
    const existing=s.saved[n],form=qs('#morphTemplateForm'),owner=formContext,startedInForm=form.contains(document.activeElement);
    let returnFocus=false,focusMoved=false,committed=false,receipt=null;
    const trackFocus=event=>{if(event.target!==document.body&&!form.contains(event.target))focusMoved=true;};
    document.addEventListener('focusin',trackFocus);
    saving=true;controls();
    try{
      const note='密度图 '+n+' 组；'+lead+' 导联；形态分组，未修改心搏分类';
      const payload=existing?{name,rhythm_family:family,note}:{name,rhythm_family:family,lead,source_class:s.source,sample_indices:samples,revision:s.revision,note};
      const data=await api(existing?'/api/beat-templates/'+existing.id:'/api/cases/'+encodeURIComponent(s.id)+'/beat-templates',{method:existing?'PATCH':'POST',body:JSON.stringify(payload)});
      committed=true;
      s.saved[n]={id:data.id,name:data.name,family:data.rhythm_family,samples};
      if(isCurrent(s)&&formContext===owner){
        if(data.case_id===s.id&&sameSamples(data.sample_indices,samples)&&Number.isSafeInteger(s.analysisRevision)){
          receipt={session:s,owner,key:s.key,slot:n,id:data.id,samples};saveReload=receipt;
        }
        state.editTemplates=[data,...state.editTemplates.filter(t=>String(t.id)!==String(data.id))];renderEditClasses();
        if(typeof clinicalUI!=='undefined')await clinicalUI.loadOccurrences();
        if(isCurrent(s)&&s.refreshDone)await s.refreshDone;
        if(isCurrent(s)&&formContext===owner&&!s.saveRebase&&!['stale','error','loading'].includes(s.phase)){
          returnFocus=!focusMoved&&(form.contains(document.activeElement)||startedInForm&&document.activeElement===document.body);
          closeForm();status(n+' 组模板“'+data.name+'”已保存，共 '+fmtNumber(samples.length)+' 搏；心搏分类未改变。');
        }
      }
    }catch(error){if(isCurrent(s))status((committed?'模板已保存，但刷新失败；原分组保留：':'模板未保存：')+error.message,true)}
    finally{if(saveReload===receipt)saveReload=null;document.removeEventListener('focusin',trackFocus);saving=false;controls();if(returnFocus)focusFormTrigger(owner);}
  }
  function point(event,canvas){
    const g=plots.get(canvas),r=canvas.getBoundingClientRect();if(!g)return null;
    return {x:Math.max(0,Math.min(1,(event.clientX-r.left-g.l)/g.w)),y:Math.max(0,Math.min(1,(event.clientY-r.top-g.t)/g.h))};
  }
  function captureView(){
    return {key:current?.key,session:current,caseToken:state.caseRequestId,view:{...view},linkedViewedScope:{...current?.viewedScope||{kind:'remainder'}},selection:selection?{slot:selection.slot,samples:[...selection.samples]}:null,box:box?{slot:box.slot,points:box.points.map(p=>({...p}))}:null,activeSlot,formSlot,formOpen:!qs('#morphTemplateForm').hidden,name:qs('#morphTemplateName').value,family:qs('#morphTemplateFamily').value,range:['morphRangeLead','editRangeStart','editRangeEnd','editRangeTop','editRangeBottom'].map(id=>qs('#'+id).value),rangeOpen:qs('.morph-keyboard-range').open};
  }
  function resetView(){
    closeLeadPicker();
    requestToken++;selectionToken++;current=null;saveReload=null;busy=false;selecting=false;sessions.clear();
    globalThis.ECGLinkedSelection?.cancelLane('template.density');notifyLinked();
    clearSelection();closeForm();activeSlot=6;Object.assign(view,{top:'II',bottom:'V1',groups:'II'});
    for(const [id,slot] of [['morphLeadTop','top'],['morphLeadBottom','bottom'],['morphLeadGroups','groups']])if(qs('#'+id))qs('#'+id).value=view[slot];
    qs('#morphTemplateName').value='';qs('#morphTemplateFamily').value='自定义';
    ['morphRangeLead','editRangeStart','editRangeEnd','editRangeTop','editRangeBottom'].forEach((id,i)=>qs('#'+id).value=['top','38','62','18','54'][i]);
    qs('.morph-keyboard-range').open=false;
  }
  async function restoreView(mark,valid=()=>true){
    if(!valid())return;
    const usable=mark&&mark.caseToken===state.caseRequestId&&mark.key===key(context());
    if(!usable){clearSelection();closeForm();await refresh();return;}
    if(mark.session){sessions.set(mark.key,mark.session);if(current?.groups!==mark.session.groups)current=null;}
    if(mark.session)mark.session.viewedScope={...mark.linkedViewedScope||{kind:'remainder'}};
    Object.assign(view,mark.view);
    for(const [id,slot] of [['morphLeadTop','top'],['morphLeadBottom','bottom'],['morphLeadGroups','groups']])qs('#'+id).value=view[slot];
    ['morphRangeLead','editRangeStart','editRangeEnd','editRangeTop','editRangeBottom'].forEach((id,i)=>qs('#'+id).value=mark.range[i]);
    qs('.morph-keyboard-range').open=mark.rangeOpen;
    // The fresh refresh checks the same revision/basis before re-enabling edits.
    await refresh(true);
    if(!valid()||!isCurrent(current)||current.key!==mark.key||!available(current))return;
    selection=mark.selection;box=mark.box;activeSlot=mark.activeSlot;
    if(mark.formOpen&&current.groups.slots[mark.formSlot]?.length){templateForm(mark.formSlot,false);qs('#morphTemplateName').value=mark.name;qs('#morphTemplateFamily').value=mark.family;}
    else closeForm();
    controls();drawAll();notifyLinked();refreshLinked();
  }
  function mount(){
    if(!qs('#morphGroups'))return;
    if(!qs('#morphViewRemaining')){const b=document.createElement('button');b.type='button';b.id='morphViewRemaining';b.textContent='查看剩余';b.title='返回当前剩余集合；保留联动筛选、全部分组和模板输入';b.onclick=()=>{if(!available(current))return;clearSelection();current.viewedScope={kind:'remainder'};notifyLinked();refreshLinked();};qs('.morph-group-tools').append(b);}
    if(!linkedSubscribed&&globalThis.ECGLinkedSelection){linkedSubscribed=true;let generation=null;ECGLinkedSelection.subscribe((snap,detail)=>{if(generation===snap.selectionGeneration)return;generation=snap.selectionGeneration;if(detail?.origin!=='template.density-gate')clearSelection();refreshLinked();notifyLinked();});}
    if(!qs('#morphScope')){const scope=document.createElement('p');scope.id='morphScope';scope.className='morph-scope';scope.setAttribute('aria-label','密度集合与未保存分组');qs('#morphMethod').before(scope);}
    if(!qs('#morphScopeSummary')){const summary=document.createElement('p');summary.id='morphScopeSummary';summary.className='morph-scope-summary';summary.setAttribute('aria-label','当前密度来源与完整集合数量');qs('.morph-leads').before(summary);}
    if(!qs('#morphGroupSources')){const sources=document.createElement('p');sources.id='morphGroupSources';sources.className='morph-group-sources';qs('#morphMethod').before(sources);}
    qs('.morph-method-details summary').textContent='来源、统计与保存说明';
    if(!qs('#morphImpact')){const impact=document.createElement('p');impact.id='morphImpact';impact.className='morph-impact';qs('.morph-actions').after(impact);}
    qs('#morphGroups').innerHTML=G.slots.map(n=>'<section class="morph-group" data-morph-group="'+n+'"><header><button type="button" data-group-select="'+n+'" aria-label="查看 '+n+' 组" aria-pressed="'+(n===6)+'"><b>'+n+'</b><span data-group-count>0搏</span><span data-group-state>空</span></button><button type="button" data-group-move="'+n+'" aria-label="移入 '+n+' 组" disabled>移入</button></header><canvas id="morphSlot'+n+'" data-morph-group-plot="'+n+'" aria-label="'+n+' 组剥离心搏密度"></canvas></section>').join('');
    for(const n of G.slots)qs('#morphSlot'+n).dataset.morphGroupPlot=String(n);
    for(const [id,slot] of [['morphLeadTop','top'],['morphLeadBottom','bottom'],['morphLeadGroups','groups']]){
      const el=qs('#'+id);el.innerHTML=leads.map(l=>'<option value="'+l+'">'+l+'</option>').join('');el.value=view[slot];
      el.onchange=()=>{view[slot]=el.value;clearSelection();closeForm();refresh(true)};
    }
    mountLeadPicker();
    qs('#morphTemplateFamily').innerHTML=['自定义','单发','成对','连续三发','连续多发','房速','室速','二联律','三联律(NNP)','三联律(NPP)','四联律','全部'].map(x=>'<option>'+esc(x)+'</option>').join('');
    qs('#morphTemplateForm').onsubmit=saveTemplate;qs('#morphTemplateCancel').onclick=()=>closeForm(true);
    qs('#morphGroups').onclick=event=>{
      const b=event.target.closest('button');if(!b)return;
      if(b.dataset.groupMove)move(Number(b.dataset.groupMove)).catch(handleError);
      if(b.dataset.groupSelect){clearSelection();activeSlot=Number(b.dataset.groupSelect);if(current)current.viewedScope={kind:'group',slot:activeSlot};controls();notifyLinked();refreshLinked();}
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
      if(state.currentPage!=='edit'||state.editMode!=='cluster'||!qs('#editWorkbench')?.getClientRects().length||event.target.closest('input,select,textarea,[contenteditable="true"]')||document.querySelector('dialog[open]'))return;
      const n=G.shortcut(event);if(n!==null){event.preventDefault();event.stopImmediatePropagation();if(!selection?.samples.length)status('请先在任一左侧密度图框选心搏，再按 '+n+'。');else move(n).catch(handleError);}
      if(event.key==='Escape'&&event.target.closest('.edit-density-panel')){event.preventDefault();event.stopImmediatePropagation();clearSelection();closeForm(true);}
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
  return {refresh,drawAll,captureView,restoreView,resetView,privateSnapshot,subscribeLinked(fn){linkedListeners.add(fn);return()=>linkedListeners.delete(fn)},refreshLinked,canSwitch:()=>!saving};
})();
