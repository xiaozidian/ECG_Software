"""Independent stdlib scalar ST mean for the exact immutable mathematical M01.

No ecg_core/stt, range, vectorized production helper or returned native landmark
is imported. This is an engineering arithmetic oracle, never a diagnosis oracle.
"""
from __future__ import annotations
import argparse
from collections import Counter
from hashlib import sha256
import json
import math
import mmap
from pathlib import Path
import statistics
import struct

LEADS=('I','II','III','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6')
STORED=frozenset(('I','II','V1','V2','V3','V4','V5','V6'))
CASE='9900000000000001'
FRAME=struct.Struct('<8h')
EBI=struct.Struct('<IHHIIII')
RAW_SHA='6ff29e88a424b6bda832002e2f7db8833d5e9901ac7e1eb2bad03c13b401a966'
EBI_SHA='7e1dfbd28973d7307290af38796d1a16c47eaedfb51767dcfec7b8828cccc197'
BASE=(-40,-36,-32,-28,-24)
ST=(-2,-1,0,1,2)


def digest(path):
    h=sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def derived(frame):
    i,ii,*chest=frame
    return (i,ii,ii-i,-(i+ii)/2,i-ii/2,ii-i/2,*chest)


def median(values):return statistics.median(values)
def mad(values):
    center=median(values)
    return median([abs(x-center) for x in values])


def j_landmark(read,representatives):
    energies=[]
    for offset in range(33):
        changes=[]
        for sample,_,_ in representatives:
            a,b=read(sample+offset),read(sample+offset-1)
            changes.extend(abs(a[i]-b[i]) for i in (1,6,10))
        energies.append(median(changes))
    peak_index=max(range(21),key=lambda i:energies[i])
    peak,noise=energies[peak_index],median(energies[-8:])
    threshold=max(2.,2.5*noise,.12*peak)
    for index in range(max(8,peak_index+2),29):
        if all(x<=threshold for x in energies[index:index+4]):return index
    return 18


def lead_quality(read,reps,j,population,normal_count):
    observations={lead:{'baseline':[],'span':[],'qrs':[],'clipped':False} for lead in LEADS}
    for sample,_,_ in reps:
        bases=[read(sample+offset) for offset in BASE]
        qrs=[read(sample+offset) for offset in range(-8,j+1,2)]
        for column,lead in enumerate(LEADS):
            values=[frame[column] for frame in bases];q=[frame[column] for frame in qrs];row=observations[lead]
            row['baseline'].append(median(values));row['span'].append(max(values)-min(values));row['qrs'].append(max(q)-min(q))
            row['clipped']=row['clipped'] or (lead in STORED and any(v<=-32768 or v>=32767 for v in q))
    scores={};measurable={};eligible={}
    for lead,obs in observations.items():
        qrs=median(obs['qrs']);baseline_variation=mad(obs['baseline'])+median(obs['span']);qrs_variation=mad(obs['qrs'])/max(qrs,1.)
        score=max(0.,min(1.,1.-min(.65,baseline_variation/max(qrs,40.))-min(.35,qrs_variation)))
        scores[lead]=score;measurable[lead]=qrs>0 and not obs['clipped'];eligible[lead]=measurable[lead] and score>=.42
    limb_available=measurable['I'] and measurable['II']
    for lead in ('III','aVR','aVL','aVF'):eligible[lead]=limb_available and scores[lead]>=.42
    ratio=normal_count/max(population,1);overall=max(0.,min(1.,median(list(scores.values()))*min(1.,ratio/.6)))
    return ratio>=.35 and overall>=.42,eligible,overall


