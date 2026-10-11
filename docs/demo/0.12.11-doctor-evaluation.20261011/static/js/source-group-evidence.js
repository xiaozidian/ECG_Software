"use strict";
/* Read-only source excerpts; the full group remains the edit/report target. */
globalThis.ECGSourceGroupEvidence=(()=>{
  let closeCurrent=null;
  function clear(){closeCurrent?.();closeCurrent=null;}
  function mount(host,{item,loadWave,onLocate,isCurrent}){
    clear();
    const samples=item.target_samples||[];
    if(samples.length<2){host.hidden=true;return;}
    if(!samples.every(s=>Number.isSafeInteger(s)&&s>=0))throw Error('源心搏位置无效，不能生成回看证据');
    let index=0,twelve=false,sequence=0,controller=null,closed=false;
    const current=()=>!closed&&host.isConnected&&isCurrent();
    closeCurrent=()=>{closed=true;sequence++;controller?.abort();host.hidden=true;};
    host.hidden=false;host.className='source-group-evidence';
    host.innerHTML='<details open><summary>组合逐搏原始证据</summary><p>上方小图是完整事件概览。本区每次回看一个源心搏附近 6 秒、保留每个采样；组合选中范围与改型目标保持完整。</p><div class="source-group-controls"><button type="button" data-sg-prev>上一源搏</button><label>第 <input type="number" min="1" data-sg-index aria-label="组合源心搏序号"> 搏</label><button type="button" data-sg-go>回看</button><button type="button" data-sg-next>下一源搏</button><button type="button" data-sg-twelve aria-pressed="false">12 导联</button><button type="button" data-sg-locate>定位编辑连续波形</button><button type="button" data-sg-close>关闭逐搏证据</button></div><p data-sg-status role="status" aria-live="polite"></p><div data-sg-wave></div><button type="button" data-sg-retry hidden>重试此源搏</button></details>';
    const q=s=>host.querySelector(s),input=q('[data-sg-index]'),status=q('[data-sg-status]'),waveHost=q('[data-sg-wave]');
    input.max=String(samples.length);
    async function read(){
      if(!current())return;
      const sample=samples[index],request=++sequence;controller?.abort();controller=new AbortController();
      input.value=String(index+1);q('[data-sg-prev]').disabled=index===0;q('[data-sg-next]').disabled=index===samples.length-1;
      q('[data-sg-twelve]').setAttribute('aria-pressed',String(twelve));q('[data-sg-twelve]').textContent=twelve?'返回 3 导联':'12 导联';
      q('[data-sg-retry]').hidden=true;waveHost.replaceChildren();host.setAttribute('aria-busy','true');
      status.textContent=`正在读取第 ${index+1} / ${samples.length} 源搏 · 采样 ${sample}…`;
      try{
        const wave=await loadWave({start:Math.max(0,sample/200-3),duration:6,filter:'raw',max_points:1500,leads:twelve?'I,II,III,aVR,aVL,aVF,V1,V2,V3,V4,V5,V6':'II,V1,V5'},controller.signal);
        if(request!==sequence||!current())return;
        if(wave.stride!==1||wave.filter!=='raw')throw Error('未取得逐采样原始片段，不能作为本区证据');
        waveHost.innerHTML=ECGOccurrenceCard.svg(wave,{sample_index:sample,label:'组合逐搏原始证据'},{width:900,height:(twelve?12:3)*70});
        status.textContent=`第 ${index+1} / ${samples.length} 源搏 · 采样 ${sample} · 记录后 ${(sample/200).toFixed(3)} 秒 · ${wave.duration_s} 秒原始片段 · 步进 1 · 设备单位 u，未校准`;
      }catch(error){
        if(request!==sequence||!current()||error.name==='AbortError')return;
        status.textContent='原始证据读取失败：'+error.message+'；可重试，组合目标未改变。';q('[data-sg-retry]').hidden=false;
      }finally{if(request===sequence&&current())host.setAttribute('aria-busy','false');}
    }
    const move=next=>{if(!current())return;index=Math.max(0,Math.min(samples.length-1,next));read();};
    q('[data-sg-prev]').onclick=()=>move(index-1);q('[data-sg-next]').onclick=()=>move(index+1);
    function go(){const n=Number(input.value);input.setCustomValidity(Number.isSafeInteger(n)&&n>=1&&n<=samples.length?'':`请输入 1–${samples.length} 的整数`);if(input.reportValidity())move(n-1);}
    input.oninput=()=>input.setCustomValidity('');input.onkeydown=e=>{e.stopPropagation();if(e.key==='Enter'){e.preventDefault();go();}};q('[data-sg-go]').onclick=go;
    q('[data-sg-twelve]').onclick=()=>{if(current()){twelve=!twelve;read();}};
    q('[data-sg-locate]').onclick=()=>{if(current())onLocate(samples[index]/200);};
    q('[data-sg-retry]').onclick=read;q('[data-sg-close]').onclick=clear;
    read();
  }
  const api={mount,clear};if(typeof module!=='undefined')module.exports=api;return api;
})();
