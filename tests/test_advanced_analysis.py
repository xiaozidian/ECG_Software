import json
import time
import numpy as np
import pytest
from ecg_core.advanced_analysis import (analyze, normalize_options, alternans_spectrum,
    KORS, vcg_analysis, nn_mask, sap_analysis)


def synthetic(tmp_path, duration=360, alternans=10):
    raw=np.zeros((duration*200,8),dtype=float)
    t=np.arange(-50,130)/200
    rows=[]
    for i,s in enumerate(range(200,duration*200-130,200)):
        for j in range(8):
            qrs=900*np.exp(-((t-.0)/.015)**2)-160*np.exp(-((t-.03)/.018)**2)
            tw=(180+(-1)**i*alternans)*np.exp(-((t-(.26+j*.005))/.055)**2)
            raw[s-50:s+130,j] += (qrs+tw)*(1+j*.07)
        rows.append(dict(sample_index=s,time_s=s/200,rr_ms=1000,class_code='N'))
    path=tmp_path/'synthetic.data'
    raw.astype('<i2').tofile(path)
    return path,dict(rows=rows,events=[])


def test_known_alternation_and_kors():
    x=np.ones((128,40))*100+(-1.)**np.arange(128)[:,None]*7
    a=alternans_spectrum(x)
    assert a['amplitude']==pytest.approx(7)
    assert a['k_score'] is None # no finite noise variance; not infinity or a diagnosis
    assert alternans_spectrum(np.ones((128,40)))['amplitude']==0
    for i in range(8):
        v=np.zeros((2,8));v[:,i]=[1,-1]
        assert np.allclose(v@KORS.T,np.array([KORS[:,i],-KORS[:,i]]))


def test_full_measurement_quality_manual_and_cache(tmp_path):
    path,index=synthetic(tmp_path)
    a=analyze(path,index)
    assert a['qtd']['beat_count']>=8
    assert a['qtd']['valid_leads']==8
    assert 20<=a['qtd']['qtd_ms']<=50
    assert all(300<r['qt_ms']<500 for r in a['qtd']['leads'])
    assert a['vcg']['status']=='insufficient'
    assert a['twa']['windows'] and a['twa']['unit']=='设备单位'
    assert a['vlp']['status']=='unsupported'
    options=dict(a['options'],standard_leads=True,uv_per_unit=2,calibration_note='合成信号已知比例',
                 marker_basis=a['basis'],markers={'II':dict(q_ms=-55,t_ms=400)})
    b=analyze(path,index,options)
    assert b['qtd']['leads'][1]['qt_ms']==455
    assert b['qtd']['leads'][1]['manual']
    assert b['vcg']['status']=='research'
    assert b['twa']['windows'][0]['amplitude']==pytest.approx(a['twa']['windows'][0]['amplitude']*2,abs=1e-5)
    b['qtd']['qtd_ms']=-123
    assert analyze(path,index,options)['qtd']['qtd_ms']>=0
    changed=json.loads(json.dumps(index));changed['rows'][10]['class_code']='V'
    with pytest.raises(ValueError,match='失效'):analyze(path,changed,options)
    with pytest.raises(ValueError,match='失效'):analyze(path,index,dict(options,start_s=10))


def test_empty_af_flat_and_bad_data(tmp_path):
    path,index=synthetic(tmp_path)
    empty=analyze(path,dict(rows=[],events=[]))
    assert empty['qtd']['status']==empty['twa']['status']=='insufficient'
    index['events']=[dict(category='AF',time_s=0,end_s=360)]
    a=analyze(path,index)
    assert a['qtd']['qtd_ms'] is None and not a['twa']['windows']
    path2=tmp_path/'flat';np.zeros((72000,8),dtype='<i2').tofile(path2)
    a=analyze(path2,dict(rows=index['rows'],events=[]),dict(standard_leads=True))
    assert a['qtd']['qtd_ms'] is None and a['vcg']['status']=='insufficient' and not a['twa']['windows']
    path3=tmp_path/'bad';path3.write_bytes(b'123')
    with pytest.raises(ValueError,match='完整'):analyze(path3,index)


