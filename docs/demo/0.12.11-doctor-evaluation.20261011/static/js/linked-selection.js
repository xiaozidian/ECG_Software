"use strict";
/* Exact, read-only membership shared by chart views; never a clinical edit set. */
((root) => {
  const scopeFields = ['caseId', 'caseToken', 'analysis_basis', 'analysis_revision', 'beatRevision'];
  function scopeKey(scope) { return scope ? JSON.stringify(scopeFields.map(k => scope[k])) : ''; }
  function integer(value, label) {
    if (!Number.isSafeInteger(value) || value < 0) throw new TypeError(label + ' must be a nonnegative safe integer');
    return value;
  }
  function normalizeScope(value) {
    if (!value || typeof value.caseId !== 'string' || !value.caseId || typeof value.analysis_basis !== 'string' || !value.analysis_basis) throw new TypeError('A complete clinical scope is required');
    return Object.freeze({caseId:value.caseId, caseToken:integer(value.caseToken,'case token'),
      analysis_basis:value.analysis_basis, analysis_revision:integer(value.analysis_revision,'analysis revision'),
      beatRevision:integer(value.beatRevision,'beat revision')});
  }
  function immutable(value, seen=new Set()) {
    if (value === null || ['string','boolean'].includes(typeof value)) return value;
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (!value || typeof value !== 'object' || seen.has(value) || (!Array.isArray(value) && Object.getPrototypeOf(value)!==Object.prototype)) throw new TypeError('Selection metadata must contain only JSON values');
    seen.add(value);
    const result=Array.isArray(value)?value.map(v=>immutable(v,seen)):Object.fromEntries(Object.entries(value).map(([k,v])=>[k,immutable(v,seen)]));
    seen.delete(value);return Object.freeze(result);
  }
  function create({getActiveCase=null, onSubscriberError=null}={}) {
    let scope=null, kind='none', samples=null, focusSample=null, timeBounds=null, sourcePopulation=null, origin=null;
    let selectionGeneration=0, focusGeneration=0, laneSerial=0, notifying=false, pendingNotification=null;
    const subscribers=new Set(), lanes=new Map();
    const rawSnapshot=()=>Object.freeze({scope,kind,samples,focusSample,timeBounds,sourcePopulation,origin,selectionGeneration,focusGeneration});
    function notify(change) {
      pendingNotification={snapshot:rawSnapshot(),event:Object.freeze({change,origin})};
      if(notifying)return;
      notifying=true;
      try {
        while(pendingNotification){
          const batch=pendingNotification;pendingNotification=null;
          for(const fn of [...subscribers]){
            try { fn(batch.snapshot,batch.event); } catch(error) { if(onSubscriberError)onSubscriberError(error);else root.console?.error('Linked chart subscriber failed',error); }
            // A nested change queues the latest snapshot. Never finish sending
            // this superseded batch after consumers have seen the new state.
            if(pendingNotification)break;
          }
        }
      } finally {notifying=false;}
    }
    function abortWhere(test) { for(const [name,entry] of lanes)if(test(name,entry)){entry.controller.abort();lanes.delete(name);} }
    function reset(nextScope, change, nextOrigin) {
      abortWhere(()=>true);scope=nextScope;kind='none';samples=null;focusSample=null;timeBounds=null;sourcePopulation=null;origin=nextOrigin;
      selectionGeneration++;focusGeneration++;notify(change);
    }
    function active(scopeValue) {
      if(!getActiveCase)return true;
      const value=getActiveCase();
      return !!value && value.caseId===scopeValue.caseId && value.caseToken===scopeValue.caseToken;
    }
    function syncActive() {
      if(scope&&!active(scope))reset(null,'scope','case-change');
    }
    function currentExpected(expectedScope) {
      syncActive();
      return !!scope && (!expectedScope || scopeKey(scope)===scopeKey(expectedScope));
    }
    function setScope(value) {
      syncActive();
      if(value===null){reset(null,'scope','case-change');return true;}
      const next=normalizeScope(value);
      if(!active(next))return false;
      if(scopeKey(scope)===scopeKey(next))return true;
      if(scope&&scope.caseId===next.caseId&&scope.caseToken===next.caseToken&&scope.analysis_basis===next.analysis_basis &&
         (next.analysis_revision<scope.analysis_revision||next.beatRevision<scope.beatRevision))return false;
      reset(next,'scope','clinical-basis-change');return true;
    }
    function select(value,{expectedScope=null}={}) {
      if(!currentExpected(expectedScope))return false;
      if(!value||!Array.isArray(value.samples))throw new TypeError('An exact sample array is required');
      const next=Object.freeze([...new Set(value.samples.map(s=>integer(s,'sample')))].sort((a,b)=>a-b));
      let bounds=null;
      if(value.timeBounds!=null){const {start_s,end_s}=value.timeBounds;
        if(!Number.isFinite(start_s)||!Number.isFinite(end_s)||start_s<0||end_s<start_s)throw new TypeError('Invalid half-open time bounds');
        bounds=Object.freeze({start_s,end_s});}
      const population=value.sourcePopulation==null?null:immutable(value.sourcePopulation);
      const focus=value.focusSample==null?null:integer(value.focusSample,'focus sample');
      if(focus!==null&&!next.includes(focus))throw new TypeError('Focus must belong to the exact selected cohort');
      abortWhere(()=>true);kind='samples';samples=next;focusSample=focus;timeBounds=bounds;sourcePopulation=population;origin=String(value.origin||'chart-selection');
      selectionGeneration++;focusGeneration++;notify('selection');return true;
    }
    function focus(sample,{expectedScope=null,origin:nextOrigin='chart-focus'}={}) {
      if(!currentExpected(expectedScope))return false;
      const value=sample==null?null:integer(sample,'focus sample');
      if(value!==null&&kind==='samples'&&!samples.includes(value))return false;
      if(value===focusSample)return true;
      abortWhere((name,entry)=>entry.ticket.focusSensitive);focusSample=value;origin=String(nextOrigin);focusGeneration++;notify('focus');return true;
    }
    function clear({expectedScope=null,origin:nextOrigin='chart-clear'}={}) {
      if(!currentExpected(expectedScope))return false;
      // Even an already-global clear invalidates an outstanding calculation.
      reset(scope,'clear',String(nextOrigin));return true;
    }
    function beginLane(name,viewKey,{focusSensitive=false}={}) {
      syncActive();name=String(name);if(!name)throw new TypeError('A request lane is required');
      const old=lanes.get(name);if(old)old.controller.abort();
      const controller=new AbortController();
      const ticket=Object.freeze({name,viewKey:String(viewKey),scopeKey:scopeKey(scope),selectionGeneration,focusGeneration,focusSensitive:!!focusSensitive,serial:++laneSerial,signal:controller.signal});
      if(!scope)controller.abort();else lanes.set(name,{ticket,controller});
      return ticket;
    }
    function isCurrent(ticket,currentViewKey) {
      syncActive();
      return !!scope&&!!ticket&&!ticket.signal.aborted&&lanes.get(ticket.name)?.ticket===ticket&&ticket.scopeKey===scopeKey(scope)&&ticket.selectionGeneration===selectionGeneration&&(!ticket.focusSensitive||ticket.focusGeneration===focusGeneration)&&(currentViewKey===undefined||ticket.viewKey===String(currentViewKey));
    }
    function cancelLane(name){abortWhere(n=>n===String(name));}
    function cancelPresentationLanes(prefix){const prefixes=Array.isArray(prefix)?prefix:[prefix];abortWhere(name=>prefixes.some(p=>name.startsWith(String(p))));}
    return Object.freeze({setScope,select,focus,clear,beginLane,isCurrent,cancelLane,cancelPresentationLanes,
      snapshot:()=>{syncActive();return rawSnapshot();},
      subscribe:fn=>{if(typeof fn!=='function')throw new TypeError('A listener is required');subscribers.add(fn);return ()=>subscribers.delete(fn);}});
  }
  const api={create,scopeKey,normalizeScope};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(typeof document!=='undefined'){
    root.ECGLinkedSelection=create({getActiveCase:()=>typeof state==='undefined'?null:{caseId:state.caseId,caseToken:state.caseRequestId}});
    if(typeof selectCase==='function'){
      const legacySelect=selectCase;
      selectCase=function(...args){const before=state.caseRequestId,result=legacySelect.apply(this,args);if(state.caseRequestId!==before)root.ECGLinkedSelection.snapshot();return result;};
    }
    if(typeof goPage==='function'){
      const legacyPage=goPage;
      goPage=function(...args){const before=state.currentPage,result=legacyPage.apply(this,args);root.ECGLinkedSelection.snapshot();if(state.currentPage!==before){if(before==='review')root.ECGLinkedSelection.cancelPresentationLanes(['overview.','overview:']);if(before==='edit')root.ECGLinkedSelection.cancelPresentationLanes(['template.','template:']);}return result;};
    }
  }
})(typeof globalThis!=='undefined'?globalThis:this);
