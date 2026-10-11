"use strict";
/* A partition, not a beat-edit operation. Source samples never change. */
(()=>{
  const slots=[6,7,8,9];
  class Groups {
    constructor(source){
      this.source=[...new Set(source)].sort((a,b)=>a-b);
      this.slots=Object.fromEntries(slots.map(n=>[n,[]]));
      this.history=[];
    }
    remaining(){const used=new Set(Object.values(this.slots).flat());return this.source.filter(s=>!used.has(s));}
    remember(){this.history.push(Object.fromEntries(slots.map(n=>[n,[...this.slots[n]]])));if(this.history.length>12)this.history.shift();}
    move(number,selected){
      if(!slots.includes(number))throw Error('分组编号应为 6–9');
      const remaining=new Set(this.remaining()),unique=[...new Set(selected)];
      if(!unique.length)return 0;
      if(unique.some(s=>!remaining.has(s)))throw Error('框选已变化，请重新框选');
      this.remember();this.slots[number]=this.slots[number].concat(unique).sort((a,b)=>a-b);return unique.length;
    }
    restore(number){if(!slots.includes(number)||!this.slots[number].length)return false;this.remember();this.slots[number]=[];return true;}
    undo(){if(!this.history.length)return false;this.slots=this.history.pop();return true;}
  }
  function shortcut(event){
    return !event.repeat&&!event.ctrlKey&&!event.metaKey&&!event.altKey&&!event.shiftKey&&/^[6-9]$/.test(event.key)?Number(event.key):null;
  }
  const api={Groups,slots,shortcut};globalThis.ECGMorphologyGroups=api;if(typeof module!=='undefined')module.exports=api;
})();
