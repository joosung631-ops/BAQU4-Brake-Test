const fs=require('fs'),vm=require('vm'),assert=require('assert');
const ids=['bag-select','bag-loop','bag-play','bag-stop','bag-status','bag-slower','bag-faster','bag-rate'];
const els=Object.fromEntries(ids.map(id=>[id,{options:[],value:'',checked:false,replaceChildren(...v){this.options=v;this.value=v[0]?.value||'';}}]));
let state={bags:['2026-09-20_1'],state:'idle',selected:null,loop:false,rate:1,external:false},requests=[];
const context={document:{getElementById:id=>els[id]},window:{addEventListener(){}},Option:class{constructor(text,value){this.text=text;this.value=value;}},setTimeout(){},clearTimeout(){},
 fetch:async(url,opts)=>{if(opts?.method==='POST'){const body=JSON.parse(opts.body);requests.push(body);state.rate=Math.max(.1,Math.round((state.rate+body.step*.1)*10)/10);}return {ok:true,json:async()=>({...state})};}};
(async()=>{
 vm.runInNewContext(fs.readFileSync('dashboard/dashboard/bag-control.js','utf8'),context);
 await new Promise(setImmediate);
 assert.equal(els['bag-rate'].textContent,'1.0×');
 await els['bag-faster'].onclick();assert.equal(requests[0].step,1);assert.equal(els['bag-rate'].textContent,'1.1×');
 await els['bag-slower'].onclick();assert.equal(els['bag-rate'].textContent,'1.0×');
 state.rate=.2;await els['bag-slower'].onclick();assert.equal(els['bag-rate'].textContent,'0.1×');assert.equal(els['bag-slower'].disabled,true);
 console.log('Bag speed buttons, displayed rate and minimum: passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
