"""Freeze an explicit tested implementation and published reference engines.

Only code manifests enter the policy. No case IDs, inputs, annotations, doctor
names or medical data are read from clinical records by this build tool.
"""
from pathlib import Path
import argparse,importlib.util,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ecg_core.analysis_provenance import MODULES
from ecg_core.performance_compatibility import POLICY_SCHEMA,code_fingerprints,digest
def build(root,parents):
    names=("app",)+tuple("ecg_core."+n for n in MODULES)
    engines=[]
    for value in parents:
        if set(value)<={"app_version","artifacts","dependencies","sample_rate_hz","channels","input_format"} and "artifacts" in value:
            engines.append(value)
        else:raise ValueError("仅接受已发布程序engine清单，不接受病例或临床数据")
    if not engines:raise ValueError("需要明确的已发布父程序清单")
    policy=dict(schema=POLICY_SCHEMA,current_code=code_fingerprints(root,names),
                parent_engine_ids=sorted({digest(e) for e in engines}),
                parent_engines=sorted(engines,key=digest))
    return policy
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=ROOT)
    p.add_argument('--parents',type=Path,required=True);p.add_argument('--output',type=Path)
    args=p.parse_args();values=json.loads(args.parents.read_bytes())
    if isinstance(values,dict):values=[values]
    value=build(args.source.resolve(),values)
    out=args.output or args.source/'performance-compatibility.json'
    out.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    print("Frozen",len(value['current_code']),"modules and",len(value['parent_engine_ids']),"published parent engines")
