'use strict';
// Execute the shipped adapter against original varying mathematical int16 frames.
// This is a protocol/algorithm test in Node VM, never browser click evidence.
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto');
const {harness}=require('./browser_demo_feedback_api.cjs');
const fixture=JSON.parse(fs.readFileSync(process.argv[2],'utf8')),mode=process.argv[3];
const KEY='cardioinsight-public-math-4314-v2',FIELDS=['case_id','analysis_basis','analysis_revision','beat_revision'];
const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
const scope=value=>Object.fromEntries(FIELDS.map(key=>[key,value[key]]));
const query=value=>new URLSearchParams(value).toString();
const source=item=>({raw:fs.readFileSync(item.raw_path),rows:item.rows});
const assets=h=>h.nativeRequests.filter(path=>path.endsWith('/waveform.bin'));
function sameModel(value,expected){
  const actual={...value};for(const field of FIELDS)delete actual[field];
  assert.deepEqual(actual,expected,'all min/max pairs, edges, raw metadata and source extent must match native');
}
async function main(){
  const item=fixture.cases.at(-1),rawSource=source(item);
  if(mode==='parity'){
    for(const example of fixture.cases){
      const data=source(example),h=harness(data),basis=scope(await h.call('analysis-basis'));
      const stored=h.localStorage.getItem(KEY),writes=h.localStorage.writes;
      for(const [bins,expected] of Object.entries(example.expected)){
        const value=await h.call('waveform-overview?'+query({bins,...basis}));
        sameModel(value,expected);assert.deepEqual(scope(value),basis);
        for(const ranges of Object.values(value.leads))assert(ranges.every(pair=>pair[0]<=pair[1]));
      }
      sameModel(await h.call('waveform-overview'),example.expected['1000']);
      assert.equal(assets(h).length,1,'immutable mathematical raw bytes shared across all bin counts');
      assert.equal(sha(data.raw),example.raw_sha256,'raw input must remain unchanged');
      assert.equal(h.localStorage.getItem(KEY),stored);assert.equal(h.localStorage.writes,writes,'reads must not persist');
    }
  }else if(mode==='validation'){
    const h=harness(rawSource),stored=h.localStorage.getItem(KEY);
    for(const bins of ['49','1601','50.0','1e3','abc','','NaN','Infinity','0x64'])await h.call('waveform-overview?'+query({bins}),'GET',undefined,400);
    await h.call('waveform-overview','POST',{},404);
    await h.call('/api/cases/other-mathematical-case/waveform-overview','GET',undefined,404);
    assert.equal(assets(h).length,0,'invalid requests cannot load the raw asset');
    for(const bins of [' 50 ','+50','0050'])sameModel(await h.call('waveform-overview?'+query({bins})),item.expected['50']);
    for(const raw of [Buffer.alloc(0),Buffer.alloc(17)]){
      const malformed=harness({raw,rows:[]}),before=malformed.localStorage.getItem(KEY);
      await malformed.call('waveform-overview','GET',undefined,409);
      assert.equal(malformed.localStorage.getItem(KEY),before);assert.equal(malformed.localStorage.writes,0);
    }
    const truncatedSource={raw:Buffer.from(rawSource.raw),rows:rawSource.rows},truncated=harness(truncatedSource);
    truncatedSource.raw=truncatedSource.raw.subarray(0,-16);
    await truncated.call('waveform-overview','GET',undefined,409);
    assert.equal(truncated.localStorage.writes,0);assert.equal(h.localStorage.getItem(KEY),stored);
  }else if(mode==='identity'){
    const h=harness(rawSource),basis=scope(await h.call('analysis-basis'));
    for(const field of FIELDS){
      const stale={...basis,[field]:typeof basis[field]==='number'?basis[field]+1:basis[field]+'-old'};
      await h.call('waveform-overview?'+query(stale),'GET',undefined,409);
    }
    assert.equal(assets(h).length,0,'all identity conflicts are rejected before source loading');
    await h.call('beat-editor','PUT',{operation:'relabel',revision:0,confirmed:true,selection:{samples:[800]},class_code:'V'});
    const changed=scope(await h.call('analysis-basis')),stored=h.localStorage.getItem(KEY),writes=h.localStorage.writes;
    assert.equal(changed.beat_revision,basis.beat_revision+1);assert(changed.analysis_revision>basis.analysis_revision);
    await h.call('waveform-overview?'+query(basis),'GET',undefined,409);
    const current=await h.call('waveform-overview?'+query(changed));sameModel(current,item.expected['1000']);assert.deepEqual(scope(current),changed);
    assert.equal(h.localStorage.getItem(KEY),stored);assert.equal(h.localStorage.writes,writes);
  }else if(mode==='concurrency'){
    const h=harness(rawSource),before=scope(await h.call('analysis-basis'));h.holdWaveform();
    const pending=h.call('waveform-overview?'+query(before),'GET',undefined,409);await h.waitWaveformHeld();
    await h.call('beat-editor','PUT',{operation:'relabel',revision:0,confirmed:true,selection:{samples:[800]},class_code:'V'});
    const after=scope(await h.call('analysis-basis')),stored=h.localStorage.getItem(KEY),writes=h.localStorage.writes;
    h.releaseWaveform();const rejected=await pending;assert.match(rejected.error,/变化/);
    const current=await h.call('waveform-overview?'+query(after));sameModel(current,item.expected['1000']);assert.deepEqual(scope(current),after);
    assert.equal(assets(h).length,1);assert.equal(h.localStorage.getItem(KEY),stored);assert.equal(h.localStorage.writes,writes);
    // A second browser adapter sharing storage must also invalidate an awaited read.
    const local=harness(rawSource),other=harness(rawSource,local.localStorage.values),basis=scope(await local.call('analysis-basis'));local.holdWaveform();
    const waiting=local.call('waveform-overview?'+query(basis),'GET',undefined,409);await local.waitWaveformHeld();
    await other.call('beat-editor','PUT',{operation:'relabel',revision:0,confirmed:true,selection:{samples:[800]},class_code:'V'});
    const persisted=other.localStorage.getItem(KEY);local.releaseWaveform();await waiting;
    assert.equal(local.localStorage.getItem(KEY),persisted);assert.equal(local.localStorage.writes,0);
  }else if(mode==='abort'){
    const h=harness(rawSource),controller=new AbortController(),path='/api/cases/'+h.input.case_id+'/waveform-overview';
    controller.abort();await assert.rejects(h.context.fetch(path,{signal:controller.signal}),error=>error.name==='AbortError');assert.equal(assets(h).length,0);
    const inFlight=new AbortController();h.holdWaveform();const pending=h.context.fetch(path,{signal:inFlight.signal});await h.waitWaveformHeld();
    inFlight.abort();h.releaseWaveform();await assert.rejects(pending,error=>error.name==='AbortError');
    sameModel(await h.call('waveform-overview'),item.expected['1000']);assert.equal(assets(h).length,1,'an aborted consumer cannot poison or reload the immutable shared raw asset');assert.equal(h.localStorage.writes,0);
  }else throw Error('Unknown test case: '+mode);
  console.log(JSON.stringify({passed:true,case:mode,nativeParity:true,patient_inputs:false,services_started:false,browser_ui:false}));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
