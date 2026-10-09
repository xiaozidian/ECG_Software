"use strict";
/* In-flight read ownership. No completed-result cache and no write deduplication. */
globalThis.ECGReadRequests=(()=>{
  const cancelled=()=>Object.assign(new Error('读取已取消'),{name:'AbortError'});
  function create(){
    const pending=new Map(),lanes=new Map();let currentScope=null;
    function clear(){for(const entry of pending.values())entry.controller.abort();pending.clear();lanes.clear();}
    function read(scope,key,build,lane='',signal=null){
      if(signal?.aborted)return Promise.reject(cancelled());
      if(currentScope!==scope){clear();currentScope=scope;}
      const full=JSON.stringify([scope,lane,key]);let entry=pending.get(full);
      if(!entry){
        if(lane){const previous=lanes.get(lane);if(previous&&previous.key!==full){previous.controller.abort();pending.delete(previous.key);}}
        const controller=new AbortController();entry={controller,key:full,consumers:new Set()};
        entry.promise=Promise.resolve().then(()=>{if(controller.signal.aborted)throw cancelled();return build(controller.signal)}).then(value=>{if(controller.signal.aborted)throw cancelled();return value}).finally(()=>{if(pending.get(full)===entry)pending.delete(full);if(lanes.get(lane)===entry)lanes.delete(lane)});
        pending.set(full,entry);if(lane)lanes.set(lane,entry);
      }
      // A caller's timeout/cancel belongs to that consumer. Shared readers keep
      // their transport until its last consumer leaves; retries then start fresh.
      return new Promise((resolve,reject)=>{
        const consumer={};let done=false;entry.consumers.add(consumer);
        const release=()=>{signal?.removeEventListener('abort',abort);entry.controller.signal.removeEventListener('abort',abort);entry.consumers.delete(consumer);};
        const abort=()=>{
          if(done)return;done=true;release();reject(cancelled());
          if(!entry.consumers.size){entry.controller.abort();if(pending.get(full)===entry)pending.delete(full);if(lanes.get(lane)===entry)lanes.delete(lane);}
        };
        signal?.addEventListener('abort',abort,{once:true});entry.controller.signal.addEventListener('abort',abort,{once:true});
        if(signal?.aborted||entry.controller.signal.aborted)abort();
        entry.promise.then(value=>{
          if(done)return;done=true;release();
          try{resolve(typeof structuredClone==='function'?structuredClone(value):JSON.parse(JSON.stringify(value)));}catch(error){reject(error);}
        },error=>{if(done)return;done=true;release();reject(error);});
      });
    }
    return {read,clear,pendingCount:()=>pending.size};
  }
  return {...create(),create};
})();
if(typeof module!=='undefined')module.exports=globalThis.ECGReadRequests;
