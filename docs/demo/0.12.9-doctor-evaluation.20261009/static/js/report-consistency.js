"use strict";
// An observed revision is not permission to overwrite the draft based on an older one.
(() => {
  const sameBase=(a,b)=>Boolean(a&&b&&a.version===b.version&&
    (a.review_revision===undefined||b.review_revision===undefined||a.review_revision===b.review_revision));
  const content=(conclusion,composition)=>JSON.stringify({conclusion,composition});
  const canApprove=(state,conclusion,ready,writable)=>Boolean(writable&&ready&&state.report&&
    !state.reportDirty&&!state.reportStale&&!state.reportSaving&&!state.reportEvidenceLoading&&!state.reportEvidenceError&&
    !(state.reportCategoryPending||[]).length&&
    !(state.reportComposition?.diagnosis_blocks||[]).some(block=>block.needs_review)&&String(conclusion??'').trim());
  function receive(state,remote){
    if((state.reportDirty||state.reportSaving)&&state.report&&!sameBase(state.report,remote)){
      state.reportStale=true;return false;
    }
    if(!state.reportDirty&&!state.reportSaving){state.report=remote;state.reportStale=false;return true;}
    return false;
  }
  globalThis.ECGReportConsistency={sameBase,content,receive,canApprove};
})();