def test_clipped_vcg_and_af_boundary_are_rejected(tmp_path):
    path,index=synthetic(tmp_path)
    raw=np.memmap(path,dtype='<i2',mode='r+',shape=(72000,8))
    raw[400,0]=32767
    raw.flush()
    del raw
    a=analyze(path,index,{'standard_leads':True})
    assert a['vcg']['status']=='insufficient'
    with pytest.raises(ValueError,match='平线或削顶'):
        analyze(path,index,dict(marker_basis=a['basis'],markers={'I':{'q_ms':-50,'t_ms':400}}))
    rows=[dict(sample_index=i*200,rr_ms=1000,class_code='N') for i in range(1,6)]
    valid=nn_mask(rows,[(1.5,2.5)])[2]
    assert valid.tolist()==[False,False,False,True,True]


@pytest.mark.parametrize('option',[{'start_s':float('nan')},{'duration_s':1},{'standard_leads':'yes'},
    {'uv_per_unit':1},{'sap_start_s':100,'sap_end_s':90},{'markers':{'I':{'q_ms':-30,'t_ms':400}}}])
def test_options_reject_invalid(option):
    with pytest.raises(ValueError):normalize_options(option)


def test_rr_screen_periodicity_missing_and_not_ahi():
    times=np.arange(1,601,dtype=float)
    rr=1000+100*np.sin(2*np.pi*times/60)
    valid=np.ones(600,dtype=bool)
    a=sap_analysis(times,rr,valid,601,normalize_options())
    assert a['candidate_windows']==2 and a['valid_minutes']==10
    assert 'ahi' not in a and 'apnea_count' not in a
    b=sap_analysis(times,np.ones(600)*1000,valid,601,normalize_options())
    assert b['candidate_windows']==0
    valid[40:100]=False
    c=sap_analysis(times,rr,valid,601,normalize_options())
    assert c['valid_minutes']==5 and c['windows'][0]['valid'] is False
    rows=[dict(sample_index=200,rr_ms=1000,class_code='N'),dict(sample_index=800,rr_ms=1000,class_code='N')]
    assert not np.any(nn_mask(rows)[2])


def test_api_and_composition_roundtrip(client):
    cid=client.get('/api/cases').json['items'][0]['case_id']
    start=time.perf_counter()
    r=client.post(f'/api/cases/{cid}/advanced-analysis',json={'options':{'duration_s':60}})
    assert r.status_code==200,r.json
    assert set(r.json['documents'])=={'qtd','vcg','twa','sap'}
    assert r.json['sample_rate_hz']==200
    assert 'name' not in r.json and 'data_path' not in r.json
    assert time.perf_counter()-start<30
    from ecg_core.storage import normalize_report_composition
    composition=normalize_report_composition({'advanced_options':r.json['options'],'page_selection_version':1,'included_pages':['qtd','vcg','twa','sap']})
    assert composition['advanced_options']==r.json['options']
    invalid = client.post(f'/api/cases/{cid}/advanced-analysis',json={'options':{'start_s':-1}})
    assert invalid.status_code==400, invalid.json


def test_documents_pdf_and_browser_share_evidence(tmp_path):
    from ecg_core.advanced_analysis import report_documents
    from ecg_core.report_pdf import build_report_pdf
    from ecg_core.report_sections_pdf import documents
    import subprocess
    path,index=synthetic(tmp_path)
    data=analyze(path,index,{'standard_leads':True})
    data['documents']=report_documents(data)
    case={'case_id':'synthetic-advanced-test','metadata':{},'summary':{}}
    report={'status':'draft','selected_waveforms':[],'composition':{'page_selection_version':1,'included_pages':['qtd','vcg','twa','sap']},'section_evidence':{'advanced':data}}
    docs=documents(case,report,report['composition']['included_pages'])
    model={'case':case,'report':report,'evidence':report['section_evidence']}
    script="global.ECGReportPaper={clock:()=>'',wrapText:x=>[x]};const s=require('./static/js/report-sections.js');const m=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify(s.documents(m,m.report.composition.included_pages)))"
    browser=json.loads(subprocess.check_output(['node','-e',script],input=json.dumps(model),text=True))
    assert docs==browser
    pdf=build_report_pdf(case,{},report).getvalue()
    assert pdf.startswith(b'%PDF') and len(pdf)>10000