def calculate(read,records,total_samples,*,start=0,end=12000,measurement_ms=60):
    assert 0<=start<end<=total_samples and end-start>=12000
    assert measurement_ms in (0,60,80)
    by_block={}
    for row in records:
        if 0<=row[0]<total_samples:by_block.setdefault(row[0]//3200,[]).append(row)
    values={lead:[] for lead in LEADS};anchors={lead:[] for lead in LEADS};counts=Counter();reasons=Counter();blocks=[]
    for index in range(start//3200,(end-1)//3200+1):
        rows=by_block.get(index,[]);states={};candidates=[]
        for n,row in enumerate(rows):
            sample,group,rr=row;previous=rows[n-1][1] if n else None;following=rows[n+1][1] if n+1<len(rows) else None
            if group!=1:states[sample]=('excluded','non_n_candidate')
            elif previous in (3,34) or following in (3,34):states[sample]=('excluded','adjacent_v_or_artifact')
            elif not 350<=rr<=2000:states[sample]=('excluded','rr_outside_legacy_bounds')
            elif sample<50 or sample+120>=total_samples:states[sample]=('missing','source_edge_guard_unavailable')
            else:candidates.append(row)
        reps=candidates if len(candidates)<=7 else [candidates[round(k*(len(candidates)-1)/6)] for k in range(7)]
        block={'block_index':index,'j_representative_samples':[r[0] for r in reps],'candidate_count':len(candidates)}
        if len(reps)<3:
            for r in candidates:states[r[0]]=('missing','j_unavailable')
            block.update(j_offset_samples=None,eligible=False)
        else:
            j=j_landmark(read,reps);population=sum(r[1]!=34 for r in rows);good,per_lead,score=lead_quality(read,reps,j,population,len(candidates));block.update(j_offset_samples=j,eligible=good,quality_score=round(score,3),lead_eligible=per_lead)
            for r in candidates:states[r[0]]=('used','used') if good else ('excluded','engineering_quality_gate')
            if good:
                offset=j+measurement_ms//5
                for sample,_,_ in candidates:
                    if not start<=sample<end:continue
                    bases=[read(sample+x) for x in BASE];st=[read(sample+offset+x) for x in ST]
                    for column,lead in enumerate(LEADS):
                        if per_lead[lead]:values[lead].append(median([f[column] for f in st])-median([f[column] for f in bases]));anchors[lead].append(sample)
        for sample,_,_ in rows:
            if start<=sample<end:
                status,reason=states[sample];counts[status]+=1
                if status!='used':reasons[reason]+=1
        blocks.append(block)
    return {'range':{'start_sample':start,'end_sample':end,'duration_s':(end-start)/200,'half_open':True},'counts':{'detected_count':sum(counts.values()),'used_count':counts['used'],'excluded_count':counts['excluded'],'missing_count':counts['missing'],'reason_counts':dict(reasons)},'leads':[{'lead':lead,'mean_units':math.fsum(v)/len(v) if v else None,'used_count':len(v),'unit':'u'} for lead,v in values.items()],'blocks':blocks,'used_anchors':anchors}


def verify_source(root):
    manifest=json.loads((root/'source-manifest.json').read_text());assert manifest['kind']=='mathematical_synthetic' and manifest['wholly_synthetic'] is True and manifest['patient_inputs_read'] is False
    assert manifest['case_id']==CASE and manifest['sampling_rate_hz']==200 and manifest['sample_count']==17280000
    raw=root/CASE/'data'/f'{CASE}.DATA';ebi=root/CASE/'DGS'/f'{CASE}.EBI'
    assert raw.stat().st_size==276480000 and digest(raw)==RAW_SHA and digest(ebi)==EBI_SHA
    data=ebi.read_bytes();assert data[:32].rstrip(b'\0')==b'SYNTHETIC_DOCTOR_24H_V1' and (len(data)-32)%EBI.size==0
    rows=[(r[0],r[2],r[6]) for r in EBI.iter_unpack(data[32:])]
    assert len(rows)==100051 and all(a[0]<b[0] for a,b in zip(rows,rows[1:]))
    return raw,rows


def main(root,output):
    raw,records=verify_source(root)
    with raw.open('rb') as stream,mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ) as buffer:
        read=lambda sample:derived(FRAME.unpack_from(buffer,sample*16))
        result=calculate(read,records,17280000)
        representative_set={r for block in result['blocks'] for r in block['j_representative_samples']}
        anchor=next(sample for sample in result['used_anchors']['II'] if sample not in representative_set)
        block=next(b for b in result['blocks'] if b['block_index']==anchor//3200);support={anchor+block['j_offset_samples']+12+x for x in ST}
        def altered(sample):
            frame=list(FRAME.unpack_from(buffer,sample*16))
            if sample in support:frame[1]+=10
            return derived(frame)
        changed=calculate(altered,records,17280000)
        a=next(x for x in result['leads'] if x['lead']=='II');b=next(x for x in changed['leads'] if x['lead']=='II')
        assert result['counts']==changed['counts'] and [b['j_offset_samples'] for b in result['blocks']]==[b['j_offset_samples'] for b in changed['blocks']]
        delta=b['mean_units']-a['mean_units'];expected_delta=10/a['used_count'];assert abs(delta-expected_delta)<1e-12
    record={'schema':'independent-M01-full-minute-ST-scalar-oracle-v1','source':'original immutable mathematical M01','source_raw_sha256':RAW_SHA,'source_EBI_sha256':EBI_SHA,'source_total_samples':17280000,'source_duration_s':86400,'profile_expected':'raw-200hz-fixed16s-st-perbeat-morphology-v3','oracle_dependencies':'stdlib struct, statistics, math, mmap only; no production measurements or returned landmarks/counts used','scope':'Exact no-explicit-mask ST mean/count/J/lead availability only, not T morphology or diagnosis. Complete fixed blocks are read, including 60–64s for the final partial requested block.','clinical_validation':False,'patient_inputs_read':False,'result':result,'negative_control':{'kind':'in-memory +10 stored II units at all five ST support samples of one used non-J-representative beat','source_file_modified':False,'anchor':anchor,'J_and_counts_unchanged':True,'actual_II_mean_shift':delta,'expected_II_mean_shift':expected_delta,'proves_nonrepresentative_beats_participate':True}}
    output.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'counts':result['counts'],'J_offsets':[b['j_offset_samples'] for b in result['blocks']],'means':result['leads'],'negative_control_mean_shift':delta},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args();main(args.source_root,args.output)
