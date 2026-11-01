'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/js/overview-workbench.js','utf8');
const start=source.indexOf('  function gestureDistance(');assert(start>=0);
const end=source.indexOf('\n  }',start)+4,context=vm.createContext({});
vm.runInContext(source.slice(start,end),context);
const job={g:{kind:'scatter',bound:2000,w:300,h:220},selectionMode:'lasso',
  point:{x:100,y:100},last:{x:100,y:100},points:[[500,500],[1500,500],[1500,1500],[500,1500],[500,500]]};
assert(context.gestureDistance(job)>4,'A closed loop is a lasso even when it returns to its origin');
assert(context.gestureDistance({...job,points:[[500,500],[501,500],[500,500]]})<4,'Tiny pointer jitter remains a click');
assert.equal(context.gestureDistance({...job,selectionMode:'point'}),0);
assert.equal(context.gestureDistance({...job,selectionMode:'box',last:{x:103,y:104}}),5);
assert.equal(context.gestureDistance({...job,g:{kind:'rr'},last:{x:106,y:108}}),10);
console.log('Closed lasso, tiny jitter, point, box and RR gesture distances passed.');
