"use strict";
/* Batch same-case/lead thumbnail reads. Bound concurrency so navigation stays responsive. */
((root)=>{
  function create(load,{batchSize=24,concurrency=2,cacheSize=192}={}){
    const cache=new Map(),pending=new Map();let queue=[],running=0,timer=null;
    function schedule(){if(timer===null)timer=setTimeout(()=>{timer=null;drain()},0)}
    function drain(){
      while(running<concurrency&&queue.length){
        const group=queue[0].group,batch=[];
        queue=queue.filter(job=>{if(job.group===group&&batch.length<batchSize){batch.push(job);return false}return true});
        running++;
        Promise.resolve().then(()=>load(group,batch.map(job=>job.input))).then(items=>{
          if(!Array.isArray(items)||items.length!==batch.length)throw Error('波形批次不完整，请重试');
          batch.forEach((job,i)=>{cache.set(job.key,items[i]);job.resolve(items[i])});
          while(cache.size>cacheSize)cache.delete(cache.keys().next().value);
        }).catch(error=>batch.forEach(job=>job.reject(error))).finally(()=>{
          batch.forEach(job=>pending.delete(job.key));running--;schedule();
        });
      }
    }
    return {get(key,group,input){
      if(cache.has(key)){const value=cache.get(key);cache.delete(key);cache.set(key,value);return Promise.resolve(value)}
      if(pending.has(key))return pending.get(key);
      const promise=new Promise((resolve,reject)=>queue.push({key,group,input,resolve,reject}));
      pending.set(key,promise);schedule();return promise;
    },clear(){cache.clear()}};
  }
  root.ECGWaveformLoader={create};if(typeof module!=='undefined')module.exports={create};
})(typeof globalThis!=='undefined'?globalThis:this);
