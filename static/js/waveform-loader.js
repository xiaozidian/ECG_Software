"use strict";
/* Batch same-case/lead thumbnail reads. Bound concurrency so navigation stays responsive. */
((root)=>{
  function create(load,{batchSize=24,concurrency=2,cacheSize=192}={}){
    const cache=new Map(),pending=new Map();let queue=[],running=0,timer=null,generation=0;
    function schedule(){if(timer===null)timer=setTimeout(()=>{timer=null;drain()},0)}
    function drain(){
      while(running<concurrency&&queue.length){
        const group=queue[0].group,batch=[];
        queue=queue.filter(job=>{if(job.group===group&&batch.length<batchSize){batch.push(job);return false}return true});
        running++;
        Promise.resolve().then(()=>load(group,batch.map(job=>job.input))).then(items=>{
          if(!Array.isArray(items)||items.length!==batch.length)throw Error('波形批次不完整，请重试');
          batch.forEach((job,i)=>{if(job.generation===generation){cache.set(job.key,items[i]);job.resolve(items[i])}});
          while(cache.size>cacheSize)cache.delete(cache.keys().next().value);
        }).catch(error=>batch.forEach(job=>job.reject(error))).finally(()=>{
          batch.forEach(job=>{if(pending.get(job.key)===job)pending.delete(job.key)});running--;schedule();
        });
      }
    }
    return {get(key,group,input,{owner=null}={}){
      if(cache.has(key)){const value=cache.get(key);cache.delete(key);cache.set(key,value);return Promise.resolve(value)}
      if(pending.has(key)){const job=pending.get(key);job.owners.add(owner);return job.promise;}
      const job={key,group,input,generation,owners:new Set([owner])};job.promise=new Promise((resolve,reject)=>Object.assign(job,{resolve,reject}));
      queue.push(job);pending.set(key,job);schedule();return job.promise;
    },retain(owner,keys){
      // Only the named view may release its demand. Unowned/report consumers
      // stay pinned. In-flight batches keep their concurrency slot: aborting
      // fetch would not stop server work and could overload a local workstation.
      if(owner===null||owner===undefined)throw Error('需要明确的波形视图标识');
      const wanted=new Set(keys);
      pending.forEach(job=>{if(!wanted.has(job.key))job.owners.delete(owner)});
      queue=queue.filter(job=>{
        if(job.owners.size)return true;
        if(pending.get(job.key)===job)pending.delete(job.key);
        job.reject(Error('波形已离开当前视野，取消尚未发出的读取'));return false;
      });
      // Stable partition keeps ordering within a viewport and within other views.
      const current=job=>wanted.has(job.key)&&job.owners.has(owner);
      queue=[...queue.filter(current),...queue.filter(job=>!current(job))];schedule();
    },clear(){
      // A late response from the previous case/revision must neither repopulate
      // the cache nor remove a fresh pending request that happens to share its key.
      generation++;cache.clear();queue=[];
      pending.forEach(job=>job.reject(Error('波形依据已变化，请重新加载')));pending.clear();
    }};
  }
  root.ECGWaveformLoader={create};if(typeof module!=='undefined')module.exports={create};
})(typeof globalThis!=='undefined'?globalThis:this);
