async function gpsProjectBrowserCases(){
 const $=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);},wait=async f=>{for(let i=0;i<300;i++){if(f())return;await new Promise(r=>setTimeout(r,25));}throw Error('timeout');};
 const api=gpsProject.api;let p=await api('/api/gps/projects/load?filename=lane-browser.json');
 window.gpsProject={get current(){return p;},beforeStep:async()=>true,api,save:async(stage,payload)=>{p=await api('/api/gps/projects/save',{filename:p.filename,revision:p.project.revision,stage,...payload});return p;}};
 await dashboardModes.setBuildStep('lane');const c=$('gps-lane-canvas');await wait(()=>!gpsLane.busy&&c.dataset.pointCount==='31');
 assert(c.dataset.edgeCount==='0','No lane before Apply');assert($('gps-lane-width').textContent.includes('3.2'),'Width read from configuration');assert($('gps-lane-save').disabled,'No unapplied result saved');
 const original=JSON.stringify(p.project.stages['8']);$('gps-lane-apply').click();await wait(()=>!gpsLane.busy&&c.dataset.edgeCount==='31');
 assert(c.dataset.appliedWidth==='3.2','Full lane width applied');assert(!$('gps-lane-save').disabled,'Applied preview can save');assert(Number(c.dataset.gridSpacingMeters)>0,'Metric grid shown');
 const before=await api('/api/gps/projects/load?filename='+p.filename);assert(before.project.revision===1,'Apply does not save prematurely');
 await gpsLane.save();assert(p.project.stages['9'].lane_width_m===3.2,'Stage 8 saved');assert(!('points' in p.project.stages['9'])&&!('edges' in p.project.stages['9']),'Coordinates not duplicated');assert(JSON.stringify(p.project.stages['8'])===original,'Stage 7 unchanged');
 await dashboardModes.setBuildStep('lane');await wait(()=>!gpsLane.busy&&c.dataset.edgeCount==='31');assert($('gps-lane-dirty').textContent==='저장된 상태','Saved lane restored');
 const scale=Number(c.dataset.gridSpacingMeters),r=c.getBoundingClientRect();c.dispatchEvent(new WheelEvent('wheel',{clientX:r.left+r.width/2,clientY:r.top+r.height/2,deltaY:-1000,cancelable:true,bubbles:true}));assert(Number(c.dataset.gridSpacingMeters)<scale,'Zoom supported');$('gps-lane-fit').click();
 return 'Configuration width, explicit Apply, half-width lane preview, stage 8 compact save, reload and grid zoom: passed';
}
