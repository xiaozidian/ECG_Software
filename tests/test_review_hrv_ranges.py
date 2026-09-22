import json
import math
from pathlib import Path
import subprocess
from types import SimpleNamespace
import pytest
from ecg_core.hrv_analysis import analyze_hrv, spectrum
from ecg_core.report_layout import resolve_strip, strip_settings
from ecg_core.clinical_analysis import build_index, normalize_selection, validate_report
from ecg_core.storage import normalize_report_composition

ROOT=Path(__file__).parents[1]
OPTS=dict(nn_min=300,nn_max=2000,pause=2.5,tachy=120,brady=50)


def test_hrv_draft_can_reach_report_without_discarding():
    assert js("['report','trends','edit','dashboard'].map(next=>ECGReviewTools.shouldConfirmNavigation('trends',next,true))", {}) == [False,False,True,True]


def feed(duration=600,code='N'):
    rows=[];sample=0
    while sample<duration*200:
        rr=round((.8+.07*math.sin(sample/200*2*math.pi*.1))*200)
        rows.append(dict(id=f's:{sample}',sample_index=sample,time_s=sample/200,class_code=code,rr_ms=(sample-rows[-1]['sample_index'])*5 if rows else 0,hr=60000/((sample-rows[-1]['sample_index'])*5) if rows else None))
        sample+=rr
    return SimpleNamespace(beats=rows,markers=[],duration=duration,document={'settings':OPTS})


def js(expression,payload):
    code="require('./static/js/report-engine.js');require('./static/js/clinical-analysis.js');require('./static/js/hrv-analysis.js');require('./static/js/clinical-review-tools.js');const input=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify("+expression+"));"
    return json.loads(subprocess.check_output(['node','-e',code],input=json.dumps(payload),text=True,cwd=ROOT))


def test_frequency_peak_and_energy_are_measured():
    nn=[(i,i,i+1,800+100*math.sin(2*math.pi*.1*(i+1))) for i in range(300)]
    psd=spectrum(nn)
    peak=max(range(1,129),key=lambda k:psd[k])
    assert peak*4/1024==pytest.approx(.1,abs=.004)
    assert 3500<sum(v*4/1024 for v in psd[1:])<5500
    assert sum(psd[k] for k in range(11,39))>10*sum(psd[k] for k in range(39,103))


def test_short_noise_and_unknown_clock_do_not_fabricate_metrics():
    short=analyze_hrv(feed(120),None)
    assert short['periods']['full']['spectral_blocks']==0
    assert short['periods']['full']['frequency']['lf_ms2'] is None
    assert short['periods']['day']['nn_count']==0
    assert short['periods']['night']['coverage_s']==0
    noise=analyze_hrv(feed(600,'X'),'2026-09-20 08:00:00')
    assert noise['periods']['full']['nn_count']==0
    assert noise['periods']['full']['sdnn_ms'] is None


def test_gaps_are_not_interpolated_into_frequency():
    nn=[(i,i,i+1,800) for i in range(300) if not 100<=i<=110]
    assert spectrum(nn) is None


def test_hrv_browser_backend_parity_and_day_night():
    f=feed(1200);clock='2026-09-20 21:50:00'
    py=analyze_hrv(f,clock);browser=js('ECGHrvAnalysis.analyze(input.feed,input.clock)',{'feed':vars(f),'clock':clock})
    assert py['periods']['full']['nn_count']>1400
    assert py['periods']['day']['coverage_s']==py['periods']['night']['coverage_s']==600
    for key in py['periods']:
        a,b=py['periods'][key],browser['periods'][key]
        assert a['spectral_blocks']==b['spectral_blocks']
        assert a['spectral_blocks']>0
        for metric in ['sdnn_ms','rmssd_ms','pnn50_pct','sdann_ms','sdnn_index_ms','triangular_index']:
            assert a[metric]==pytest.approx(b[metric],abs=.0002)
        assert a['frequency']==pytest.approx(b['frequency'],abs=.0002)
        assert a['histogram']==b['histogram']
        assert [p['power'] for p in a['psd']]==pytest.approx([p['power'] for p in b['psd']],abs=.0002)


