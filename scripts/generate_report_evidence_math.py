"""Independent 600-second mathematical ST/T+RR fixture; no recorded source read.

This supplements, never replaces or alters, the retained 24-hour native M01.
"""
from hashlib import sha256
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
import numpy as np

CASE_ID = '9900000000000001'
DURATION = 600
RATE = 200


def generate(output):
    output = Path(output)
    assert not output.exists(), 'Keep previous mathematical attempts'
    paths = {kind: output/CASE_ID/folder/name for kind,folder,name in [
        ('data','data',CASE_ID+'.DATA'),('ebi','DGS',CASE_ID+'.EBI'),
        ('lps','report_image',CASE_ID+'_1.LPS')]}
    for p in paths.values(): p.parent.mkdir(parents=True,exist_ok=True)
    rows=[];sample=200;rr=0
    while sample<DURATION*RATE:
        rows.append((sample,rr))
        rr=4000 if len(rows)==21 else 4500 if len(rows)==41 else 1000
        sample+=rr//5
    paths['ebi'].write_bytes(bytes(32)+b''.join(struct.pack('<IHHIIII',s,1,1,0,0,0,r) for s,r in rows))
    times=np.arange(DURATION*RATE)/RATE
    values=np.full((DURATION*RATE,8),3000.,dtype=np.float64)
    values+=(2*np.sin(2*np.pi*times/60))[:,None]
    gains=np.array([.5,1,-.8,.7,.8,.9,1,.75])
    for s,_ in rows:
        lo,hi=max(0,s-70),min(len(values),s+140);t=(np.arange(lo,hi)-s)/RATE
        qrs=900*np.exp(-.5*(t/.012)**2)-120*np.exp(-.5*((t+.025)/.009)**2)-250*np.exp(-.5*((t-.028)/.012)**2)
        p=90*np.exp(-.5*((t+.15)/.04)**2)
        twave=(-1 if 400<=s/RATE<512 else 1)*190*np.exp(-.5*((t-.31)/.055)**2)
        values[lo:hi]+=(qrs+p+twave)[:,None]*gains
        plateau=((t>=.08)&(t<=.25)).astype(float)
        if 120<=s/RATE<360: values[lo:hi,1]-=plateau*280
        if 180<=s/RATE<360: values[lo:hi,6]-=plateau*230
    paths['data'].write_bytes(np.rint(values).astype('<i2').tobytes())
    root=ET.Element('LrScriptPage');shapes=ET.SubElement(root,'ShapeList')
    texts=['姓名：数学验收M01','记录时间：2026-01-01 08:00:00','记录时长：0小时10分钟',
        '总心搏数：'+str(len(rows)),'室性心搏：0','室上性心搏：0','最慢心率：13',
        '平均心率：'+str(round(len(rows)/10)),'最快心率：60','最长RR间期：4.5s']
    for i,text in enumerate(texts):ET.SubElement(shapes,'PShape',SPTYPE='3',CRECT=f'100,{100+i*80},2200,{160+i*80}').text=text
    ET.SubElement(shapes,'PShape',SPTYPE='3',CRECT='100,2050,2200,2110').text='报告结论'
    ET.SubElement(shapes,'PShape',SPTYPE='3',CRECT='100,2140,2200,2200').text='全新数学函数生成；不对应患者，不构成疾病金标准。'
    ET.ElementTree(root).write(paths['lps'],encoding='utf-16',xml_declaration=True)
    manifest={'profile':'report-evidence-mathematical-600s-v1','kind':'mathematical_synthetic',
        'wholly_synthetic':True,'patient_inputs_read':False,'clinical_validation':False,
        'case_id':CASE_ID,'duration_seconds':DURATION,'sample_rate_hz':RATE,'channel_count':8,
        'source_waveform_copied':False,'unchanged_24h_generator':True,
        'design_only':{'II_ST_plateau_s':[120,360],'V5_ST_plateau_s':[180,360],
            'T_polarity_s':[400,512],'RR_ms':[4000,4500]},
        'files':{p.relative_to(output).as_posix():{'bytes':p.stat().st_size,'sha256':sha256(p.read_bytes()).hexdigest()} for p in paths.values()}}
    (output/'source-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return manifest
