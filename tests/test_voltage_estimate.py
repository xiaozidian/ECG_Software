"""Assumed gain is traceable research configuration, not acquisition calibration."""
import json
from pathlib import Path
import subprocess

import pytest

from ecg_core.signal_profile import normalize_voltage_estimate, paper_uv_per_unit, raw_signal_metadata
from ecg_core.advanced_analysis import analyze, normalize_options, report_documents
from ecg_core.storage import normalize_report_composition
from ecg_core.report_paper_pdf import build_paper_pdf
from ecg_core.report_pdf import _register_font, FONT_NAME
from test_advanced_analysis import synthetic
from test_signal_units import entry
from test_analysis_provenance import synthetic_app, synthetic_case

ROOT=Path(__file__).resolve().parents[1]

def estimate(factor=2):
    return dict(mode='estimated',uv_per_unit=factor,calibration_verified=False)

@pytest.mark.parametrize('value',[True,[],{},'2',{'mode':'verified','uv_per_unit':1},
    *[dict(mode='estimated',uv_per_unit=x) for x in [True,False,'1',0,-1,10001,float('inf'),float('nan')]]])
def test_invalid_settings_rejected(value):
    with pytest.raises(ValueError):normalize_voltage_estimate(value)
    with pytest.raises(ValueError):normalize_report_composition({'paper':{'voltage_estimate':value}})
    with pytest.raises(ValueError):normalize_options({'voltage_estimate':value})

def test_normalization_does_not_upgrade_acquisition():
    assert normalize_voltage_estimate() is None
    assert normalize_voltage_estimate(dict(estimate(),calibration_verified=True))==estimate()
    for factor in [.000001,1,10000]:
        e=estimate(factor)
        assert normalize_options(normalize_options({'voltage_estimate':e}))==normalize_options({'voltage_estimate':e})
        c=normalize_report_composition({'paper':{'voltage_estimate':e}})
        assert normalize_report_composition(c)==c
    with pytest.raises(ValueError,match='不一致'):
        normalize_options({'voltage_estimate':estimate(), 'uv_per_unit':3,'calibration_note':'different'})
    wave=raw_signal_metadata()
    assert paper_uv_per_unit(wave,estimate())==2
    assert wave['calibration_verified'] is False and wave['units']=='device_unit'
    assert paper_uv_per_unit({'units':'mV','calibration_verified':True},estimate())==1000
    assert paper_uv_per_unit({'units':'mV','calibration_verified':False},estimate()) is None

def test_known_signal_scales_amplitude_but_not_timing_quality_or_diagnosis(tmp_path):
    path,index=synthetic(tmp_path)
    original=path.read_bytes()
    a=analyze(path,index)
    b=analyze(path,index,{'voltage_estimate':estimate(3)})
    assert b['calibration_verified'] is False
    assert '1 u = 3' in b['calibration'] and '非设备校准' in b['calibration']
    assert b['qtd']==a['qtd'] and b['sap']==a['sap'] and b['vlp']==a['vlp']
    assert b['vcg']['status']=='insufficient' # A gain assumption cannot confirm electrodes.
    assert len(a['twa']['windows'])==len(b['twa']['windows'])>0
    for x,y in zip(a['twa']['windows'],b['twa']['windows']):
        assert y['amplitude']==pytest.approx(x['amplitude']*3,abs=1e-5)
        assert y['noise']==pytest.approx(x['noise']*3,abs=1e-5)
        assert y['start_s']==x['start_s'] and y['k_score']==pytest.approx(x['k_score'],abs=.0002)
    assert '估算' in b['twa']['unit']
    assert '非设备校准' in json.dumps(report_documents(b),ensure_ascii=False)
    assert path.read_bytes()==original
    assert analyze(path,index)['twa']==a['twa'] # no shared-cache contamination

def test_server_composition_roundtrip_and_pdf(synthetic_app,synthetic_case,monkeypatch):
    client=synthetic_app.test_client();base='/api/cases/'+synthetic_case[1]
    before=client.get(base+'/report').json
    payload=dict(conclusion='Synthetic only',status='draft',expected_version=before['version'],composition={'paper':{'voltage_estimate':estimate()}})
    response=client.put(base+'/report',json=payload)
    assert response.status_code==200,response.json
    saved=client.get(base+'/report').json
    assert saved['composition']['paper']['voltage_estimate']==estimate()
    assert client.get(base+'/waveform?start=1&duration=7').json['calibration_verified'] is False
    from reportlab.pdfgen.canvas import Canvas
    drawn=[];orig=Canvas.drawString
    def capture(self,x,y,t,*args,**kwargs):
        drawn.append(t);return orig(self,x,y,t,*args,**kwargs)
    monkeypatch.setattr(Canvas,'drawString',capture);_register_font()
    pdf=build_paper_pdf({'case_id':'synthetic','metadata':{}},{'composition':{'page_selection_version':1,'included_pages':['event_strips'],'paper':{'voltage_estimate':estimate()}},'selected_waveforms':[entry('device_unit',False)]},FONT_NAME)
    assert pdf.getvalue().startswith(b'%PDF')
    text='\n'.join(drawn)
    assert 'mm/估算mV' in text and '1u=2uV' in text and '非设备校准' in text
    assert '10 mm/mV' not in text

