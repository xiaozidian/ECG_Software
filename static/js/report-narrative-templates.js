"use strict";
/* Deliberately small declarative language; never eval, HTML, or imported scripts. */
globalThis.ECGReportNarrative=(()=>{
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const starter={id:'measurement-summary',name:'统计综述（待人工复核）',is_default:true,source:'记录时长：{{Rec_Time_Span}}。总心搏数：{{Beat_Total_Count}} 搏。\n平均心率 {{HR_Aver}} bpm，最慢 {{HR_Min}} bpm（{{HR_Min_Time}}），最快 {{HR_Max}} bpm（{{HR_Max_Time}}）。\n室上性心搏 {{S_Total_Count}} 搏，成对 {{S_Couplet_Count}} 对；室性心搏 {{V_Total_Count}} 搏，成对 {{V_Couplet_Count}} 对。\n{{#if S_Run_Count}}室上性连续 ≥3 搏模式 {{S_Run_Count}} 阵（非自动房速诊断）。{{/if}}\n最长有效 RR：{{LG_RR}} ms（{{LG_RR_Time}}）。\nST-T：{{STT_State}}。\n请结合波形填写人工结论。'};
  const missing=reason=>({value:null,status:'unavailable',remark:reason});
  function fields({caseData,statistics}){
    const s=statistics.summary||{},meta=caseData.metadata||{},technical=caseData.technical||{},base=ECGReportStripEditor.clockBase(meta),duration=technical.duration_seconds_raw;
    const field=(value,unit,source,remark='')=>({value:value??null,unit,source,status:value==null?'unavailable':'available',remark});
    const time=t=>Number.isFinite(t)&&base!=null?ECGReportStripEditor.clockAt(base,t).replace('T',' ').slice(0,19):null;
    const hr=x=>Number.isFinite(x)?Math.floor(x+.5):null;
    const result={
      Rec_Channel_Count:field(technical.independent_channels,'通道','导入格式的独立通道数','与推导/显示 12 导联不同；设备映射待核验'),
      Rec_ST_Day:field(base==null?null:time(0)?.slice(0,10),'日期','记录头时间','设备时钟未独立验证'),Rec_ST_Time:field(base==null?null:time(0)?.slice(11),'时:分:秒','记录头时间'),
      Rec_Ed_Day:field(time(duration)?.slice(0,10),'日期','记录头时间 + 文件长度'),Rec_Ed_Time:field(time(duration)?.slice(11),'时:分:秒','记录头时间 + 文件长度'),
      Rec_Time_Span:field(Number.isFinite(duration)?`${Math.floor(duration/3600)} 小时 ${Math.floor(duration%3600/60)} 分 ${Number((duration%60).toFixed(3))} 秒`:null,'时长','字节数 / 格式采样率 / 通道数 / 2','不是有效 NN 时长；设备采样率需核验'),
      Rec_Time_Span_Val:field(duration,'s','文件长度推算记录时长'),Rec_Time_Span_Invalid:missing('医院字段名和“有效时长”备注存在歧义；未映射'),Rec_Time_Span_Invalid_Val:missing('未提供经核验的无效时长'),
      Beat_Total_Count:field(s.total,'搏','当前修订有效心搏统计','未完成诊断确认不等于确诊'),
      HR_Aver:field(hr(s.avg_hr),'bpm','当前修订有效 RR 的平均间期倒数','显示整数，底层精度不变'),HR_Min:field(hr(s.min_hr),'bpm','当前修订有效 RR'),HR_Max:field(hr(s.max_hr),'bpm','当前修订有效 RR'),
      HR_Min_Time:field(time(s.slowest?.time_s),'记录时钟','最慢有效 RR 后一心搏时间'),HR_Max_Time:field(time(s.fastest?.time_s),'记录时钟','最快有效 RR 后一心搏时间'),
      LG_RR:field(s.longest?.rr_ms,'ms','当前修订全程有效 RR（非手选候选）'),LG_RR_Time:field(time(s.longest?.time_s),'记录时钟','全程最长有效 RR 后一心搏时间'),
      Pause_TH:field(2500,'ms','原工程候选阈值','严格 >2500ms；不等于窦性停搏诊断阈值'),Pause_Total:field(s.pause,'次','原工程长 RR 候选 >2500ms','不将统计互斥桶替代检测器'),
      STT_State:field('未在此模板中重新评估；请查看 ST-T 专页状态','','ST-T 状态提示','未评估 / 不可评估 / 已评估未检出 / 事件待复核均不等于确认正常'),
      AF_Total_Count:field(s.rhythm?.confirmed_any?.count??s.af,'段','医生已确认房颤/房扑片段','与未确认筛查候选分开'),
      HRV_Reference:field('儿科参考范围未验证；仅报告合格 NN 的方法、时长、比例和数值','','本项目验证状态'),
    };
    for(const code of ['S','V'])for(const [key,path,unit,remark] of [['Total_Count','total','搏','当前逐搏类型，未自动确诊'],['Single_Count','single','次','模式计次'],['Couplet_Count','couplet','对','成对模式计次'],['Run_Count','run','阵','连续 ≥3 搏模式，非房速/室速自动诊断'],['Bigeminy_Count','bigeminy','阵','模式可能重叠，不与总数相加'],['Trigeminy_Count','trigeminy','阵','模式可能重叠，不与总数相加']])result[`${code}_${key}`]=field(s[code]?.[path],unit,'当前修订逐搏 / 事件统计',remark);
    for(const name of ['S_Run_Slow_Beat','S_Run_LG_Beat','S_Run_Fast_HR','L_Pause_TH','L_Pause_Total','Pause_LG_RR','Pause_LG_RR_Time','L_RR_TH','L_RR_Total','SG_RR','SG_RR_Time','STMaxUpLead','STMaxUpVal','STMaxUpTime','STMaxDpLead','STMaxDpVal','STMaxDpTime'])result[name]=missing('定义、数据源或电压校准未核验；不编造数值');
    return result;
  }
  function render(source,catalog){
    if(typeof source!=='string'||source.length>12000)throw Error('模板内容最长 12000 字');
    if(/<\/?\s*(?:script|skscript)\b|\{%|<%/i.test(source))throw Error('此模板含脚本语法；只支持 {{字段}} 与 {{#if 字段}}…{{/if}}，脚本不执行');
    const tokens=source.split(/(\{\{[\s\S]*?\}\})/g),stack=[true];let out='';const used=new Set();
    for(const token of tokens){
      if(!token.startsWith('{{')){if(stack.every(Boolean))out+=token;continue;}
      const key=token.slice(2,-2).trim();if(key==='/if'){if(stack.length===1)throw Error('条件结束标签没有开始标签');stack.pop();continue;}
      const conditional=key.startsWith('#if '),name=conditional?key.slice(4).trim():key;
      if(!Object.hasOwn(catalog,name))throw Error(`未知字段：${name}`);used.add(name);const f=catalog[name];
      if(conditional){if(stack.length>=9)throw Error('条件嵌套过深');stack.push(f.status==='available'&&Boolean(f.value));}
      else if(stack.every(Boolean))out+=f.status==='available'?String(f.value):'—（未提供）';
    }
    if(stack.length!==1)throw Error('条件缺少 {{/if}}');
    if(out.includes('{{')||out.includes('}}'))throw Error('模板花括号不完整');
    return {text:out,used:[...used],unavailable:[...used].filter(k=>catalog[k].status!=='available')};
  }
  function open({templates,context,editor,isCurrent=()=>true,onCommit}){
    if(document.querySelector('dialog[open]')||!isCurrent())return;
    const catalog=fields(context),drafts=structuredClone(templates?.length?templates:[starter]),dialog=document.createElement('dialog');let active=drafts.find(d=>d.is_default)?.id||drafts[0].id,result=null,undo=null;
    dialog.className='rw-template-dialog';dialog.setAttribute('aria-labelledby','rwNarrativeTitle');document.body.append(dialog);
    function current(){return dialog.isConnected&&isCurrent()&&editor.isConnected&&!editor.disabled&&!editor.readOnly;}
    function draw(){
      const selected=drafts.find(t=>t.id===active);dialog.innerHTML=`<header><h2 id="rwNarrativeTitle">综述模板</h2><button type="button" data-nt-close>取消并关闭</button></header><div class="rw-template-layout"><nav class="rw-template-list" aria-label="综述模板列表">${drafts.map(t=>`<button type="button" data-nt-id="${esc(t.id)}" aria-pressed="${t.id===active}">${esc(t.name)}${t.is_default?' · 默认':''}</button>`).join('')}<button type="button" data-nt-new>复制为新模板</button><button type="button" data-nt-delete ${drafts.length<2?'disabled':''}>删除本模板</button><button type="button" data-nt-undo ${undo?'':'disabled'}>撤销模板删除</button></nav><section class="rw-template-main"><label>模板名称<input data-nt-name value="${esc(selected.name)}" maxlength="80"></label><label><span><input type="checkbox" data-nt-default ${selected.is_default?'checked':''}>设为本报告默认模板</span></label><label>模板内容<textarea data-nt-source aria-label="模板内容" maxlength="12000" spellcheck="false">${esc(selected.source)}</textarea></label><p class="rw-hint">{{字段}} 插入已核验来源；{{#if 字段}}…{{/if}} 仅在字段可用且非零时包含内容。字段为零不会生成“正常”。外部医院脚本不执行。</p><strong>生成文字预览</strong><div data-nt-result></div><p role="status" data-nt-status></p><details open><summary>宏字段 · 名称 / 值 / 单位 / 来源与限制</summary><div class="rw-template-macros"><table><thead><tr><th>字段名</th><th>值</th><th>单位</th><th>来源 / 备注</th></tr></thead><tbody>${Object.entries(catalog).map(([k,f])=>`<tr><td><button type="button" data-nt-field="${k}" title="插入此字段">${k}</button></td><td>${esc(f.status==='available'?f.value:'未提供')}</td><td>${esc(f.unit||'—')}</td><td>${esc([f.source,f.remark].filter(Boolean).join('；'))}</td></tr>`).join('')}</tbody></table></div></details></section></div><footer><button type="button" data-nt-save>保存模板到草稿</button><button type="button" data-nt-append>将预览追加到结论</button><button type="button" data-nt-replace>用预览替换结论</button></footer>`;
      const q=s=>dialog.querySelector(s),source=q('[data-nt-source]'),status=q('[data-nt-status]');
      function preview(){const replace=q('[data-nt-replace]');replace.textContent='用预览替换结论';replace.onclick=()=>{q('[data-nt-result]').textContent=result.text+'\n\n—— 当前结论（替换前保留供核对）——\n'+editor.value;status.textContent='请核对以上新旧正文。再次点击“确认替换结论”才会替换；关闭或取消不修改正文。';replace.textContent='确认替换结论';replace.onclick=()=>commit('replace');};try{selected.source=source.value;result=render(source.value,catalog);q('[data-nt-result]').textContent=result.text;status.textContent=result.unavailable.length?`未提供字段：${result.unavailable.join('、')}。已显式标缺失；请人工核对。`:'字段来自当前修订，自动统计仍须医生复核。';q('[data-nt-append]').disabled=q('[data-nt-replace]').disabled=false;}catch(error){result=null;q('[data-nt-result]').textContent='无法生成';status.textContent=error.message;q('[data-nt-append]').disabled=q('[data-nt-replace]').disabled=true;}}
      q('[data-nt-close]').onclick=()=>dialog.close();source.oninput=preview;q('[data-nt-name]').oninput=e=>{selected.name=e.target.value;};q('[data-nt-default]').onchange=e=>{drafts.forEach(t=>t.is_default=t.id===active&&e.target.checked);draw();};
      dialog.querySelectorAll('[data-nt-id]').forEach(b=>b.onclick=()=>{active=b.dataset.ntId;draw();});
      dialog.querySelectorAll('[data-nt-field]').forEach(b=>b.onclick=()=>{source.setRangeText('{{'+b.dataset.ntField+'}}',source.selectionStart,source.selectionEnd,'end');preview();source.focus();});
      q('[data-nt-new]').onclick=()=>{if(drafts.length>=30){status.textContent='模板最多 30 个';return;}active='local-'+crypto.randomUUID();drafts.push({...selected,id:active,name:selected.name+' 副本',is_default:false});draw();};
      q('[data-nt-delete]').onclick=()=>{undo={item:structuredClone(selected),index:drafts.indexOf(selected)};drafts.splice(drafts.indexOf(selected),1);active=drafts[0].id;draw();};q('[data-nt-undo]').onclick=()=>{if(!undo)return;if(undo.item.is_default)drafts.forEach(t=>t.is_default=false);drafts.splice(undo.index,0,undo.item);active=undo.item.id;undo=null;draw();};
      const commit=mode=>{if(!current()){status.textContent='病例或报告已变化，本次模板尚未应用';return;}if(drafts.some(t=>!t.name.trim()||!t.source.trim())){status.textContent='模板名称与内容不能为空';return;}try{onCommit({templates:structuredClone(drafts),text:mode==='save'?null:result?.text,mode});dialog.close();}catch(error){status.textContent=error.message;}};
      q('[data-nt-save]').onclick=()=>commit('save');q('[data-nt-append]').onclick=()=>commit('append');
      preview();
    }
    dialog.addEventListener('close',()=>dialog.remove(),{once:true});draw();dialog.showModal();
  }
  return {starter,fields,render,open};
})();
