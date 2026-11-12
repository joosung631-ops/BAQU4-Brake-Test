async function gpsProjectBrowserCases(){
 const $=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);},wait=async f=>{for(let i=0;i<200;i++){if(f())return;await new Promise(r=>setTimeout(r,25));}throw Error('timeout');};
 const api=gpsProject.api,rv=await api('/api/gps/review');let p=await api('/api/gps/projects/create',{filename:'curves-browser.json'});
 p=await api('/api/gps/projects/save',{filename:p.filename,revision:p.project.revision,stage:2,dataset_id:rv.dataset_id,display:{linear:true,smooth:true}});
 p=await api('/api/gps/projects/save',{filename:p.filename,revision:p.project.revision,stage:3,dataset_id:rv.dataset_id,tracks:rv.tracks.map(t=>({id:t.id,excluded_seq:[]}))});
 window.gpsProject={current:p,beforeStep:async()=>true,save:async()=>{}};
 await dashboardModes.setBuildStep('matching');const c=$('gps-merge-canvas');await wait(()=>Number(c.dataset.smoothSegments)>0);
 assert($('gps-merge-linear').checked&&$('gps-merge-smooth').checked,'Both default on');assert(c.dataset.linearSegments==='4','Linear follows current points');
 $('gps-merge-linear').click();assert(c.dataset.linearSegments==='0'&&Number(c.dataset.smoothSegments)>0,'Linear independent');
 $('gps-merge-smooth').click();assert(c.dataset.smoothSegments==='0','Smooth off');$('gps-merge-linear').click();$('gps-merge-smooth').click();await wait(()=>Number(c.dataset.smoothSegments)>0);
 c.setPointerCapture=()=>{};const r=c.getBoundingClientRect(),ev=(type,x,y)=>c.dispatchEvent(new PointerEvent(type,{clientX:r.left+x,clientY:r.top+y,pointerId:1,button:0,bubbles:true}));
 ev('pointerdown',1,1);ev('pointermove',r.width-1,r.height-1);ev('pointerup',r.width-1,r.height-1);$('gps-merge-confirm').click();
 assert(c.dataset.pointCount==='1'&&c.dataset.linearSegments==='0','Linear updates after merge');await new Promise(r=>setTimeout(r,200));assert(c.dataset.smoothSegments==='0','Smooth updates to single merged point');
 $('gps-merge-undo').click();await wait(()=>Number(c.dataset.smoothSegments)>0);assert(c.dataset.linearSegments==='4','Undo restores both curves');await gpsMerger.save();
 return 'Stage 4 linear/smooth independent toggles, merged-point recomputation and undo: passed';
}