def test_browser_unit_and_report_parity():
    code=r"""const fs=require('fs'),vm=require('vm'),assert=require('assert');
    vm.runInThisContext(fs.readFileSync('static/js/voltage-estimate.js','utf8'));
    vm.runInThisContext(fs.readFileSync('static/js/report-paper.js','utf8'));
    const V=ECGVoltage;assert.equal(V.snapshot(),null);
    assert.equal(V.amplitude(1000,{units:'device_unit',calibration_verified:false}),'1000 设备单位');
    assert.equal(V.amplitude(1,{units:'mV',calibration_verified:true}),'1.000 mV');
    assert.equal(V.amplitude(1000,null),'1000 设备单位');
    for(const x of [NaN,Infinity,0,-1,'2',true])assert.throws(()=>V.normalize({mode:'estimated',uv_per_unit:x}));
    const entry=JSON.parse(fs.readFileSync(0,'utf8'));
    const svg=ECGReportPaper.stripSvg(entry,{voltage_estimate:{mode:'estimated',uv_per_unit:2}},276);
    assert(svg.includes('1u=2µV')&&svg.includes('非设备校准')&&svg.includes('mm/估算mV'));
    assert(!svg.includes('NaN')&&!svg.includes('Infinity'));
    assert(ECGReportPaper.stripSvg(entry,{},276).includes('电压未校准'));
    console.log('ok');"""
    assert subprocess.check_output(['node','-e',code],input=json.dumps(entry('device_unit',False)),text=True,cwd=ROOT).strip()=='ok'


def test_startup_toggle_and_explicit_report_snapshot():
    code=r"""const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
    function session(storageFails=false){
      const nodes=new Map(),events=[],writes=[],reports=[];
      const node=key=>{if(!nodes.has(key))nodes.set(key,{attrs:{},hidden:false,textContent:'',
        setAttribute(k,v){this.attrs[k]=v},focus(){this.focused=true},
        addEventListener(k,fn){this[k]=fn},querySelector:node});return nodes.get(key)};
      const form=node('form');form.elements={coefficient:{value:''}};form.reportValidity=()=>true;
      const ctx=vm.createContext({document:{querySelector:node,addEventListener(){},dispatchEvent:e=>events.push(e.type)},
        CustomEvent:class{constructor(type){this.type=type}},
        localStorage:{getItem:()=> '2',setItem:(k,v)=>{if(storageFails)throw Error('disabled');writes.push(v)}}});
      vm.runInContext(fs.readFileSync('static/js/voltage-estimate.js','utf8'),ctx);
      const V=ctx.ECGVoltage;V.applyToReport=x=>reports.push(x);V.mount();
      const toggle=node('#voltageToggle'),panel=node('#voltagePanel');
      assert.equal(V.snapshot(),null);assert.equal(panel.hidden,false);
      assert.equal(toggle.attrs['aria-checked'],'false');assert.equal(form.elements.coefficient.value,2);
      toggle.onclick();assert.equal(V.snapshot().uv_per_unit,2);
      assert.equal(V.amplitude(500,{units:'device_unit'}),'1.000 mV（估算）');
      assert.equal(V.amplitude(1,{units:'mV',calibration_verified:true}),'1.000 mV');
      assert.equal(V.snapshot().calibration_verified,false);assert.equal(reports.length,0);
      form.elements.coefficient.value='3';form.oninput();assert.equal(V.snapshot().uv_per_unit,2);
      form.onsubmit({preventDefault(){}});assert.equal(V.snapshot().uv_per_unit,3);
      assert.equal(reports.length,0);node('[data-voltage-report]').onclick();
      assert.equal(reports[0].uv_per_unit,3);toggle.onclick();assert.equal(V.snapshot(),null);
      assert.equal(reports.length,1);assert.equal(reports[0].uv_per_unit,3);
      node('[data-voltage-report]').onclick();assert.equal(reports[1],null);
      panel.keydown({key:'Escape'});assert.equal(panel.hidden,true);assert.equal(node('#voltageSettings').focused,true);
      assert(events.every(x=>x==='ecg-voltage-display-change'));
      assert.equal(writes.length,storageFails?0:1);
    }
    session();session(true);console.log('ok');"""
    assert subprocess.check_output(['node','-e',code],text=True,cwd=ROOT).strip()=='ok'
