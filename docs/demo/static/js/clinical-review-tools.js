"use strict";
/* Geometry shared by virtual review cards and interactive R-peak locators. */
(()=>{
  function virtualGrid(total,width,scrollTop=0){
    const columns=Math.max(1,Math.min(6,Math.floor(width/170))),row=126,rows=Math.ceil(total/columns),height=Math.min(3,rows)*row||48;
    const top=Math.min(Math.max(0,scrollTop),Math.max(0,rows*row-height)),firstRow=Math.floor(top/row);
    return {columns,row,height,top,width:width/columns,contentHeight:rows*row,first:Math.max(0,(firstRow-1)*columns),last:Math.min(total,(firstRow+5)*columns),visibleFirst:total?firstRow*columns+1:0,visibleLast:Math.min(total,Math.ceil((top+height)/row)*columns)};
  }
  function markCanvas(ctx,x,top,bottom,code){
    ctx.save();ctx.globalAlpha=1;ctx.font='bold 11px sans-serif';
    const label=String(code||'?'),w=Math.max(18,ctx.measureText(label).width+8),labelY=Math.max(0,top-20),bandTop=Math.max(top,labelY+20);
    // Multiply leaves dark ECG traces dark; no opaque line crosses the R peak.
    ctx.globalCompositeOperation='multiply';ctx.fillStyle='rgba(217,75,136,.14)';ctx.fillRect(x-12,bandTop,24,Math.max(0,bottom-bandTop));
    ctx.globalCompositeOperation='source-over';ctx.fillStyle='#c92a2b';
    ctx.fillRect(x-3,bandTop,6,2);ctx.fillRect(x-3,bottom-2,6,2);
    ctx.fillStyle='#fff';ctx.fillRect(x-w/2,labelY,w,18);ctx.strokeStyle='#1760c2';ctx.lineWidth=1.5;ctx.strokeRect(x-w/2,labelY,w,18);
    ctx.fillStyle='#164d9a';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(label,x,labelY+9);ctx.restore();
  }
  function markSvg(x,height,code){
    const label=String(code||'?').replace(/[^A-Za-z?]/g,'');
    return `<g class="selected-r-peak" pointer-events="none"><rect class="selected-r-band" x="${x-12}" y="20" width="24" height="${Math.max(0,height-20)}" fill="#d94b88" fill-opacity=".14" style="mix-blend-mode:multiply"/><path d="M${x-3} 21h6M${x-3} ${height-1}h6" stroke="#c92a2b" stroke-width="2"/><rect x="${x-10}" y="0" width="20" height="18" fill="white" stroke="#1760c2" stroke-width="1.5"/><text x="${x}" y="13" fill="#164d9a" text-anchor="middle" font-size="13" font-weight="bold">${label}</text></g>`;
  }
  // The report workspace is the save destination for HRV inclusion drafts.
  const shouldConfirmNavigation=(current,next,dirty)=>Boolean(dirty&&current!==next&&next!=='report');
  const api={virtualGrid,markCanvas,markSvg,shouldConfirmNavigation};globalThis.ECGReviewTools=api;if(typeof module!=='undefined')module.exports=api;
})();
