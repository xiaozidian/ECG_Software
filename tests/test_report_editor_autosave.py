"""Saving an equal draft cannot invalidate an open strip editor."""
from pathlib import Path
import subprocess


def test_strip_editor_survives_equal_save_but_rejects_changed_source_or_curation():
    root = Path(__file__).resolve().parents[1]
    script = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/js/clinical-ui.js','utf8'),code=source.slice(source.indexOf('  async function editReportStrip('),source.indexOf('  async function editNarrativeTemplates('));
const original={event_id:'event',basis_version:'basis',caption:'caption',leads:['II'],duration_s:7,notes:'note',print_enabled:true,preview_lead:'II'};let options;
const ctx={state:{caseId:'A',caseRequestId:1,reportStale:false,caseData:{metadata:{},technical:{duration_seconds_raw:100}},reportComposition:{selected_events:[structuredClone(original)]}},selectedLookup:new Map([['event',{event_id:'event',basis_version:'basis',label:'label'}]]),clinicalWorkflow:{writable:()=>true},ECGReportEngine:{settings:s=>({leads:s.leads,duration_s:s.duration_s})},ECGReportStripEditor:{curation:s=>({notes:s.notes||'',print_enabled:s.print_enabled!==false,preview_lead:s.preview_lead||'II'}),open:async o=>options=o},dirty(){},renderReportBody:async()=>{},reportStrip:async()=>{},reportReviewWave:async()=>{}};
ctx.selected=()=>ctx.state.reportComposition.selected_events;vm.createContext(ctx);vm.runInContext(code,ctx);
(async()=>{await ctx.editReportStrip(0);assert(options.isCurrent());
ctx.state.reportComposition.selected_events=[{notes:'note',print_enabled:true,preview_lead:'II',duration_s:7,leads:['II'],caption:'caption',basis_version:'basis',event_id:'event'}];assert(options.isCurrent(),'equal server save must preserve editor despite new objects/key order');
const next={...original,caption:'edited'};await options.onApply(next,{setDefaults:false});assert.equal(ctx.selected()[0].caption,'edited');
for(const key of ['basis_version','caption','duration_s','notes','print_enabled','leads','preview_lead']){ctx.state.reportComposition.selected_events=[structuredClone(original)];await ctx.editReportStrip(0);ctx.selected()[0][key]=key==='leads'?['V1']:key==='print_enabled'?false:key==='duration_s'?8:'changed';assert.equal(options.isCurrent(),false,'real change must invalidate: '+key);}
ctx.state.reportComposition.selected_events=[structuredClone(original)];await ctx.editReportStrip(0);ctx.state.reportStale=true;assert.equal(options.isCurrent(),false);ctx.state.reportStale=false;ctx.state.caseRequestId++;assert.equal(options.isCurrent(),false);
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    subprocess.run(['node', '-e', script], cwd=root, check=True, timeout=15)
