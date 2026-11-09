"""Pin immutable15 P01 migration input and unchanged M01 source, not test reuse."""
from pathlib import Path
import argparse,json,zipfile,sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.prepare_ui15_baseline import api,download,dump,one,read
from scripts.prepare_ui15_final_upgrade import producer
from scripts.windows_doctor_build import digest,validate_source

REPO='xiaozidian/ECG_Software'
P01='e4b05f506a363ae89ee44ab44a9540dbe640848a4e5178a406fc8a023d952462'
MATH='3b09e147add5a794800bc0be400ec57c347077c47546cc67c5593b3bedd745d0'


def prepare(args):
    assert not args.output.exists(),'Preserve earlier baseline evidence'
    args.output.mkdir(parents=True)
    contract=read(ROOT/'scripts/ui15-final-upgrade-contract.json')
    original,rows=producer(contract)  # actual original failure15 and passed1–14
    accepted=api(REPO,'/actions/runs/42506121783')
    assert (accepted['status'],accepted['conclusion'],accepted['head_sha'])==('completed','success','b4895c0a4002403015c0a075ece53669b8fad5ed')
    paths={};outer={}
    for role in ('p01','math'):
        row=next(r for r in rows if contract['outer_artifacts'][r['name']]['role']==role)
        outer[role]=download(REPO,{**row,'bytes':row['size_in_bytes']},args.output/role)
        name='CardioInsight-DoctorEval-Windows-x64-1.0.15-P01-software.zip' if role=='p01' else 'CardioInsight-Synthetic-M01-24h-v1.zip'
        path=one(args.output/role,name);expected=P01 if role=='p01' else MATH
        assert digest(path)==expected and path.with_name(path.name+'.sha256').read_text().split()==[expected,name]
        paths[role]=str(path)
    source=args.output/'original-source'
    with zipfile.ZipFile(paths['math']) as archive:
        assert archive.testzip() is None
        for info in archive.infolist():
            assert not info.is_dir() and info.filename.startswith('M01/')
            assert not Path(info.filename).is_absolute() and '..' not in Path(info.filename).parts and '\\' not in info.filename
        archive.extractall(source)
    manifest=validate_source(source/'M01');paths['math_source']=str(source/'M01')
    value=dict(status='immutable15-base-and-original-M01-input-verified-only',purpose='prior software is a migration fixture; no old test counts are new17 acceptance',
        producer={k:original[k] for k in ('id','head_sha','conclusion','status','html_url','path')},producer_passed_steps='1–14',producer_original_failed_step=15,
        accepted15_QA={k:accepted[k] for k in ('id','head_sha','conclusion','status','html_url')},outer_artifacts=outer,paths=paths,
        P01_SHA256=P01,M01_archive_SHA256=MATH,source_manifest_sha256=digest(source/'M01/source-manifest.json'),patient_inputs_read=False)
    dump(args.output/'baseline17-input.json',value);print(json.dumps(value))


def validate_final(args):
    baseline=read(args.baseline_proof);source=Path(baseline['paths']['math_source'])
    package=args.package_root/'Sources/M01'
    left={p.relative_to(source).as_posix():digest(p) for p in source.rglob('*') if p.is_file()}
    right={p.relative_to(package).as_posix():digest(p) for p in package.rglob('*') if p.is_file()}
    assert left==right and len(left)==5
    assert digest(Path(baseline['paths']['math']))==MATH
    dump(args.output,dict(status='passed',full17_source_payload_exactly_original_M01=True,source_payload_sha256=right,
         delivered_source_archive_sha256=MATH,delivered_archive_is_original15_bytes=True,
         note='Build may create an internal source ZIP with new ZIP timestamps; it is not delivered. Delivery uses the immutable original source ZIP.',clinical_validation=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--baseline-proof',type=Path);p.add_argument('--package-root',type=Path)
    a=p.parse_args()
    if a.package_root:validate_final(a)
    else:prepare(a)
