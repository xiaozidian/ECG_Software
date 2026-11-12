"""A narrow internal read must equal the full analysis and never alias its cache."""
from copy import deepcopy
import numpy as np
from ecg_core.stt import analyze_stt, _CACHE


def test_trend_projection_matches_full_cold_and_warm_detached(tmp_path):
    path=tmp_path/'synthetic.DATA'
    rate=200;seconds=70;signal=np.zeros((rate*seconds,8),dtype='<i2')
    for anchor in range(200,len(signal)-160,200):
        signal[anchor:anchor+3,:]=900
        signal[anchor+20:anchor+35,:]=130
        signal[anchor+55:anchor+67,:]=190
    path.write_bytes(signal.tobytes())
    beats=[(s,0,1,0,0,0,1000) for s in range(200,len(signal)-160,200)]
    options={'analysis_revision':'engineering-projection'}
    _CACHE.clear()
    projected=analyze_stt(path,beats,seconds,project=lambda a:a['trends']['leads'],**options)
    full=analyze_stt(path,beats,seconds,**options)
    assert projected==full['trends']['leads']
    original=deepcopy(projected)
    lead=next(iter(projected));projected[lead][0]['start_s']=-12
    full['trends']['leads'][lead][0]['end_s']=-21
    assert analyze_stt(path,beats,seconds,project=lambda a:a['trends']['leads'],**options)==original
    # An edited middle beat must bind a distinct algorithm cache entry.
    changed=list(beats);middle=len(changed)//2
    changed[middle]=(changed[middle][0],0,2,0,0,0,1000)
    analyze_stt(path,changed,seconds,project=lambda a:a['trends']['leads'],**options)
    assert len(_CACHE)==2
