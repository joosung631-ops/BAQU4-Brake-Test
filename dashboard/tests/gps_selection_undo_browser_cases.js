async function gpsProjectBrowserCases(){
 const $=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);},wait=async f=>{for(let i=0;i<100;i++){if(f())return;await new Promise(r=>setTimeout(r,30));}throw Error('timeout');};
 const originalFetch=window.fetch;
 window.fetch=(url,...args)=>String(url).includes('/api/gps/projects/merge-source')?Promise.resolve(new Response(JSON.stringify({source:{origin:[37,127],tracks:[{id:'test',name:'test',points:[0,1,2].map(i=>({seq:i+1,lat:37+i*.0001,lon:127+i*.0001,segment:0}))}]},source_digest:'test',tracks:null}),{headers:{'Content-Type':'application/json'}})):originalFetch(url,...args);
 window.gpsProject={current:{filename:'test'},beforeStep:async()=>true,save:async()=>{}};
 await dashboardModes.setBuildStep('matching');const c=$('gps-merge-canvas');await wait(()=>c.dataset.pointCount==='3');c.setPointerCapture=()=>{};
 const r=c.getBoundingClientRect(),event=(type,x,y,altKey=false)=>c.dispatchEvent(new PointerEvent(type,{clientX:r.left+x,clientY:r.top+y,pointerId:1,button:0,altKey,bubbles:true}));
 const all=(alt=false)=>{event('pointerdown',1,1,alt);event('pointermove',r.width-1,r.height-1,alt);event('pointerup',r.width-1,r.height-1,alt);};

 const distance=Number(c.dataset.scaleDistanceMeters);assert(distance>0,'Scale bar has distance');
 c.dispatchEvent(new WheelEvent('wheel',{deltaY:-2000,clientX:r.left+r.width/2,clientY:r.top+r.height/2,bubbles:true,cancelable:true}));
 assert(Number(c.dataset.scaleDistanceMeters)<distance,'Scale bar adapts when zooming');$('gps-merge-fit').click();
 assert(!$('gps-merge-selection-undo')&&!$('gps-merge-clear'),'Selection cancel buttons removed');
 all();assert(c.dataset.selectedCount==='3','Drag selects points');
 window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));assert(c.dataset.selectedCount==='0','Esc clears all selection after drag');
 event('pointerdown',r.width/2,r.height/2);event('pointerup',r.width/2,r.height/2);assert(c.dataset.selectedCount==='1','Existing click selection');
 event('pointerdown',1,1);event('pointermove',r.width-1,r.height-1);
 window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));assert(c.dataset.selectedCount==='1','Esc ignored during drag');
 event('pointerup',r.width-1,r.height-1);assert(c.dataset.selectedCount==='3','Drag still completes after Esc');
 window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));assert(c.dataset.selectedCount==='0'&&c.dataset.preview==='null','Esc clears selection and mean preview');
 return 'Esc ignored during drag; clears all selection after drag; selection buttons removed: passed';
}