def test_vertical_virtual_grid_is_bounded_and_can_reach_last_record():
    g=js('ECGReviewTools.virtualGrid(input.total,input.width,input.top)',{'total':106370,'width':1000,'top':3e7})
    assert g['columns']==5 and g['last']==106370
    assert g['last']-g['first']<=30
    assert g['visibleLast']==106370
    small=js('ECGReviewTools.virtualGrid(2,1000,0)',{})
    assert small['height']==126 and small['contentHeight']==126


def test_manual_range_is_exact_persists_and_matches_browser():
    f=feed(60);index=build_index(f);event=index['events'][0]
    anchor=event['start_sample']/200;a=max(0,anchor-4);b=min(60,a+10)
    spec={'leads':['II','V1'],'duration_s':7,'range_start_s':a,'range_end_s':b}
    py=resolve_strip(index,event,spec);browser=js('ECGReportEngine.resolve(input.index,input.event,input.spec)',{'index':index,'event':event,'spec':spec})
    assert py==browser
    assert py['start_s']==round(a*200)/200 and py['end_s']==round(b*200)/200
    assert '延长' not in py['warning']
    comp=normalize_report_composition({'selected_events':[dict(event_id=event['event_id'],basis_version=event['basis_version'],**spec)],'include_hrv':True})
    assert comp['include_hrv'] is True
    assert validate_report(index,comp,{})[0]['range_start_s']==py['start_s']


@pytest.mark.parametrize('spec',[{'range_start_s':0},{'range_start_s':True,'range_end_s':7},{'range_start_s':float('nan'),'range_end_s':7},{'range_start_s':1,'range_end_s':1.5},{'range_start_s':0,'range_end_s':121}])
def test_invalid_manual_spec_rejected(spec):
    with pytest.raises(ValueError):strip_settings(spec)


def test_manual_range_requires_anchor_and_five_usable_beats():
    index=build_index(feed(60));e={'start_sample':6000}
    for a,b in [(0,10),(29,31),(55,65)]:
        with pytest.raises(ValueError):resolve_strip(index,e,{'range_start_s':a,'range_end_s':b})
    with pytest.raises(ValueError):normalize_report_composition({'include_hrv':'yes'})


@pytest.mark.parametrize('code',['N','S','V'])
def test_peak_marker_has_translucent_band_edge_ticks_and_blue_label(code):
    from xml.etree import ElementTree
    result=ElementTree.fromstring(js("ECGReviewTools.markSvg(100,300,input.code)",{'code':code}))
    band=result.find("./rect[@class='selected-r-band']")
    assert band is not None and float(band.attrib['width'])==24
    assert float(band.attrib['fill-opacity'])==pytest.approx(.14)
    assert 'multiply' in band.attrib['style'] and 'stroke' not in band.attrib
    ticks=result.find('path')
    assert ticks.attrib['d']=='M97 21h6M97 299h6'
    assert ticks.attrib['stroke']=='#c92a2b'
    assert result.find("./rect[@stroke='#1760c2']") is not None
    assert result.find('text').text==code


def test_canvas_peak_marker_keeps_waveform_clear_and_label_above_plot():
    result=js("""(()=>{
      const fills=[],frames=[],labels=[];
      // No path/line API: adding a through-wave line must fail this test.
      const ctx={save(){},restore(){},measureText:()=>({width:6}),
        fillRect(...rect){fills.push({rect,color:this.fillStyle,blend:this.globalCompositeOperation})},
        strokeRect(...rect){frames.push({rect,color:this.strokeStyle})},
        fillText(text,x,y){labels.push({text,x,y})}};
      ECGReviewTools.markCanvas(ctx,100,27,300,'N');return {fills,frames,labels};
    })()""",{})
    band=result['fills'][0]
    assert band=={'rect':[88,27,24,273],'color':'rgba(217,75,136,.14)','blend':'multiply'}
    ticks=[fill['rect'] for fill in result['fills'] if fill['color']=='#c92a2b']
    assert ticks==[[97,27,6,2],[97,298,6,2]]
    assert result['frames']==[{'rect':[91,7,18,18],'color':'#1760c2'}]
    assert result['labels']==[{'text':'N','x':100,'y':16}]


