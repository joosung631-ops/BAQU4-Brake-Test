async function gpsProjectBrowserCases(){
 const $=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);},wait=async f=>{for(let i=0;i<200;i++){if(f())return;await new Promise(r=>setTimeout(r,25));}throw Error('timeout');};
 const api=gpsProject.api,rv=await api('/api/gps/review');let p=await api('/api/gps/projects/create',{filename:'fusion-browser.json'});
 p=await api('/api/gps/projects/save',{filename:p.filename,revision:p.project.revision,stage:2,dataset_id:rv.dataset_id,display:{linear:true,smooth:true}});
 p=await api('/api/gps/projects/save',{filename:p.filename,revision:p.project.revision,stage:3,dataset_id:rv.dataset_id,tracks:rv.tracks.map(t=>({id:t.id,excluded_seq:[]}))});
 const src=await api('/api/gps/projects/merge-source?filename='+p.filename);
 p=await api('/api/gps/projects/save',{filename:p.filename,revision:p.project.revision,stage:5,source_digest:src.source_digest,tracks:src.source.tracks.map(t=>({id:t.id,groups:t.points.map(p=>[p.seq])}))});
 window.gpsProject={get current(){return p;},beforeStep:async()=>true,api,save:async(stage,payload)=>{p=await api('/api/gps/projects/save',{filename:p.filename,revision:p.project.revision,stage,...payload});return p;}};
 await dashboardModes.setBuildStep('fusion');const c=$('gps-fusion-canvas');await wait(()=>c.dataset.pointCount==='6');assert($('gps-fusion-legend').children.length===2,'Both recordings shown');await wait(()=>Number(c.dataset.smoothSegments)>0);assert($('gps-fusion-linear').checked&&$('gps-fusion-smooth').checked,'Both curves default on');$('gps-fusion-linear').click();assert(c.dataset.linearSegments==='0'&&Number(c.dataset.smoothSegments)>0,'Linear independent');$('gps-fusion-smooth').click();assert(c.dataset.smoothSegments==='0','Smooth independent');$('gps-fusion-linear').click();$('gps-fusion-smooth').click();await wait(()=>Number(c.dataset.smoothSegments)>0);c.setPointerCapture=()=>{};
 const r=c.getBoundingClientRect(),ev=(type,x,y,shiftKey=false)=>c.dispatchEvent(new PointerEvent(type,{clientX:r.left+x,clientY:r.top+y,pointerId:1,button:0,shiftKey,bubbles:true}));
 const rect=(x1,y1,x2,y2,shift=false)=>{ev('pointerdown',x1,y1,shift);ev('pointermove',x2,y2,shift);ev('pointerup',x2,y2,shift);};
 rect(1,1,r.width-1,r.height/2-20);assert(c.dataset.selectedCount==='2','Cross-bag top selection');
 rect(1,r.height/2+20,r.width-1,r.height-1);assert(c.dataset.selectedCount==='2','Normal drag replaces selection');
 rect(1,1,r.width-1,r.height/2-20,true);assert(c.dataset.selectedCount==='4','Shift drag adds selection');
 const preview=JSON.parse(c.dataset.preview);assert(preview.tracks===2,'Preview includes both recordings');$('gps-fusion-manual').click();assert(c.dataset.pointCount==='3','Manual merge spans bags');
 $('gps-fusion-undo').click();assert(c.dataset.pointCount==='6','Manual undo');
 rect(r.width/2-12,r.height/2-12,r.width/2+12,r.height/2+12);assert(c.dataset.selectedCount==='2','Select only middle pair');$('gps-fusion-radius').value='.5';$('gps-fusion-auto').click();await wait(()=>c.dataset.pointCount==='5'&&!gpsFusion.busy);assert(c.dataset.pointCount==='5','Auto merges selected pair only');
 $('gps-fusion-undo').click();rect(1,1,r.width-1,r.height-1);$('gps-fusion-auto').click();await wait(()=>c.dataset.pointCount==='3'&&!gpsFusion.busy);
 await gpsFusion.save();assert(p.project.stages['6'].points.length===3,'Stage 5 persisted');assert(p.project.stages['5'].tracks.every(t=>t.points.length===3),'Stage 4 untouched');
 await dashboardModes.setBuildStep('fusion');await wait(()=>c.dataset.pointCount==='3'&&!gpsFusion.busy);assert(c.dataset.selectedCount==='0','Reload saved groups');
 return 'All bags overlay, replacement and Shift-add drag, cross-bag manual merge, selected-only distance merge, undo, stage 5 persistence and reload: passed';
}
