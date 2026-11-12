const fs=require('fs'),vm=require('vm'),assert=require('assert');
const fills=[];
const ctx=new Proxy({fill(){fills.push(this.fillStyle);}}, {get(o,k){return k in o?o[k]:()=>{};}});
const els={};for(const id of ['gps-live-canvas','gps-live-status','gps-live-coordinates','gps-live-fit','gps-live-clear'])els[id]={dataset:{},addEventListener(){},getBoundingClientRect(){return {width:900,height:700};}};
els['gps-live-canvas'].getContext=()=>ctx;
let ws;
const context={document:{getElementById:id=>els[id]},window:{devicePixelRatio:1,addEventListener(){}},location:{protocol:'http:',host:'test'},
 ResizeObserver:class{constructor(f){this.f=f;}observe(){this.f();}},WebSocket:class{constructor(){ws=this;}},setTimeout,clearTimeout,
 fetch:async()=>({ok:true})};
vm.runInNewContext(fs.readFileSync('dashboard/dashboard/gps-live-overlay.js','utf8'),context);
const point=(seq,quality)=>({seq,quality,lat:37.2+seq*.00001,lon:126.7});
function send(session,seq,reset,points){ws.onmessage({data:JSON.stringify({session,seq,reset,points,active:true})});}
send('display',1,true,[point(1,4)]);
send('display',2,false,[point(2,1)]);
assert.equal(els['gps-live-canvas'].dataset.pointCount,'2');
assert(fills.includes('#4e83ba'));assert(fills.includes('#dc4545'));
send('display',2,false,[]);assert.equal(els['gps-live-canvas'].dataset.pointCount,'2');
// New bag has the same display session and globally increasing sequence.
send('display',3,false,[point(3,5)]);assert.equal(els['gps-live-canvas'].dataset.pointCount,'3');
send('cleared',0,true,[]);assert.equal(els['gps-live-canvas'].dataset.pointCount,'0');
send('cleared',1,false,[point(1,null)]);assert(fills.includes('#94a3b8'));
console.log('GPS browser accumulation, clear and quality colors: passed');
