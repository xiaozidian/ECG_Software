"""Report presentation / template contracts, using authored numerical fixtures only."""
import copy
import io
import json
import subprocess
import pytest
from ecg_core.storage import Storage, normalize_report_composition
from ecg_core.report_curation import strip_curation, narrative_templates
from ecg_core.clinical_analysis import validate_report
from ecg_core.report_layout import prepare_strip
from ecg_core.report_paper_pdf import build_paper_pdf
from ecg_core.report_pdf import _register_font, FONT_NAME
from test_report_layout import index_for
from test_paper_geometry import sample_entry


def node(source, data=None):
    return json.loads(subprocess.check_output(['node','-e',source],input=json.dumps(data),text=True))


def test_independent_settings_and_templates_survive_save_reopen_without_beat_edit(tmp_path):
    index=index_for(list(range(30)),list('NNNSNNNNNNVNNNNNNNNNNNNNNNNNNN'),duration=30)
    events=[e for e in index['events'] if e['category'] in ('S','V')][:2]
    picks=[dict(event_id=e['event_id'],basis_version=e['basis_version'],caption='math'+str(i),leads=['II'] if i else ['II','V1','V5'],duration_s=7,print_enabled=i==0,notes='保留注释'+str(i),preview_lead='V1') for i,e in enumerate(events)]
    assert len(picks)==2
    template=dict(id='test',name='数学模板',source='心搏 {{Beat_Total_Count}}',is_default=True)
    comp=normalize_report_composition(dict(selected_events=picks,narrative_templates=[template]))
    db=Storage(tmp_path/'curation.db');before=copy.deepcopy(index)
    saved=db.save_report('math','原人工结论','draft','test',comp)
    assert db.get_report('math','')['composition']==saved['composition']
    assert saved['composition']['selected_events']==picks
    assert saved['composition']['narrative_templates']==[template]
    resolved=validate_report(index,saved['composition'],{})
    assert resolved[1]['print_enabled'] is False and resolved[0]['notes']=='保留注释0'
    assert index==before and db.get_review('math')['revision']==0


@pytest.mark.parametrize('value',[{'print_enabled':0},{'notes':1},{'notes':'x'*2001},{'preview_lead':'unknown'}])
def test_invalid_curation_is_rejected(value):
    with pytest.raises(ValueError):strip_curation(value)


@pytest.mark.parametrize('value',[[dict(id='a',name='a',source='x',is_default=1)],[dict(id='a',name='a',source='x',is_default=True),dict(id='b',name='b',source='y',is_default=True)],[dict(id='a',name='',source='x')],[dict(id='a',name='a',source='x'),dict(id='a',name='b',source='y')]])
def test_template_ids_names_defaults_are_validated(value):
    with pytest.raises(ValueError):narrative_templates(value)


def test_strip_project_only_changes_channel_view_and_cancel_snapshot_is_detached():
    result=node("""
require('./static/js/report-engine.js');require('./static/js/report-strip-editor.js');
const a=ECGReportStripEditor,beat={sample_index:100,rr_ms:800,hr:75},source={strip:{leads:['II','V1','V5']},waveform:{start_s:0,duration_s:7,beats:[beat],leads:{II:[0,-900,2500],V1:[0,500,-200],V5:[0,-800,400],I:[1,2,3]}}};
const before=JSON.stringify(source),view=a.project(source);const next=a.draft({event_id:'same',basis_version:'b',leads:['II'],duration_s:7},source,{caption:'math',start_s:1.005,duration_s:7.005,leads:['V5','II'],notes:'n',preview_lead:'V5',print_enabled:false},30);
let missing=false;try{a.project(source,['V6']);}catch(_){missing=true;}
console.log(JSON.stringify({names:Object.keys(view.waveform.leads),sameRows:view.waveform.beats===source.waveform.beats,sameSamples:view.waveform.leads.II===source.waveform.leads.II,before:before===JSON.stringify(source),missing,next}));
""")
    assert result['names']==['II','V1','V5']
    assert result['sameRows'] and result['sameSamples'] and result['before'] and result['missing']
    assert result['next']['range_start_s']==1.005 and result['next']['range_end_s']==8.01
    assert result['next']['leads']==['II','V5'] and not result['next']['print_enabled']


def test_template_parser_has_no_script_execution_and_distinguishes_missing_zero():
    result=node("""
require('./static/js/report-narrative-templates.js');const a=ECGReportNarrative,fields={ZERO:{value:0,status:'available'},N:{value:5,status:'available'},M:{value:null,status:'unavailable'}};
const rendered=a.render('{{ZERO}} / {{M}} {{#if ZERO}}正常{{/if}}{{#if N}}共{{N}}搏{{#if M}}正常{{/if}}{{/if}}',fields),errors=[];
for(const source of ['<SKScript>throw new Error()</SKScript>','<script>evil()</script>','{{UNKNOWN}}','{{#if N}}x','{{/if}}','{{N']){try{a.render(source,fields);errors.push(false);}catch(_){errors.push(true);}}
console.log(JSON.stringify({rendered,errors}));
""")
    assert result['rendered']['text']=='0 / —（未提供） 共5搏'
    assert result['rendered']['unavailable']==['M'] and all(result['errors'])


