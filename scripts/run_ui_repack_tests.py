"""Fresh Windows JS/CSS/HTML wrapper regressions; unchanged backend reused separately."""
from pathlib import Path
import argparse,json,subprocess,sys,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
def main(a):
 selection=json.loads((ROOT/'scripts/ui-regression-selection.json').read_text())
 a.output.mkdir(parents=True,exist_ok=True);suite=a.output/'ui-repack-tests.xml'
 run=subprocess.run([sys.executable,'-m','pytest','-p','scripts.ui_no_pdf_tests','-p','no:cacheprovider','-q',*selection['test_nodes'],'--junitxml='+str(suite)],cwd=ROOT)
 assert suite.is_file();nodes=list(ET.parse(suite).iter('testcase'))
 counts={'total':len(nodes),'passed':sum(not any(n.find(k)is not None for k in ['failure','error','skipped']) for n in nodes),'failed':sum(n.find('failure')is not None for n in nodes),'error':sum(n.find('error')is not None for n in nodes),'skipped':sum(n.find('skipped')is not None for n in nodes)}
 r={'status':'passed' if run.returncode==0 else 'failed','scope':'fresh Windows UI2 actual JS/CSS/HTML extraction and browser wrappers; backend/perf reuse is explicit separate receipt','declared_test_functions':len(selection['test_nodes']),'file_count':selection['file_count'],'current':counts,'test_nodes':selection['test_nodes'],'not_run_actual_PDF_generation':selection['not_run_actual_PDF_generation'],'mocked_JS_print_and_curation_checks_retained':True,'full_backend_scope_rerun':False,'clinical_validation':False}
 (a.output/'ui-test-summary.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in r.items() if k!='test_nodes'}));return run.returncode
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);raise SystemExit(main(p.parse_args()))
