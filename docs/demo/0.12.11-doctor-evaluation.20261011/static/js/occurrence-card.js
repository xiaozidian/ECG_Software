"use strict";
/* Screen thumbnails retain source samples and use CSS-pixel geometry. */
(()=>{
  const geometry={columns:7,minWidth:170,row:142,visibleRows:2};
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function leads(primary='II',count=2){return [primary,...['II','V1','V5'].filter(name=>name!==primary)].slice(0,count===3?3:2);}
  function windowFor(item){
    const anchor=item.sample_index/200,targets=[item.start_sample,item.end_sample,...(item.target_samples||[])].filter(Number.isFinite).map(s=>s/200);
    const half=Math.max(1.2,...targets.map(t=>Math.abs(t-anchor)+.8));
    return {start:Math.max(0,anchor-half),end:anchor+half};
  }
  function syncSelection(card,item,state){
    const samples=item.target_samples||[item.sample_index],count=samples.filter(s=>state.editSelectedSamples.has(s)).length;
    const all=count===samples.length,partial=count>0&&!all,input=card.querySelector('input[type=checkbox]'),button=card.querySelector('button');
    if(input){input.checked=all;input.indeterminate=partial;}
    card.dataset.selected=partial?'mixed':String(all);
    card.dataset.current=String(samples.includes(state.editSelectedSample));
    if(button){button.setAttribute('aria-pressed',partial?'mixed':String(all));if(samples.includes(state.editSelectedSample))button.setAttribute('aria-current','true');else button.removeAttribute('aria-current');}
  }
  function svg(wave,item,{width=170,height=90}={}){
    width=Math.max(1,Number(width)||170);height=Math.max(1,Number(height)||90);
    const entries=Object.entries(wave.leads||{}),row=height/Math.max(1,entries.length),fs=wave.sample_rate_hz||200,stride=wave.stride||1,duration=wave.duration_s;
    const anchor=(item.sample_index/fs-wave.start_s)/duration*width;
    const label=`${item.label||'心搏'}，${duration}秒，设备单位 u，各导联自适应幅度${stride>1?'，步进 '+stride+' 采样的概览，请回看完整波形':''}`;
    let output=`<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${escape(label)}"><rect width="100%" height="100%" fill="#fff"/>`;
    if(anchor>=0&&anchor<=width)output+=`<line class="occurrence-anchor" x1="${anchor}" x2="${anchor}" y1="0" y2="${height}" stroke="#d18427" stroke-width="1" vector-effect="non-scaling-stroke"/>`;
    entries.forEach(([name,values],j)=>{
      const mid=j*row+row/2,max=Math.max(50,...values.map(v=>Math.abs(v))),scale=row*.4/max;
      const points=values.map((value,i)=>`${(i*stride/fs/duration*width).toFixed(3)},${(mid-value*scale).toFixed(3)}`).join(' ');
      output+=`<polyline data-lead="${escape(name)}" fill="none" stroke="#172126" stroke-width="1.15" vector-effect="non-scaling-stroke" points="${points}"/><text x="3" y="${j*row+11}" font-size="10.5" fill="#36454d">${escape(name)}</text>`;
    });
    return output+'</svg>';
  }
  const api={geometry,leads,windowFor,syncSelection,svg};globalThis.ECGOccurrenceCard=api;if(typeof module!=='undefined')module.exports=api;
})();
