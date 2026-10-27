"""Read the still-retained, digest-pinned official 1.0.2 artifact for upgrade QA."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,subprocess,zipfile
REPO='xiaozidian/ECG_Software';ARTIFACT=11965310040
SHA='51e32ada42c8bd11d1d7b25e4bd34d0c4a81665c9f6821ad51130e472627525c'
def main(output):
 output.mkdir(parents=True,exist_ok=False)
 row=json.loads(subprocess.check_output(['gh','api',f'repos/{REPO}/actions/artifacts/{ARTIFACT}']))
 assert not row['expired'] and row['digest']=='sha256:'+SHA
 assert row['workflow_run']['id']==38719645725 and row['workflow_run']['head_sha']=='af54df43700af53c97c72dfa0203bfe0c5acb2c8'
 archive=output/'verified-previous-artifact.zip'
 with archive.open('wb') as stream:subprocess.run(['gh','api',f'repos/{REPO}/actions/artifacts/{ARTIFACT}/zip'],stdout=stream,check=True)
 assert hashlib.file_digest(archive.open('rb'),'sha256').hexdigest()==SHA
 full=output/'previous-full.zip'
 with zipfile.ZipFile(archive) as z:
  assert z.testzip() is None
  with full.open('wb') as stream:stream.write(z.read('CardioInsight-DoctorEval-Windows-x64-1.0.2-full.zip'))
 assert hashlib.file_digest(full.open('rb'),'sha256').hexdigest()=='788687f15a6adf4e991ba9bdb9bcd63362485465c56c39847268e4fb1b4ea293'
 with zipfile.ZipFile(full) as z:
  assert z.testzip() is None
  for i in z.infolist():
   p=PurePosixPath(i.filename.replace('\\','/'));assert not p.is_absolute() and '..' not in p.parts and not any(':' in n for n in p.parts)
   assert (i.external_attr>>16)&0o170000 != 0o120000
  z.extractall(output/'package')
 receipt={'status':'passed','previous_packaging':'1.0.2','artifact_id':ARTIFACT,'artifact_sha256':SHA,'patient_inputs_read':False}
 (output/'fetch-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);main(p.parse_args().output)
