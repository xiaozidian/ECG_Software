"use strict";

/* One command surface for review strips, continuous ECG and template editing. */
const beatEditor=(()=>{
  const E=ECGBeatEngine,esc=escapeHtml;
  let context=null,selected=new Set(),info=null,busy=false,openToken=0,dialog;
  const endpoint=(suffix="")=>"/api/cases/"+encodeURIComponent(context?.caseId||state.caseId)+"/beat-editor"+suffix;
  const request=(suffix,method="GET",body)=>api(endpoint(suffix),{method,...(body?{body:JSON.stringify(body)}:{})});
  const selection=()=>({scope:"samples",samples:[...selected]});
  const button=(label,action,extra="")=>'<button type="button" role="menuitem" data-editor-action="'+action+'" '+extra+'>'+label+"</button>";
  const codeButtons=(codes,neighbor="")=>codes.map(code=>'<button type="button" role="menuitem" data-editor-code="'+code+'" '+(neighbor?'data-editor-neighbor="'+neighbor+'"':"")+'><kbd>'+code+'</kbd><span>'+esc(E.types[code].name)+'</span></button>').join("");
  const mainCodes=["N","S","V","J","G","A","C","F","E","R","W","O","Z","M","H","Y","T","X","OTHER"];
  function renderMenu(){
    const menu=$("#beatRelabelMenu");menu.classList.add("full-beat-menu");
    menu.innerHTML='<header><strong>心搏修订</strong><button type="button" data-editor-action="close" aria-label="关闭心搏菜单">×</button></header>'+
      '<p class="editor-context">'+(context?.anchor?formatElapsedPrecise(context.anchor.time_s)+' · '+esc(context.anchor.class_code||context.anchor.label||""):"此位置无心搏标记")+
      ' · 已选 <b>'+selected.size+'</b> 搏 · 修订 r'+info.revision+'</p>'+
      '<div class="editor-menu-scroll"><div class="editor-types">'+codeButtons(["N","S","V","X"])+'</div>'+
      '<details><summary>更多心搏 / 节律 / 波形标记</summary><div class="editor-types">'+codeButtons(mainCodes.filter(x=>!["N","S","V","X"].includes(x)))+'</div></details>'+
      '<details><summary>起搏 P</summary><div class="editor-types">'+codeButtons(["P","PA","PV","PD","PF"])+'</div></details>'+
      '<details><summary>束支传导阻滞 B</summary><div class="editor-types">'+codeButtons(["B","BL","BR"])+'</div></details>'+
      '<div class="editor-actions">'+button("删除标记 <kbd>D</kbd>","delete")+button("恢复源类型 / 位置","restore")+
      button("手动批量添加 QRS","insert")+button("手动调整 QRS 位置","move")+
      '<details><summary>自动向前 / 向后插入候选</summary><p>参考导联 '+esc(info.settings.lead)+' · 搜索 '+info.settings.search_seconds+' 秒 · 只预览，不直接写入</p>'+
      button("向前搜索","detect-before")+button("向后搜索","detect-after")+'</details>'+
      '<details><summary>修改前一心搏 ‹</summary><div class="editor-types">'+codeButtons(Object.keys(E.types),"previous")+'</div></details>'+
      '<details><summary>修改后一心搏 ›</summary><div class="editor-types">'+codeButtons(Object.keys(E.types),"next")+'</div></details>'+
      button("设为最长 RR 报告图条 <kbd>L</kbd>","longest")+
      '<div class="editor-selection-tools">'+button("全选当前集合","all")+button("当前页全选 <kbd>K</kbd>","page")+button("反选当前集合","invert")+button("当前页反选 <kbd>I</kbd>","invert-page")+button("清除选择","clear")+'</div>'+
      button("撤销最近修订","undo",info.can_undo?"":"disabled")+button("重做","redo",info.can_redo?"":"disabled")+
      button("设置选项","settings")+'</div></div><footer>源记录只读 · 修订后重算 · 可撤销<br>房颤 / 房扑为人工逐搏节律标记；P/T 波不计入心搏。</footer>';
    menu.querySelectorAll("[data-editor-code]").forEach(b=>{b.disabled=!selected.size});
    ["delete","restore","longest","move"].forEach(a=>{menu.querySelector('[data-editor-action="'+a+'"]').disabled=!selected.size||(a==="move"&&selected.size!==1)});
    menu.hidden=false;positionBeatRelabelMenu(menu,context.x,context.y);
    try{if(!menu.matches(":popover-open"))menu.showPopover()}catch(_){}
  }
  function syncSelection(){
    if(context.surface==="edit"){state.editSelectedSamples=new Set(selected);state.editSelectedSample=context.anchor?.sample_index??null}
    refreshBeatOverrideViews();
  }
  async function open(event,canvas,waveform,surface="review",keyboard=false){
    event.preventDefault?.();if(!state.caseId||!waveform)return;
    const token=++openToken,rect=canvas.getBoundingClientRect(),x=keyboard?rect.left+rect.width/2:event.clientX,y=keyboard?rect.top+40:event.clientY;
    const anchor=nearestBeatForRelabel(canvas,waveform,x,surface,keyboard?Infinity:44);
    const g=surface==="review"?{l:0,w:rect.width}:editWaveGeometry(rect.width,rect.height);
    const time=waveform.start_s+Math.max(0,Math.min(1,(x-rect.left-g.l)/g.w))*waveform.duration_s;
    const same=context?.caseId===state.caseId&&context.surface===surface;
    context={caseId:state.caseId,surface,anchor,time,x,y,canvas,waveform,strip:!!canvas.closest("[data-scatter-sample]")};
    selected=surface==="edit"?new Set(state.editSelectedSamples):same?selected:new Set();
    if(anchor&&!selected.has(anchor.sample_index))selected=new Set([anchor.sample_index]);
    if(!anchor)selected.clear();
    state.beatRelabelTarget=anchor?{...anchor,caseId:state.caseId,surface}:null;
    syncSelection();
    try{const result=await request("");if(token!==openToken||context.caseId!==state.caseId)return;info=result;context.revision=result.revision;renderMenu();$("#beatRelabelMenu [data-editor-code]:not(:disabled)")?.focus({preventScroll:true})}catch(error){handleError(error)}
  }
  function close(){openToken++;closeBeatRelabelMenu()}
  function showDialog(title,content,accept,acceptLabel="预览修改"){
    close();dialog.innerHTML='<form method="dialog"><header><h2>'+esc(title)+'</h2><button type="button" data-dialog-close aria-label="关闭">×</button></header><div class="editor-dialog-body">'+content+'</div><p class="editor-error" role="alert"></p><footer><button type="button" data-dialog-close class="button secondary">取消</button><button type="submit" class="button primary">'+esc(acceptLabel)+'</button></footer></form>';
    dialog.querySelectorAll("[data-dialog-close]").forEach(b=>b.onclick=()=>dialog.close());
    dialog.querySelector("form").onsubmit=async event=>{
      event.preventDefault();const submit=dialog.querySelector('[type="submit"]');submit.disabled=true;
      try{await accept(new FormData(event.target))}catch(error){dialog.querySelector(".editor-error").textContent=error.message}finally{submit.disabled=false}
    };
    if(!dialog.open)dialog.showModal();
  }
  function contextOK(){if(!context||context.caseId!==state.caseId)throw Error("病例已切换，请重新选择心搏");if(!clinicalWorkflow.writable())throw Error("当前服务为只读")}
  async function afterCommit(value,operation){
    info=value;dialog.close();close();
    selected.clear();state.editSelectedSamples.clear();state.editSelectedSample=null;
    state.scatterStripCache.clear();state.reportComposer=null;
    await loadCase();
    if(state.currentPage==="edit")await loadEdit();
    if(state.currentPage==="review"){clearScatterSelection();await loadScatter()}
    await clinicalWorkflow.refresh(state.caseId);
    toast("已保存修订 r"+value.revision+" · RR / HRV / 候选已更新；可撤销", "success",5000);
    updateStatus(value);
  }
  async function commit(payload){
    contextOK();const caseId=context.caseId;
    const value=await request("","PUT",{...payload,confirmed:true});
    if(caseId!==state.caseId)return;
    await afterCommit(value,payload.operation);
  }
  function changeTable(preview){
    const a=preview.before,b=preview.after,fields=[["有效心搏",a.metrics.valid_beats,b.metrics.valid_beats],["NN 间期数",a.hrv.nn_count??0,b.hrv.nn_count??0],["最长 RR (ms)",a.metrics.longest_rr_ms,b.metrics.longest_rr_ms],["非心搏标记",a.markers.length,b.markers.length]];
    return '<table><thead><tr><th>重算项目</th><th>修改前</th><th>修改后</th></tr></thead><tbody>'+fields.map(([l,x,y])=>"<tr><th>"+l+"</th><td>"+(x??"—")+"</td><td>"+(y??"—")+"</td></tr>").join("")+"</tbody></table>";
  }
  async function perform(operation,extra={},quick=false){
    contextOK();if(busy)return;busy=true;
    try{
      const current=await request("");
      if(info&&context.revision!==undefined&&current.revision!==context.revision&&!["undo","redo"].includes(operation))throw Error("病例修订版本已变化，请重新打开菜单核对");
      info=current;
      $("#beatRelabelMenu").setAttribute("aria-busy","true");
      const payload={operation,selection:selection(),revision:info.revision,...extra};
      if(["undo","redo"].includes(operation)){await commit(payload);return}
      const preview=await request("/preview","POST",payload);
      if(quick&&selected.size===1&&["N","S","V","X"].includes(extra.class_code)){await commit(payload);return}
      let warning="将影响 "+preview.affected+" 个标记。修订后需重新确认相关复核环节；源 DATA / EBI 不会改写。";
      if(E.types[extra.class_code]?.kind==="nonbeat")warning+=" 该类型不是 QRS，原标记将从心搏和 NN 统计中排除。";
      if(E.types[extra.class_code]?.kind==="rhythm")warning+=" 这是医生指定的逐搏节律属性，不是自动房颤 / 房扑识别或完整发作负荷分析。";
      if(operation==="longest")warning+=" 只指定报告图条，不覆盖数学上最长 RR 的计算结果。";
      const positions=(extra.positions||[...selected]).slice().sort((a,b)=>a-b);
      let targets=positions.slice(0,8).map(s=>formatElapsedPrecise(s/200)).join("、")+(positions.length>8?" …":"");
      if(operation==="move")targets+=" → "+formatElapsedPrecise(extra.target_sample/200);
      if(operation==="settings")targets=Object.entries(extra.settings||{}).map(([key,value])=>key+"="+value).join("；");
      showDialog("确认"+({relabel:"改型 · "+(E.types[extra.class_code]?.name||""),delete:"删除标记",restore:"恢复源标记",insert:"补标 QRS",move:"移动 QRS",longest:"报告 RR 图条",settings:"分析设置"}[operation]||"修订"),
        "<p>"+esc(warning)+"</p><p><strong>本次目标：</strong>"+esc(targets)+"</p>"+changeTable(preview),()=>commit(payload),"确认保存修订");
    }finally{busy=false;$("#beatRelabelMenu").removeAttribute("aria-busy")}
  }
  async function quickEdit(code,samples=[...state.editSelectedSamples]){
    if(!samples.length)return toast("请先选中心搏","error");
    context={caseId:state.caseId,surface:state.currentPage==="edit"?"edit":"review",anchor:null,time:state.editStart,x:0,y:0,canvas:$("#editWaveformCanvas"),waveform:state.editWaveform};
    selected=new Set(samples);return perform("relabel",{class_code:code},true);
  }
  async function universe(page=false){
    if(page){
      if(context.strip)return [...document.querySelectorAll("[data-scatter-sample]")].filter(el=>{const a=el.getBoundingClientRect(),b=$("#scatterSelectionList").getBoundingClientRect();return a.bottom>b.top&&a.top<b.bottom}).map(el=>Number(el.dataset.scatterSample));
      if(context.canvas?.closest("#editLibraryMatrix"))return [...document.querySelectorAll("#editLibraryMatrix [data-edit-sample]")].map(el=>Number(el.dataset.editSample));
      if(context.canvas?.closest("#editTemplateGallery"))return [...document.querySelectorAll("#editTemplateGallery [data-edit-sample]")].map(el=>Number(el.dataset.editSample));
      return (context.waveform?.beats||[]).map(r=>r.sample_index);
    }
    if(context.strip&&state.scatterSelectedSamples.length)return state.scatterSelectedSamples.slice();
    const feed=await request("/beats");let rows=feed.items.concat(feed.markers);
    if(context.surface==="edit"){
      const group=({"source-N":1,"source-S":2,"source-V":3,"source-X":34})[state.editSelectedClass];
      if(group)rows=rows.filter(r=>r.group===group);
      else{const template=state.editTemplates.find(r=>"custom-"+r.id===state.editSelectedClass);if(template){const set=new Set(template.sample_indices);rows=rows.filter(r=>set.has(r.sample_index))}}
    }
    return rows.map(r=>r.sample_index);
  }
  async function neighbor(direction,code){
    const feed=await request("/beats"),index=feed.items.findIndex(r=>r.sample_index===context.anchor?.sample_index),target=feed.items[index+(direction==="previous"?-1:1)];
    if(index<0||!target)throw Error("此方向没有相邻心搏");
    selected=new Set([target.sample_index]);context.anchor=target;syncSelection();await perform("relabel",{class_code:code});
  }
  function manual(op){
    const time=op==="move"?(context.anchor?.time_s??context.time):context.time;
    showDialog(op==="move"?"调整 QRS 位置":"手动批量添加 QRS",
      '<p>输入从记录开始计的秒数，200 Hz 下按 5 ms 采样点定位；补标默认为未分类。目标位置必须在记录内，且距其他 QRS 至少 100 ms（软件编辑保护）。</p>'+
      (op==="move"?'<label>目标时间（秒）<input name="time" type="number" step="0.005" min="0" value="'+(Math.round(time*200)/200).toFixed(3)+'" required></label><div class="editor-nudges"><button type="button" data-nudge="-0.005">← 5 ms</button><button type="button" data-nudge="0.005">5 ms →</button></div>':
      '<label>QRS 位置（秒，以逗号、空格或换行分隔；最多 500 个）<textarea name="times" rows="4" required>'+Math.max(0,Math.round(time*200)/200).toFixed(3)+'</textarea></label><label>新心搏类型<select name="type">'+Object.values(E.types).filter(t=>t.kind==="beat").map(t=>'<option value="'+t.code+'" '+(t.code==="OTHER"?"selected":"")+'>'+t.code+" · "+t.name+"</option>").join("")+'</select></label>'),
      data=>{
        if(op==="move")return perform("move",{target_sample:Math.round(Number(data.get("time"))*200)});
        const values=String(data.get("times")).trim().split(/[\s,，;；]+/).map(Number);if(!values.length||values.some(v=>!Number.isFinite(v)))throw Error("请输入有效秒数");
        return perform("insert",{positions:values.map(v=>Math.round(v*200)),class_code:data.get("type")});
      });
    dialog.querySelectorAll("[data-nudge]").forEach(b=>b.onclick=()=>{const input=dialog.querySelector('[name="time"]');input.value=(Number(input.value)+Number(b.dataset.nudge)).toFixed(3)});
  }
  function settingsDialog(){
    const labels={refractory_ms:"候选排重间隔（ms，100–500）",sensitivity:"能量阈值系数（1–12；越大越保守）",search_seconds:"前后搜索时长（秒，1–60）",brady:"慢心率候选阈值（bpm，20–100）",tachy:"快心率候选阈值（bpm，80–250）",pause:"长 RR 阈值（秒，1.5–10）",nn_min:"NN 纳入下限（ms，250–1000）",nn_max:"NN 纳入上限（ms，1000–5000）"};
    showDialog("编辑与分析设置",'<p>仅作用于当前病例。候选阈值不是疾病诊断标准；排重间隔是算法参数。修改后会重新计算并撤回复核确认。</p><div class="editor-settings"><label>QRS 搜索导联<select name="lead">'+ALL_LEADS.map(l=>'<option '+(l===info.settings.lead?"selected":"")+'>'+l+'</option>').join("")+'</select></label>'+Object.entries(labels).map(([key,label])=>'<label>'+label+'<input name="'+key+'" type="number" step="any" required value="'+info.settings[key]+'"></label>').join("")+'</div>',
      data=>{const opts={};for(const key of Object.keys(E.defaults))opts[key]=key==="lead"?data.get(key):Number(data.get(key));E.settings(opts);return perform("settings",{settings:opts})});
  }
  async function detect(direction){
    info=await request("");const total=state.caseData.technical.duration_seconds_raw,t=context.anchor?.time_s??context.time;
    const start=Math.max(0,direction==="before"?t-info.settings.search_seconds:t),seconds=Math.min(info.settings.search_seconds,total-start,direction==="before"?t-start:Infinity);
    if(seconds<1)throw Error("此方向剩余记录不足 1 秒");
    const result=await request("/preview","POST",{operation:"detect",revision:info.revision,start_s:start,duration_s:seconds});
    const wave=await api("/api/cases/"+context.caseId+"/waveform?start="+start+"&duration="+seconds+"&leads="+info.settings.lead+"&filter=raw&max_points=12000");
    const candidates=result.candidates;
    showDialog("漏标 QRS 候选预览",'<p>'+esc(result.method)+'</p><p>搜索 '+formatElapsedPrecise(start)+'—'+formatElapsedPrecise(start+seconds)+' · '+esc(info.settings.lead)+' · <b>'+candidates.length+'</b> 个候选。默认不勾选；核对原始波形后逐个选择。</p><canvas id="qrsCandidatePreview" height="190" aria-label="原始波形与 QRS 候选位置"></canvas><div class="qrs-candidate-list">'+
      (candidates.map(r=>'<label><input type="checkbox" name="candidates" value="'+r.sample_index+'">'+formatElapsedPrecise(r.time_s)+'<small>阈值比 '+r.score+'（非置信概率）</small></label>').join("")||"<p>未发现候选。可调整导联／阈值，或手动补标；未检测到不代表无漏搏。</p>")+'</div>',
      async data=>{if(info.revision!==result.revision)throw Error("版本已变化，请重新检测");const positions=data.getAll("candidates").map(Number);if(!positions.length)throw Error("请核对并选择至少一个候选");await perform("insert",{positions,class_code:"OTHER",revision:result.revision})});
    const canvas=$("#qrsCandidatePreview"),box=canvas.getBoundingClientRect();canvas.width=Math.max(500,Math.round(box.width*devicePixelRatio));canvas.height=190*devicePixelRatio;
    const ctx=canvas.getContext("2d");ctx.scale(devicePixelRatio,devicePixelRatio);const w=canvas.width/devicePixelRatio,h=190,values=wave.leads[info.settings.lead],low=Math.min(...values),high=Math.max(...values),span=Math.max(1,high-low);
    ctx.fillStyle="#f8fbfb";ctx.fillRect(0,0,w,h);ctx.strokeStyle="#263e48";ctx.beginPath();values.forEach((v,i)=>{const x=i/Math.max(1,values.length-1)*w,y=170-(v-low)/span*150;i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();
    candidates.forEach((r,i)=>{const x=(r.time_s-wave.start_s)/wave.duration_s*w;ctx.strokeStyle="#ca6919";ctx.beginPath();ctx.moveTo(x,5);ctx.lineTo(x,h);ctx.stroke();ctx.fillStyle="#9d4d11";ctx.fillText(String(i+1),x+2,12)});
  }
  function updateStatus(value){
    document.querySelectorAll("[data-editor-status]").forEach(el=>{el.textContent=value?"修订 r"+value.revision:"心搏修订";el.title="右击波形或按 Shift+F10 编辑；撤销 / 重做均保留审计"});
  }
  async function action(name){
    if(name==="close")return close();
    if(name==="clear"){selected.clear();syncSelection();return renderMenu()}
    if(["all","page","invert","invert-page"].includes(name)){const universeSamples=await universe(name.includes("page"));selected=new Set(name.startsWith("invert")?universeSamples.filter(s=>!selected.has(s)):universeSamples);syncSelection();return renderMenu()}
    if(name==="insert"||name==="move")return manual(name);
    if(name==="settings")return settingsDialog();
    if(name.startsWith("detect-"))return detect(name.slice(7));
    return perform(name);
  }
  function bind(){
    dialog=document.createElement("dialog");dialog.id="beatEditorDialog";dialog.className="beat-editor-dialog";document.body.appendChild(dialog);
    $("#beatRelabelMenu").addEventListener("click",event=>{
      const b=event.target.closest("button");if(!b||b.disabled)return;
      const task=b.dataset.editorCode?(b.dataset.editorNeighbor?neighbor(b.dataset.editorNeighbor,b.dataset.editorCode):perform("relabel",{class_code:b.dataset.editorCode})):b.dataset.editorAction?action(b.dataset.editorAction):null;
      Promise.resolve(task).catch(handleError);
    });
    // Dialog/menu keystrokes must not leak to global navigation or beat shortcuts.
    document.addEventListener("keydown",event=>{
      if(dialog.open){event.stopImmediatePropagation();return}
      const menu=$("#beatRelabelMenu");
      if(!menu.hidden&&context){
        if(event.key==="Escape"){event.preventDefault();event.stopImmediatePropagation();close();return}
        if(!event.ctrlKey&&!event.metaKey&&!event.altKey&&({D:"delete",K:"page",I:"invert-page",L:"longest"})[event.key.toUpperCase()]){event.preventDefault();event.stopImmediatePropagation();action(({D:"delete",K:"page",I:"invert-page",L:"longest"})[event.key.toUpperCase()]).catch(handleError);return}
        if((event.ctrlKey||event.metaKey)&&["a","i"].includes(event.key.toLowerCase())){event.preventDefault();event.stopImmediatePropagation();action(event.key.toLowerCase()==="a"?"all":"invert").catch(handleError);return}
        if(!event.ctrlKey&&!event.metaKey&&!event.altKey&&E.types[event.key.toUpperCase()]){
          event.preventDefault();event.stopImmediatePropagation();perform("relabel",{class_code:event.key.toUpperCase()}).catch(handleError);return;
        }
        if(["ArrowDown","ArrowUp","Home","End"].includes(event.key)){event.preventDefault();event.stopImmediatePropagation();const buttons=[...menu.querySelectorAll("button:not(:disabled),summary")].filter(el=>el.getClientRects().length),i=buttons.indexOf(document.activeElement);buttons[event.key==="Home"?0:event.key==="End"?buttons.length-1:(i+(event.key==="ArrowDown"?1:-1)+buttons.length)%buttons.length]?.focus();return}
      }
      if(["INPUT","TEXTAREA","SELECT"].includes(document.activeElement.tagName))return;
      if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==="z"&&["review","edit"].includes(state.currentPage)){
        event.preventDefault();event.stopImmediatePropagation();context={caseId:state.caseId,surface:state.currentPage};perform(event.shiftKey?"redo":"undo").catch(handleError);
      }
    },true);
    document.addEventListener("contextmenu",event=>{
      const card=event.target.closest("[data-edit-sample]");if(!card)return;
      const item=state.editTemplateStrips.find(r=>r.sample_index===Number(card.dataset.editSample)),canvas=card.querySelector("canvas");if(!item||!canvas)return;
      event.preventDefault();event.stopImmediatePropagation();open(event,canvas,{...item,beats:[item]},"edit",true);
    },true);
    ["#waveformCanvas","#editWaveformCanvas","#editLibraryWaveformCanvas"].forEach(id=>{
      const canvas=$(id);if(!canvas)return;const bar=document.createElement("div");bar.className="beat-edit-history";
      bar.innerHTML='<span data-editor-status>心搏修订</span><button type="button" data-history="undo" title="⌘ / Ctrl+Z">撤销</button><button type="button" data-history="redo" title="⌘ / Ctrl+Shift+Z">重做</button>';
      canvas.parentElement.appendChild(bar);bar.setAttribute("aria-label","心搏修订历史");bar.querySelectorAll("button").forEach(b=>b.onclick=()=>{context={caseId:state.caseId,surface:id==="#waveformCanvas"?"review":"edit"};perform(b.dataset.history).catch(handleError)});
    });
  }
  document.addEventListener("DOMContentLoaded",bind);
  return {open,quickEdit,invalidate(){openToken++},restore:()=>{context={caseId:state.caseId,surface:"edit"};selected=new Set(state.editSelectedSamples);return perform("restore")},selected:sample=>context?.caseId===state.caseId&&context.surface==="review"&&selected.has(sample)};
})();
