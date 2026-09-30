"""View-only triage never changes curation or upgrades clinical review."""
import json
import subprocess

import pytest


@pytest.mark.parametrize('kind', ['missing', 'changed', 'missing_basis', 'wrong_id', 'pending', 'unknown', 'confirmed'])
def test_review_state_is_conservative(kind):
    script = """
require('./static/js/report-workspace.js');
const a=ECGReportWorkspace,k=JSON.parse(require('fs').readFileSync(0,'utf8'));
const s={event_id:'one',basis_version:'v1'},e={event_id:'one',basis_version:'v1',diagnosis_status:'confirmed'};
if(k==='changed')e.basis_version='v2';
if(k==='missing_basis'){delete e.basis_version;delete s.basis_version;}
if(k==='wrong_id')e.event_id='other';
if(k==='pending')e.diagnosis_status='pending';
if(k==='unknown')delete e.diagnosis_status;
console.log(a.stripReviewState(s,k==='missing'?null:e));
"""
    expected = 'confirmed' if kind == 'confirmed' else 'pending' if kind in ('pending', 'unknown') else 'stale'
    assert subprocess.check_output(['node','-e',script],input=json.dumps(kind),text=True).strip() == expected


def test_combined_filters_preserve_original_indices_and_curation():
    script = """
const assert=require('node:assert/strict');require('./static/js/report-workspace.js');
const a=ECGReportWorkspace,selected=[],lookup=new Map();
for(let i=0;i<1000;i++){
  selected.push(Object.freeze({event_id:'e'+i,basis_version:'v1',caption:'人工图注'+i,leads:Object.freeze(['II','V1']),range_start_s:i}));
  if(i%4!==0)lookup.set('e'+i,Object.freeze({event_id:'e'+i,basis_version:i%4===1?'v2':'v1',category:i%3?'AF':'V',subtype:i%3?'AF':'single',rhythm_status:'confirmed',diagnosis_status:i%4===3?'confirmed':'pending'}));
}
Object.freeze(selected);const before=JSON.stringify(selected),counts={all:1000,stale:500,pending:250,confirmed:250};
for(const type of ['all','AF:AF','V:single','stale','no-such-type'])for(const status of ['all','stale','pending','confirmed']){
  const q=a.reviewQueue(selected,lookup,type,status);assert.deepEqual(q.counts,counts);
  const expected=selected.map((s,i)=>i).filter(i=>{
    const key=i%4===0?'stale':i%3?'AF:AF':'V:single',state=i%4<2?'stale':i%4===2?'pending':'confirmed';
    return (type==='all'||key===type)&&(status==='all'||state===status);
  });
  assert.deepEqual(q.visible.map(r=>r.i),expected);q.visible.forEach(r=>assert.equal(r.s,selected[r.i]));
}
assert.equal(JSON.stringify(selected),before);
assert.deepEqual(a.reviewQueue([],new Map()).counts,{all:0,stale:0,pending:0,confirmed:0});
const old=selected[1],replacement={...old,basis_version:'v2'};
assert.equal(a.reviewQueue([replacement],lookup,'all','stale').visible.length,0);
assert.equal(a.stripReviewState(old,lookup.get(old.event_id)),'stale');
console.log('ok');
"""
    assert subprocess.check_output(['node','-e',script],text=True).strip() == 'ok'


@pytest.mark.parametrize('episode', ['pending', 'confirmed', None, 'unexpected'])
@pytest.mark.parametrize('step', ['pending', 'confirmed'])
def test_rhythm_episode_and_workflow_confirmation_are_both_required(episode, step):
    script = """
require('./static/js/report-workspace.js');const a=ECGReportWorkspace;
const e=JSON.parse(require('fs').readFileSync(0,'utf8')),s={event_id:'x',basis_version:'v1'};
const state=a.stripReviewState(s,e);console.log(JSON.stringify({state,note:a.reviewExplanation(state,e)}));
"""
    event=dict(event_id='x',basis_version='v1',category='AF',rhythm_status=episode,diagnosis_status=step)
    result=json.loads(subprocess.check_output(['node','-e',script],input=json.dumps(event),text=True))
    assert result['state'] == ('confirmed' if episode==step=='confirmed' else 'pending')
    if episode=='confirmed' and step=='pending':
        assert '片段已确认，编辑环节仍待确认' in result['note']
    if episode!='confirmed':
        assert '节律片段仍待复核' in result['note']
