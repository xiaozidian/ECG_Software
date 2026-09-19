"""Generate a deterministic, non-patient PDF for report layout regression."""
from __future__ import annotations
import argparse
import math
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ecg_core.clinical_analysis import build_index
from ecg_core.report_layout import LEADS, prepare_strip, report_statistics
from ecg_core.report_pdf import build_report_pdf
from ecg_core.beat_editor import edited_hrv


def fixture():
    duration=24*3600
    times=list(range(100, int(duration*200), 200))
    rows=[dict(id=f't:{s}',sample_index=s,class_code='V' if i%900==0 else 'S' if i%707==0 else 'N',rr_ms=1000 if i else 0,hr=60 if i else None) for i,s in enumerate(times)]
    settings=dict(nn_min=300,nn_max=2000,pause=2.5,tachy=120,brady=50)
    feed=SimpleNamespace(beats=rows,markers=[],duration=duration,document={'settings':settings})
    index=build_index(feed)
    def reader(start,end,leads,max_points):
        count=round((end-start)*200);stride=max(1,math.ceil(count/max_points))
        values=[]
        for i in range(0,count,stride):
            t=(start+i/200)%1-.5
            values.append(850*math.exp(-(t/.018)**2)-190*math.exp(-((t-.035)/.025)**2)+160*math.exp(-((t-.25)/.07)**2)+50*math.exp(-((t+.2)/.04)**2))
        return dict(start_s=start,duration_s=round(end-start,3),display_sample_rate_hz=200/stride,leads={lead:[v*(-.5 if lead in ['aVR','V1'] else .7 if lead in ['III','aVL'] else 1) for v in values] for lead in leads})
    picks=[]
    for i in range(4):
        event=dict(event_id=f'fixture-{i}',start_sample=(60+i*60)*200,time_s=60+i*60,hr=60,caption=['最快心率 · 版式测试','最慢心率 · 版式测试','最长 RR · 版式测试','12 导联 · 版式测试'][i],label='版式测试')
        picks.append(prepare_strip(index,event,{'leads':LEADS if i==3 else ['II','V1','V5'],'duration_s':7},reader))
    case={'case_id':'report-layout-test','metadata':{'name':'排版测试','patient_id':'TEST-ONLY','sex':'—','age':'—','start_time':'2026-09-19 08:15:00','duration_text':'24小时','department':'测试科室','clinical_diagnosis':'仅用于版式与分页验证'},'summary':{}}
    statistics=report_statistics(index,case['metadata']['start_time'],settings);statistics['hrv']=edited_hrv(feed)
    report={'status':'draft','version':1,'conclusion':'布局验证样本，不代表患者或临床诊断。\n1. 检查信息、统计和结论分区排列。\n2. 核对各图条的导联、时间和网格比例。','composition':{'diagnosis_blocks':[],'paper':{'size':'A4','orientation':'portrait','gain':'10 mm/mV'}},'selected_waveforms':picks,'paper_statistics':statistics}
    return case,report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--long-caption',action='store_true')
    args=parser.parse_args()
    case,report=fixture()
    if args.long_caption:report['selected_waveforms'][0]['caption']='长图注完整性验证。'*40
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_bytes(build_report_pdf(case,{},report).getvalue())
    print(args.output)
