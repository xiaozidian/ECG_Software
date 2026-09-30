"use strict";
/* Display-only preference. Saved report settings are independent snapshots. */
globalThis.ECGVoltage=(()=>{
  let enabled=false,factor=1;
  const key='cardioinsight.assumed-uv-per-unit.v1';
  function normalize(value){
    if(value==null)return null;
    if(value.mode!=='estimated'||typeof value.uv_per_unit!=='number'||!Number.isFinite(value.uv_per_unit)||value.uv_per_unit<.000001||value.uv_per_unit>10000)throw Error('估算系数须为 0.000001–10000 µV/设备单位');
    return {mode:'estimated',uv_per_unit:value.uv_per_unit,calibration_verified:false};
  }
  const snapshot=()=>enabled?normalize({mode:'estimated',uv_per_unit:factor}):null;
  function amplitude(value,wave={}){
    wave=wave||{};
    if(!Number.isFinite(value))return '—';
    const units=new Map([['µV',1],['μV',1],['uV',1],['mV',1000]]);
    if(wave.calibration_verified===true&&units.has(wave.units))return (value*units.get(wave.units)/1000).toFixed(3)+' mV';
    if(enabled&&wave.units==='device_unit')return (value*factor/1000).toFixed(3)+' mV（估算）';
    return value.toFixed(0)+' 设备单位';
  }
  const note=value=>value?`估算电压：1 u = ${normalize(value).uv_per_unit} µV；假设零点为 0，非设备校准，不能保证临床一致性。`:'设备单位，电压未校准。';
  function mount(){
    const toggle=document.querySelector('#voltageToggle'),panel=document.querySelector('#voltagePanel'),settings=document.querySelector('#voltageSettings'),form=panel.querySelector('form'),status=panel.querySelector('[role=status]');
    try{const saved=Number(localStorage.getItem(key));if(saved>=.000001&&saved<=10000&&Number.isFinite(saved))factor=saved;}catch(_){/* Storage may be unavailable; default off remains usable. */}
    form.elements.coefficient.value=factor;
    function update(){
      toggle.setAttribute('aria-checked',String(enabled));
      const short=factor.toLocaleString('en-US',{maximumSignificantDigits:4,useGrouping:false});
      toggle.textContent=enabled?`估算电压：开 · ${Number(short)===factor?'':'≈'}${short} µV/u`:'估算电压：关';
      toggle.title=note(snapshot());
      panel.querySelector('[data-voltage-current]').textContent=note(snapshot());
      document.dispatchEvent(new CustomEvent('ecg-voltage-display-change'));
    }
    function disclose(open){panel.hidden=!open;settings.setAttribute('aria-expanded',String(open));}
    toggle.onclick=()=>{enabled=!enabled;update();status.textContent=enabled?'估算显示已开启。原始采样和已保存报告未改变。':'估算显示已关闭。已保存的报告系数不会自动移除。';};
    settings.onclick=()=>disclose(panel.hidden);
    panel.querySelector('[data-voltage-close]').onclick=()=>{disclose(false);settings.focus();};
    panel.addEventListener('keydown',e=>{if(e.key==='Escape'){disclose(false);settings.focus();}});
    form.onsubmit=e=>{
      e.preventDefault();if(!form.reportValidity())return;
      try{factor=normalize({mode:'estimated',uv_per_unit:Number(form.elements.coefficient.value)}).uv_per_unit;enabled=true;update();let stored=true;try{localStorage.setItem(key,String(factor));}catch(_){stored=false;}
        status.textContent='已应用估算显示；下次启动仍默认关闭。'+(stored?'':'浏览器禁止保存设置，本次仍有效。');
      }catch(error){status.textContent=error.message;}
    };
    form.oninput=()=>{status.textContent='新系数尚未应用；顶部开关仍使用上次已应用的系数。';};
    panel.querySelector('[data-voltage-off]').onclick=()=>{enabled=false;update();status.textContent='保持设备单位显示。可随时用顶部开关开启。';disclose(false);toggle.focus();};
    panel.querySelector('[data-voltage-report]').onclick=()=>{
      try{if(!globalThis.ECGVoltage.applyToReport)throw Error('报告工作区尚未就绪');ECGVoltage.applyToReport(snapshot());status.textContent=enabled?'已把当前系数复制到本病例报告图条；请复核并保存草稿。研究指标需另行计算。':'已将本病例报告图条恢复设备单位；请保存草稿。研究指标设置未改变。';}catch(error){status.textContent=error.message;}
    };
    update();disclose(true);
  }
  return {normalize,snapshot,amplitude,note,mount};
})();
if(typeof document!=='undefined')document.addEventListener('DOMContentLoaded',()=>ECGVoltage.mount(),{once:true});