def test_generated_catalog_uses_current_statistics_not_source_summary():
    result=node("""
require('./static/js/report-engine.js');require('./static/js/report-strip-editor.js');require('./static/js/report-narrative-templates.js');
const fields=ECGReportNarrative.fields({caseData:{metadata:{start_time:'2026-01-01 23:59:00'},technical:{duration_seconds_raw:120,independent_channels:8},summary:{avg_hr:999}},statistics:{summary:{total:20,avg_hr:74.5,min_hr:40.01,max_hr:120.49,slowest:{time_s:1},fastest:{time_s:60},longest:{rr_ms:3000,time_s:90},S:{total:2,couplet:1,run:0},V:{total:1,couplet:0},af:0,pause:1}}});console.log(JSON.stringify(fields));
""")
    assert result['HR_Aver']['value']==75 and result['HR_Max']['value']==120
    assert result['Rec_Ed_Day']['value']=='2026-01-02'
    assert result['Rec_Channel_Count']['value']==8 and '12' in result['Rec_Channel_Count']['remark']
    assert result['Rec_Time_Span_Invalid']['status']=='unavailable'
    assert result['S_Run_Fast_HR']['status']=='unavailable'
    assert result['LG_RR']['unit']=='ms' and '非手选' in result['LG_RR']['source']


def test_cancel_print_filters_pdf_and_web_but_keeps_saved_selection_and_note():
    enabled=sample_entry();enabled.update(caption='MATH_VISIBLE',notes='MATH_LOCAL_NOTE')
    disabled=copy.deepcopy(enabled);disabled.update(caption='MATH_HIDDEN',print_enabled=False,notes='HIDDEN_NOTE')
    model={'case':{'case_id':'MATH','metadata':{}},'statistics':{},'report':{'status':'draft','conclusion':'math','composition':{'included_pages':['event_strips'],'page_selection_version':1,'paper':{}},'selected_waveforms':[enabled,disabled]}}
    original=copy.deepcopy(model)
    _register_font();pdf=build_paper_pdf(model['case'],model['report'],FONT_NAME)
    text=subprocess.check_output(['pdftotext','-','-'],input=pdf.getvalue()).decode('utf-8')
    assert 'MATH_VISIBLE' in text and 'MATH_LOCAL_NOTE' in text
    assert 'MATH_HIDDEN' not in text and 'HIDDEN_NOTE' not in text
    result=node("require('./static/js/clinical-review-tools.js');require('./static/js/report-paper.js');const input=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify({html:ECGReportPaper.stripPages(input.model,input.entries)}));",{'model':model,'entries':[enabled,disabled]})
    assert 'MATH_VISIBLE' in result['html'] and 'MATH_LOCAL_NOTE' in result['html']
    assert 'MATH_HIDDEN' not in result['html'] and 'HIDDEN_NOTE' not in result['html']
    assert model==original


def test_report_range_labels_keep_sample_precision_without_mutating_timing():
    result=node("require('./static/js/report-workspace.js');console.log(JSON.stringify([16.5,20.495,86400.005].map(ECGReportWorkspace.preciseTime)));")
    assert result==['D1 00:00:16.500','D1 00:00:20.495','D2 00:00:00.005']


def test_rr_candidates_follow_pause_in_type_order_and_keep_entry_settings():
    result=node("""
require('./static/js/report-workspace.js');const picks=[{event_id:'r',leads:['II','V1','V5'],range_start_s:16.5},{event_id:'s',leads:['II']},{event_id:'f',leads:['I','II']},{event_id:'p',leads:['V5']}],lookup=new Map([['r',{category:'rr_candidate',subtype:'manual_rr',time_s:20.495}],['s',{category:'S',subtype:'single',time_s:6.28}],['f',{category:'fastest',subtype:'RR',time_s:63.495}],['p',{category:'pause',subtype:'pause',time_s:20.495}]]);const before=JSON.stringify(picks),out=ECGReportWorkspace.sortSelections(picks,lookup,'type');console.log(JSON.stringify({ids:out.map(p=>p.event_id),sameR:out[3]===picks[0],unchanged:JSON.stringify(picks)===before}));
""")
    assert result==dict(ids=['f','s','p','r'],sameR=True,unchanged=True)


def test_stale_card_allows_recoverable_removal_without_reenabling_waveform_actions():
    result = node("""
const fs=require('fs'),vm=require('vm'),source=fs.readFileSync('static/js/report-workspace.js','utf8');
const start=source.indexOf('  function stripActions('),end=source.indexOf('  function compose(',start),context=vm.createContext({});
if(start<0||end<start)throw Error('Missing production strip actions');
vm.runInContext(source.slice(start,end),context);
const actions=status=>[...context.stripActions(2,status).matchAll(/<button[^>]*data-rw-strip-action="([^"]+)"[^>]*>/g)].map(m=>({action:m[1],disabled:m[0].includes(' disabled')}));
console.log(JSON.stringify({stale:actions('stale'),pending:actions('pending'),confirmed:actions('confirmed')}));
""")
    assert len(result['stale']) == 8
    assert [row['action'] for row in result['stale'] if not row['disabled']] == ['remove']
    assert all(not row['disabled'] for row in result['pending'] + result['confirmed'])