def test_range_editor_has_only_two_cursors_and_keeps_explicit_apply():
    # Mount against small DOM doubles; browser verification covers actual hit targets.
    code=r"""
    const assert=require('node:assert/strict');
    require('./static/js/clinical-review-tools.js');
    require('./static/js/report-range-editor.js');
    const make=dataset=>({dataset,style:{},addEventListener(){},setPointerCapture(){},
      closest(){return this},parentElement:{getBoundingClientRect:()=>({width:1000})}});
    const start=make({rangeDrag:'start'}),end=make({rangeDrag:'end'});
    const from=make({bound:'start'}),to=make({bound:'end'}),output={},error={},apply={},reset={};
    const nodes={'[data-range-drag=start]':[start],'[data-range-drag=end]':[end],
      '[data-bound=start]':[from],'[data-bound=end]':[to],'[data-bound]':[from,to],
      'output':[output],'.range-error':[error],'[data-range-apply]':[apply],
      '[data-range-reset]':[reset],'button,input':[start,end,from,to,apply,reset]};
    const handlers={},host={style:{setProperty(){}},
      querySelector:s=>nodes[s]?.[0],querySelectorAll:s=>nodes[s]||[],
      addEventListener:(type,fn)=>handlers[type]=fn};
    let applied=null,resets=0;
    ECGReportRange.mount(host,{strip:{start_s:2,end_s:9},sample_index:1000},
      {start_s:0,duration_s:20,leads:{II:[0,20,0],V1:[0,-30,0],V5:[0,40,0]},
       beats:[{sample_index:1000,class_code:'V'}]},value=>{applied=value},()=>{resets++});
    assert.equal((host.innerHTML.match(/class="report-range-stage"/g)||[]).length,1);
    assert.equal((host.innerHTML.match(/<svg /g)||[]).length,1);
    assert.equal((host.innerHTML.match(/<polyline /g)||[]).length,3);
    assert.equal((host.innerHTML.match(/class="report-range-handle"/g)||[]).length,2);
    assert(!/report-range-region|report-range-strip|data-range-drag="move"/.test(host.innerHTML));
    assert(host.innerHTML.includes('#c92a2b')&&host.innerHTML.includes('#1760c2'));
    const event={preventDefault(){},stopPropagation(){},target:start};
    handlers.keydown({...event,key:'ArrowRight',shiftKey:false});
    assert.equal(from.value,'2.005');
    handlers.pointerdown({...event,button:0,pointerId:1,clientX:100});
    handlers.pointermove({pointerId:1,clientX:150});handlers.pointerup();
    assert.equal(from.value,'3.005');assert.equal(to.value,'9.000');
    handlers.pointerdown({...event,target:end,button:0,pointerId:2,clientX:450});
    handlers.pointermove({pointerId:2,clientX:500});handlers.pointerup();
    assert.equal(to.value,'10.000');
    from.value='3.25';from.onchange();to.value='10.75';to.onchange();
    assert.equal(applied,null);
    assert(output.textContent.includes('尚未应用'));
    (async()=>{await apply.onclick();assert.deepEqual(applied,{range_start_s:3.25,range_end_s:10.75});
      await reset.onclick();assert.equal(resets,1)})().catch(e=>{console.error(e);process.exitCode=1});
    """
    subprocess.run(['node','-e',code],cwd=ROOT,check=True)
    css=(ROOT/'static/css/clinical-review-tools.css').read_text()
    assert '.report-range-region' not in css and '.report-range-strip' not in css


def test_manual_subsample_rounding_and_save_validation_match_demo():
    spec={'range_start_s':1.0025,'range_end_s':8.0025}
    assert strip_settings(spec)==js('ECGReportEngine.settings(input)',spec)
    index=build_index(feed(60));event=index['events'][0]
    invalid={'selected_events':[dict(event_id=event['event_id'],basis_version=event['basis_version'],range_start_s=0,range_end_s=1)]}
    result=js("(()=>{try{ECGClinicalAnalysis.validateReport(input.index,input.comp,{});return 'accepted'}catch(e){return e.message}})()",{'index':index,'comp':invalid})
    assert result!='accepted'


