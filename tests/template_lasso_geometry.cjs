'use strict';
const assert=require('node:assert/strict');
const M=require('../static/js/template-linked-view.js');
const checks=[];const check=(name,fn)=>{fn();checks.push(name);};
function inside(p,poly){let value=false;for(let i=0,j=poly.length-1;i<poly.length;j=i++){const a=poly[j],b=poly[i],cross=(p[0]-a[0])*(b[1]-a[1])-(p[1]-a[1])*(b[0]-a[0]);if(Math.abs(cross)<1e-8&&p[0]>=Math.min(a[0],b[0])&&p[0]<=Math.max(a[0],b[0])&&p[1]>=Math.min(a[1],b[1])&&p[1]<=Math.max(a[1],b[1]))return true;if((a[1]>p[1])!==(b[1]>p[1])&&p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0])value=!value;}return value;}
check('closed-loop-keeps-concave-notch-and-boundaries',()=>{const p=M.lassoPolygon([[0,0],[100,0],[100,35],[35,35],[35,100],[0,100],[0,0]]);assert(p);assert(inside([10,80],p));assert(inside([80,10],p));assert(!inside([80,80],p));for(const v of [[0,0],[100,0],[35,35],[35,100]])assert(inside(v,p));assert.deepEqual(p[0],p.at(-1));});
check('open-pointer-path-closes-implicitly',()=>{const p=M.lassoPolygon([[0,0],[90,0],[40,70]]);assert.equal(p.length,4);assert(inside([40,20],p));});
check('long-circle-stays-within-api-limit-and-retains-shape',()=>{const p=M.lassoPolygon(Array.from({length:2001},(_,i)=>[100+90*Math.cos(i*Math.PI/1000),100+90*Math.sin(i*Math.PI/1000)]));assert(p.length<=128);assert(inside([100,100],p));assert(!inside([190,190],p));assert(inside([150,150],p));});
check('straight-and-invalid-paths-do-not-replace-selection',()=>{assert.equal(M.lassoPolygon([[0,0],[10,10],[20,20],[0,0]]),null);assert.equal(M.lassoPolygon([[0,0],[NaN,3],[20,20]]),null);assert.equal(M.lassoPolygon([[1,1],[1,1]]),null);});
check('self-crossing-evenodd-path-is-retained',()=>{const p=M.lassoPolygon([[0,0],[100,100],[0,100],[100,0],[0,0]]);assert(p);assert(inside([50,20],p));assert(!inside([10,50],p));});
check('visual-size-independent-of-hit-target-and-device-pixels',()=>{assert.equal(M.scatterStyle(500,true,false,false).radius,1.35);assert.equal(M.scatterStyle(12000,true,false,false).radius,1.05);assert.equal(M.scatterStyle(12000,true,true,true).radius,1.6);assert(M.scatterStyle(500,true,false,true).alpha<M.scatterStyle(500,true,true,true).alpha);});
console.log(JSON.stringify({passed:true,checks}));
