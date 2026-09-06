"use strict";

// Physician checkpoints are persistent; opening a page never marks it reviewed.
const clinicalWorkflow = (() => {
  const tasks = {
    review: "先核对信号质量、导联和关键时段，再进入模板编辑。",
    edit: "先筛选类别，再选中心搏改型；分型模板与单搏改型是两种不同操作。",
    trends: "核对统计范围、NN 选择和源报告差异；按修订位置及严格连续 N-N 重算，短记录指标仍有限制。",
    stt: "回看原始波形并记录判断依据；未经幅值标定，不输出诊断性 ST 幅值。",
    events: "回看候选波形，保留必要的报告证据或排除；候选不等于诊断。",
    report: "核对复核记录、证据与结论，保存后审核；修改后需重新审核。",
  };
  const labels = {retained:"保留为证据",excluded:"已排除",pending:"待复核"};
  let data = null, request = 0, context = null, dialogContext = null, eventOffset = 0;
  const writable = () => !state.demoReadonly || Boolean(window.__CARDIOINSIGHT_UPLOADED_CASE__);
  const pending = () => CASE_WORKFLOW_STEPS.filter(step => step.page !== "report" && data?.steps?.[step.page]?.status !== "done");
  const receive = value => {data=value||null;render();};
  async function refresh(caseId=state.caseId) {
    if(!caseId)return;
    const token=++request, value=await api(`/api/cases/${caseId}/review-workflow`);
    if(token!==request||caseId!==state.caseId)return;
    data=value;
    const current=state.cases.find(item=>item.case_id===caseId);
    if(current)current.review_workflow=value;
    if(state.report){state.report.status=value.report_status;state.report.version=value.report_version;}
    render();renderWorklist();
    if(state.currentPage==="events"&&state.events)renderEvents();
    if(state.currentPage==="report")renderReport();
  }
  function render() {
    const bar=$("#caseWorkflow");
    if(!bar)return;
    const visible=Boolean(state.caseId&&CASE_WORKFLOW_PAGES.has(state.currentPage));
    bar.hidden=!visible;document.body.classList.toggle("case-workflow-visible",visible);
    if(!visible)return;
    const m=state.caseData?.metadata||{};
    $("#workflowCaseLabel").textContent=`${m.name||"病例"} · ${state.caseId}`;
    $("#workflowCaseLabel").title=`${m.sex||""} ${m.age??"—"} 岁 · ${m.start_time||""} · ${m.duration_text||""}`;
    $("#workflowProgressLabel").textContent=data?`${5-pending().length} / 5 环节已确认 · ${data.report_status==="reviewed"?"报告已审核":"报告待审核"}`:"正在读取复核记录…";
    $$("[data-workflow-page]").forEach(button=>{
      const page=button.dataset.workflowPage,done=page==="report"?data?.report_status==="reviewed":data?.steps?.[page]?.status==="done",stale=data?.steps?.[page]?.status==="stale";
      button.classList.toggle("current",page===state.currentPage);
      button.classList.toggle("visited",done);button.classList.toggle("needs-review",stale);
      button.setAttribute("aria-current",page===state.currentPage?"step":"false");
      $("small",button).textContent=done?"已确认":stale?"修改后待复核":"待复核";
      button.title=`${button.textContent.trim()} · 点击仅切换页面，不确认复核`;
    });
    $$("[data-workflow-nav]").forEach(button=>button.classList.toggle("workflow-visited",data?.steps?.[button.dataset.workflowNav]?.status==="done"));
    const next=$("#workflowNext"),isReport=state.currentPage==="report";
    next.textContent=isReport?(data?.report_status==="reviewed"?"完成，返回工作台":"查看审核前检查"):data?.steps?.[state.currentPage]?.status==="done"?"已确认 · 继续 →":"确认本步并继续";
    next.disabled=!data||(!writable()&&!isReport);
    $("#workflowTaskHint").textContent=tasks[state.currentPage];
    $("#workflowBrowseNext").hidden=isReport;
    const back=$("#workflowReturn");
    back.hidden=!(context&&context.caseId===state.caseId&&state.currentPage==="review");
    if(!back.hidden)back.textContent=`← 返回${CASE_WORKFLOW_STEPS.find(x=>x.page===context.page)?.label||"来源"}`;
    renderPreflight();
  }
  function browse() {
    const i=CASE_WORKFLOW_STEPS.findIndex(step=>step.page===state.currentPage);
    goPage(CASE_WORKFLOW_STEPS[i+1]?.page||"dashboard");
  }
  function confirmStep() {
    if(state.currentPage==="report"){if(data?.report_status==="reviewed"){goPage("dashboard");return;}$("#reportPreflight")?.scrollIntoView({block:"nearest"});$("#reportPreflight")?.focus();return;}
    if(data?.steps?.[state.currentPage]?.status==="done"){browse();return;}
    if(!data)return;
    dialogContext={caseId:state.caseId,step:state.currentPage,revision:data.revision};
    $("#workflowConfirmTitle").textContent=`确认${CASE_WORKFLOW_STEPS.find(x=>x.page===state.currentPage)?.label}`;
    $("#workflowConfirmDescription").textContent=tasks[state.currentPage];
    $("#workflowLimitNotice").textContent=state.currentPage==="stt"?"当前为人工复核工具，未验证幅值校准。无法评估时请在备注说明，确认的是复核记录，不是自动诊断。":state.currentPage==="events"?"保留表示选作报告证据，不表示确诊；未处理的源候选仍保留其待复核属性。":"导航记录不会替代医生确认。后续更改相关数据时，本环节将提示重新复核。";
    $("#workflowNote").value=data.steps?.[state.currentPage]?.note||"";
    $("#workflowConfirmed").checked=false;$("#workflowConfirmError").textContent="";
    $("#workflowConfirmDialog").showModal();
  }
  async function submit(event) {
    event.preventDefault();
    const target=dialogContext,button=$("#workflowConfirmSubmit");
    if(!target||target.caseId!==state.caseId)return;
    button.disabled=true;
    try{
      const value=await api(`/api/cases/${target.caseId}/review-workflow`,{method:"PUT",body:JSON.stringify({step:target.step,revision:target.revision,confirmed:$("#workflowConfirmed").checked,note:$("#workflowNote").value})});
      if(target.caseId!==state.caseId)return;
      receive(value);$("#workflowConfirmDialog").close();browse();toast("复核确认已保存");
    }catch(error){$("#workflowConfirmError").textContent=error.message;await refresh().catch(()=>{});}
    finally{button.disabled=false;}
  }
  function renderPreflight() {
    const panel=$("#reportPreflight");if(!panel)return;
    const retained=Object.values(data?.events||{}).filter(x=>x.status==="retained");
    panel.innerHTML=`<h2>审核前检查</h2><p>${pending().length?`尚有 ${pending().length} 个环节未确认`:"各环节已确认，请核对结论并保存"}</p><div class="preflight-steps">${CASE_WORKFLOW_STEPS.filter(x=>x.page!=="report").map(x=>`<button type="button" data-clinical-step="${x.page}"><span>${data?.steps?.[x.page]?.status==="done"?"✓":"○"}</span>${x.label}<small>${data?.steps?.[x.page]?.status==="stale"?"需重核":data?.steps?.[x.page]?.status==="done"?"已确认":"待确认"}</small></button>`).join("")}</div><p class="workflow-limit">RR、HRV 与候选使用当前修订；源报告摘要不改写。房颤/房扑标签是医生逐搏标记，不是自动诊断或发作负荷。请核对结论。</p><h3>医生保留的证据 · ${retained.length}</h3><div class="evidence-list">${retained.map(x=>`<button type="button" data-jump-time="${x.sample_index/200}">${escapeHtml(x.type)} · ${formatElapsed(x.sample_index/200)} ↗</button>`).join("")||"<p>尚未保留事件证据，可到事件复核中选择。</p>"}</div><small>${writable()?(state.demoReadonly?"演示修改仅存此浏览器":"确认与修改写入本地审计"):"当前服务为只读"}</small>`;
    const approve=$("#approveReport");
    if(approve&&writable()){
      approve.disabled=pending().length>0||state.reportDirty||!$("#conclusionEditor")?.value.trim();
      approve.title=pending().length?"请先完成上方复核环节":state.reportDirty?"请先保存草稿":"审核当前已保存版本";
    }
    const stats=$("#reportProvenance");
    if(stats)stats.dataset.overrideCount=String(state.editBeatOverrides.size);
  }
  function decision(item){return data?.events?.[`${item.type}:${item.sample_index}`]?.status||"pending";}
  function eventCell(item) {
    const key=`${item.type}:${item.sample_index}`,status=decision(item);
    return `<select data-event-decision="${key}" aria-label="${formatElapsed(item.time_s)} ${escapeHtml(item.label)}的复核处理" ${writable()?"":"disabled"}>${Object.entries(labels).map(([value,label])=>`<option value="${value}" ${value===status?"selected":""}>${label}</option>`).join("")}</select>`;
  }
  async function setEvents(items,status) {
    const caseId=state.caseId;
    const result=await api(`/api/cases/${caseId}/event-reviews`,{method:"PUT",body:JSON.stringify({items:items.map(({sample_index,type})=>({sample_index,type})),status})});
    if(caseId!==state.caseId)return;
    receive(result);state.reportComposer=null;renderEvents();toast(`已处理 ${items.length} 项：${labels[status]}`);
  }
  function sourceJump(time) {
    if(state.currentPage!=="review"&&CASE_WORKFLOW_PAGES.has(state.currentPage))context={caseId:state.caseId,page:state.currentPage,scroll:window.scrollY,time};
  }
  function allowLeave() {
    if(!state.reportDirty)return true;
    if(!window.confirm("报告有未保存修改。离开会丢弃这些修改，是否继续？"))return false;
    state.reportDirty=false;state.reportComposition=normalizedReportComposition(state.report?.composition);return true;
  }
  function bind(){
    const panel=document.createElement("article");panel.id="reportPreflight";panel.className="card report-preflight";panel.tabIndex=-1;
    $(".report-summary-rail")?.prepend(panel);
    $("#workflowBrowseNext").addEventListener("click",browse);
    $("#workflowReturn").addEventListener("click",()=>{const origin=context;if(!origin)return;goPage(origin.page);requestAnimationFrame(()=>window.scrollTo(0,origin.scroll));context=null;render();});
    $("#workflowConfirmForm").addEventListener("submit",submit);
    $$("[data-close-workflow]").forEach(button=>button.addEventListener("click",()=>$("#workflowConfirmDialog").close()));
    document.addEventListener("click",event=>{const button=event.target.closest("[data-clinical-step]");if(button)goPage(button.dataset.clinicalStep);});
    $("#eventTableBody").addEventListener("change",event=>{const select=event.target.closest("[data-event-decision]");if(!select)return;const [type,sample]=select.dataset.eventDecision.split(":");select.disabled=true;setEvents([{type,sample_index:Number(sample)}],select.value).catch(error=>{handleError(error);renderEvents();});});
    const pager=document.createElement("footer");pager.className="clinical-event-pager";
    pager.innerHTML='<button type="button" id="eventsPrev" class="button secondary">← 上一页</button><span id="eventsPageLabel"></span><button type="button" id="eventsNext" class="button secondary">下一页 →</button>';
    $("#eventTableBody").closest("article").append(pager);
    $("#eventsPrev").addEventListener("click",()=>{eventOffset=Math.max(0,eventOffset-100);loadEvents().catch(handleError);});
    $("#eventsNext").addEventListener("click",()=>{eventOffset+=100;loadEvents().catch(handleError);});
    ["#editWaveCanvasWrap",".edit-library-wave-wrap"].forEach(selector=>{
      const wrap=$(selector);if(!wrap)return;
      const toolbar=document.createElement("div");toolbar.className="clinical-beat-toolbar";toolbar.setAttribute("role","toolbar");toolbar.setAttribute("aria-label","选中心搏改型");
      toolbar.innerHTML='<span>选中心搏后改型</span>'+Object.values(EDIT_BEAT_TYPES).map(type=>`<button type="button" data-clinical-beat="${type.code}" title="${type.name}（${type.code}）">${type.code} <small>${type.name}</small></button>`).join("");
      toolbar.addEventListener("click",event=>{const button=event.target.closest("[data-clinical-beat]");if(button)applyEditBeatType(button.dataset.clinicalBeat).catch(handleError);});
      wrap.prepend(toolbar);
    });
    const strips=$("#scatterSelectionList");
    const menu=event=>{
      const card=event.target.closest("[data-scatter-sample]");if(!card)return;
      const strip=state.scatterStripCache.get(Number(card.dataset.scatterSample));if(!strip)return;
      event.preventDefault();const canvas=$("canvas",card),r=canvas.getBoundingClientRect();
      // A strip represents its anchor beat, not an adjacent beat under the cursor.
      openBeatRelabelMenu({clientX:event.clientX||r.left+r.width/2,clientY:event.clientY||r.top+25},canvas,{start_s:strip.time_s-2,duration_s:4,beats:[strip]},"review",true);
    };
    strips.addEventListener("contextmenu",menu);
    strips.addEventListener("keydown",event=>{if(event.key==="ContextMenu"||(event.shiftKey&&event.key==="F10"))menu(event);});
    window.addEventListener("beforeunload",event=>{if(state.reportDirty){event.preventDefault();event.returnValue="";}});
    $("#conclusionEditor").addEventListener("input",renderPreflight);
    if(state.demoReadonly&&writable()){
      ["saveReport","returnReport","approveReport"].forEach(id=>{const button=$("#"+id);button.hidden=false;button.disabled=false;});
      $("#conclusionEditor").readOnly=false;
      $("#conclusionEditor").closest("article").querySelector(".report-panel-heading small").textContent="演示草稿仅保存于当前浏览器，不上传";
    }
  }
  document.addEventListener("DOMContentLoaded",bind);
  return {render,receive,refresh,confirmStep,allowLeave,sourceJump,eventCell,decision,writable,
    get offset(){return eventOffset;},resetEvents(){eventOffset=0;},
    updatedEvents(){const e=state.events;if(!e)return;$("#eventsPrev").disabled=eventOffset===0;$("#eventsNext").disabled=eventOffset+e.items.length>=e.total;$("#eventsPageLabel").textContent=`当前 ${e.total?eventOffset+1:0}–${eventOffset+e.items.length} / ${fmtNumber(e.total)} 项 · 候选基于当前修订`;},
    reset(){data=null;context=null;eventOffset=0;request++;},
    retained(){return Object.values(data?.events||{}).filter(x=>x.status==="retained");},
    readiness(){return pending().length===0;},
  };
})();
