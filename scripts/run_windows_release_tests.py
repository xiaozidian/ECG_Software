"""Execute and accurately account for the current release's non-PDF scope."""
import argparse,json,os,subprocess,sys,xml.etree.ElementTree as ET
from pathlib import Path
KNOWN={
 'test_candidate_thresholds_match_unchanged_frozen_development',
 'test_current_workstation_cannot_masquerade_as_frozen_development',
}
def main(output):
 output.mkdir(parents=True,exist_ok=True)
 os.environ['ECG_WINDOWS_TEST_SCOPE_RECEIPT']=str(output/'test-scope.json')
 tests=json.loads(Path('scripts/windows_release_test_scope.json').read_text())
 suite=output/'scoped-tests.xml'
 run=subprocess.run([sys.executable,'-m','pytest','-p','scripts.windows_no_pdf_tests','-q',*tests,'--junitxml='+str(suite)])
 assert suite.is_file(),'Scoped tests did not finish'
 nodes=list(ET.parse(suite).getroot().iter('testcase'))
 counts={'total':len(nodes),'passed':sum(not any(t.find(k) is not None for k in ['failure','error','skipped']) for t in nodes),
  'failed':sum(t.find('failure') is not None for t in nodes),'error':sum(t.find('error') is not None for t in nodes),'skipped':sum(t.find('skipped') is not None for t in nodes)}
 af=output/'historical-af.xml'
 af_run=subprocess.run([sys.executable,'-m','pytest','-q',*[f'tests/test_ltafdb_validation.py::{name}' for name in sorted(KNOWN)],'--junitxml='+str(af)])
 assert af.is_file(),'Historical AF tests did not finish'
 af_nodes=list(ET.parse(af).getroot().iter('testcase'));assert len(af_nodes)==2
 historical=[];unexplained=[]
 for node in af_nodes:
  failed=node.find('failure');error=node.find('error')
  item={'name':node.get('name'),'status':'passed'}
  if failed is not None or error is not None:
   failure=failed if failed is not None else error;text=(failure.text or '')+' '+failure.get('message','')
   if node.get('name') in KNOWN and 'FileNotFoundError' in text and 'summary.json' in text:
    item.update(status='missing_historical_material',reason='Frozen-development summary.json is absent; downstream threshold/provenance assertions have not run')
   else:item.update(status='failed');unexplained.append(node.get('name'))
  historical.append(item)
 receipt={'status':'passed' if run.returncode==0 and not unexplained else 'failed','scope':'related application and Windows packaging tests; full repository suite not run',
  'current':counts,'historical_af':historical,'unexplained_af_failures':unexplained,
  'full_suite_green':False if any(x['status']!='passed' for x in historical) else None,
  'pdf_open_export_download_run':False,'clinical_validation':False}
 (output/'test-summary.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt));return 0 if receipt['status']=='passed' else 1
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);raise SystemExit(main(p.parse_args().output))
