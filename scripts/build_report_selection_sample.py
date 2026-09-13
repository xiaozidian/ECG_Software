"""Build a reproducible report from the already-public Demo waveform and index.

No patient source files or local configuration are copied. The output is a draft
for software acceptance, not a physician-reviewed diagnosis.
"""
from pathlib import Path
import json
import subprocess
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ecg_core.clinical_analysis import build_index,query_index,hrv_windows
from ecg_core.report_pdf import build_report_pdf
from ecg_core.waveform import read_event_waveform
from ecg_core.storage import normalize_report_composition


def build(output):
    script="""global.window={};require('./demo/static/demo-data/uploaded-sim-af-001/case-data.js');const E=require('./static/js/beat-engine.js');const c=window.__CARDIOINSIGHT_UPLOADED_CASE__;const f=E.materialize(c.beats,E.blank(),[]);f.duration=c.technical.duration_seconds_raw;process.stdout.write(JSON.stringify({case:c,feed:f}));"""
    value=json.loads(subprocess.check_output(['node','-e',script],cwd=ROOT))
    case=value['case'];feed=SimpleNamespace(**value['feed'])
    review={'steps':{'edit':{'status':'done','note':'自动化样例'},'stt':{'status':'done','note':'自动化样例'}}}
    start,end=case['simulation_profile']['rhythm_candidate_windows_s'][0]
    candidate={'id':-1,'sample_index':start*200,'details':{'kind':'AF','status':'pending','end_sample':min(int(feed.duration*200)-1,int(end*200)),'finding':'房颤候选片段'}}
    index=build_index(feed,annotations=[candidate],review=review)
    singles=query_index(index,{'category':'S','mode':'single'})['items'][:2]
    triple=query_index(index,{'category':'S','mode':'triplet'})['items'][:1]
    chosen=singles+triple
    assert len(chosen)==3,'Published fixture must have two singles and a triple'
    composition=normalize_report_composition({'selected_events':[{'event_id':e['event_id'],'basis_version':e['basis_version'],'caption':e['label']} for e in chosen], 'diagnosis_blocks':[{'key':f"S:{sub}",'text':label} for sub,label in [('single','单发房早'),('triplet','连续三发房早')]],'paper':{'size':'A4','orientation':'portrait'}})
    waves=[{**e,'caption':e['label'],'waveform':read_event_waveform(ROOT/'demo/static/demo-data/uploaded-sim-af-001/waveform.bin',max(0,e['time_s']-.8),e['end_s']+1.6)} for e in chosen]
    stats=query_index(index,{'category':'S'})
    report={'version':1,'status':'draft','reviewed_by':'','composition':composition,'conclusion':'软件验收样例：使用已公开的10分钟Demo波形，展示独立入报选择。未经过临床审核。','selected_waveforms':waves,'event_statistics':stats,'hrv_windows':hrv_windows(feed,case['metadata']['start_time'])}
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    (output/'report-selection-sample.pdf').write_bytes(build_report_pdf(case,{},report).getvalue())
    # Observable data only; no copied patient metadata.
    receipt={'fixture':'existing public 10-minute Demo','status':'draft','selected_strips':len(chosen),'diagnosis_blocks':composition['diagnosis_blocks'],'all_S_events':stats['category_counts']['S'],'all_S_beats':stats['beat_counts']['S'],'selected_events':composition['selected_events'],'hrv':report['hrv_windows']}
    (output/'report-selection-sample.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
    print(f"3 strips / 2 diagnosis blocks; complete S statistics {receipt['all_S_events']} events / {receipt['all_S_beats']} beats")

if __name__=='__main__':build(sys.argv[1] if len(sys.argv)>1 else ROOT/'docs/acceptance/interaction-report-v2')
