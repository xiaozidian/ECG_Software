/* Synthetic microbenchmark; no patient data, network, or state writes. */
"use strict";
const {performance}=require('node:perf_hooks');
const E=require('../static/js/beat-engine.js'),A=require('../static/js/clinical-analysis.js');
const mean=a=>a.reduce((s,x)=>s+x,0)/a.length;
const previous=a=>Math.sqrt(a.reduce((s,x)=>s+(x-mean(a))**2,0)/(a.length-1));
const linear=a=>{const m=mean(a);return Math.sqrt(a.reduce((s,x)=>s+(x-m)**2,0)/(a.length-1))};
const input=Array.from({length:20000},(_,i)=>800+(i%7)*5);
let start=performance.now();const before=previous(input),oldMs=performance.now()-start;
start=performance.now();const after=linear(input),newMs=performance.now()-start;
let sample=0;
const beats=Array.from({length:100001},(_,i)=>{const rr=i?800+(i%7)*5:0;sample+=rr/5;return {sample_index:sample,class_code:'N',rr_ms:rr}});
const feed={beats,duration:sample/200,document:E.blank()};
start=performance.now();const summary=E.hrv(feed,feed.duration),summaryMs=performance.now()-start;
start=performance.now();const windows=A.hrvWindows(feed,'2026-09-28 08:00:00'),windowsMs=performance.now()-start;
console.log(JSON.stringify({node:process.version,same_numeric_result:before===after,
  stdev_20000:{before_ms:oldMs,after_ms:newMs},
  nn_100000:{summary_ms:summaryMs,windowed_ms:windowsMs,count:summary.nn_count,window_count:windows.periods.full.nn_count}},null,2));
