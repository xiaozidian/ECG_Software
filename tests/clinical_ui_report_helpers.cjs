'use strict';
// Narrow VM fixtures must load the same ST helper closure as the workstation.
// No guard is replaced: compose/report-use eligibility stays production code.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/js/clinical-ui.js','utf8'),prepared=new WeakSet();
function region(a,b){const i=source.indexOf(a),j=source.indexOf(b,i+1);assert(i>=0&&j>i,'Production report helper boundary changed: '+a);return source.slice(i,j);}
const sttSource=region('  const sttGroups=','  let reportAutosaveTimer=');
function prepare(ctx){
 if(prepared.has(ctx))return;
 ctx.sttGroup??='all';ctx.sttReportFocus??=null;
 ctx.ECGReportEngine??=require('../static/js/report-engine.js');
 ctx.ECGReportSections??=require('../static/js/report-sections.js');
 if(typeof ctx.composition!=='function')vm.runInContext(region('  function composition(){','  const sttGroups='),ctx);
 vm.runInContext(sttSource,ctx);prepared.add(ctx);
}
module.exports={prepare,sttSource};