def test_hrv_detail_table_keeps_missing_st_unknown_not_zero():
    result=js("(()=>{require('./static/js/hrv-report.js');return ECGHrvReport.detailRows(input,input.hourly)})()",{
        'hourly':[{'start_s':0,'end_s':600,'label':'08-05 08:00'}],
        'st_trends':{'II':[{'time_s':1,'deviation_units':None},{'time_s':30,'deviation_units':-40},{'time_s':500,'deviation_units':20}]},
        'event_statistics':{'hourly':[{'start_s':0,'end_s':600,'S':{'single':3,'couplet':2,'total':7},'af':0}]}})
    assert result[0]['stI'] is None and result[0]['stII']==-40
    assert result[0]['block'] is None and result[0]['Scouplet']==2


def test_standalone_hrv_pdf_has_two_a4_pages(tmp_path,monkeypatch):
    import re
    from ecg_core.report_pdf import build_report_pdf
    from reportlab.pdfgen.canvas import Canvas
    labels=[]
    for method in ('drawString','drawRightString','drawCentredString'):
        original=getattr(Canvas,method)
        def capture(self,x,y,text,*args,_draw=original,**kwargs):
            labels.append((self.getPageNumber(),str(text),self._fontsize))
            return _draw(self,x,y,text,*args,**kwargs)
        monkeypatch.setattr(Canvas,method,capture)
    data=analyze_hrv(feed(600),'2026-09-20 08:00:00')
    data['st_trends']={'II':[{'time_s':1,'deviation_units':None},{'time_s':30,'deviation_units':-40},{'time_s':120,'deviation_units':None}]}
    case={'case_id':'hrv-test','metadata':{'name':'测试','patient_id':'test'},'summary':{}}
    document=build_report_pdf(case,{},dict(status='draft',hrv_only=True,selected_waveforms=[],hrv_analysis=data)).getvalue()
    assert len(re.findall(rb'/Type /Page\b',document))==2
    assert b'595.2756 841.8898' in document
    assert document.startswith(b'%PDF-')
    for name in ('平均 NN ms','SDNN ms','SDANN ms','SDNN index ms','rMSSD ms'):
        assert any(page==1 and text==name for page,text,size in labels)
    assert any(page==2 and text=='S单发' and size>=6.3 for page,text,size in labels)
    for page in (1,2):
        assert any(p==page and '未审核' in text for p,text,size in labels)
        assert any(p==page and '需医生复核' in text for p,text,size in labels)


def test_api_manual_range_hrv_inclusion_and_privacy(client):
    import re
    case=client.get('/api/cases').json['items'][0]['case_id'];base=f'/api/cases/{case}'
    event=client.get(base+'/report-events?category=fastest').json['items'][0]
    params={'event_id':event['event_id'],'basis_version':event['basis_version'],'duration':7,'leads':'II,V1,V5'}
    auto=client.get(base+'/report-strip',query_string=params).json['strip']
    manual={'range_start_s':auto['start_s'],'range_end_s':auto['end_s']}
    assert client.get(base+'/report-strip',query_string={**params,**manual}).json['strip']['start_s']==auto['start_s']
    assert client.get(base+'/report-strip',query_string={**params,'range_start_s':0,'range_end_s':1}).status_code==400
    draft=client.get(base+'/report').json
    selected=dict(event_id=event['event_id'],basis_version=event['basis_version'],**manual)
    response=client.put(base+'/report',json={'status':'draft','expected_version':draft['version'],'conclusion':'软件回归验证','composition':{**draft['composition'],'selected_events':[selected],'include_hrv':True}})
    assert response.status_code==200
    saved=client.get(base+'/report').json['composition']
    assert saved['include_hrv'] is True and saved['selected_events'][0]['range_end_s']==auto['end_s']
    pdf=client.get(base+'/hrv-report.pdf');assert pdf.status_code==200
    assert pdf.headers['X-Privacy-Mode']=='masked'
    assert len(re.findall(rb'/Type /Page\b',pdf.data))==2
    main=client.get(base+'/report.pdf');assert main.status_code==200
    assert len(re.findall(rb'/Type /Page\b',main.data))>=5
