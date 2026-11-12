async function gpsProjectBrowserCases(){
 const $=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);},wait=async f=>{for(let i=0;i<1200;i++){if(f())return;await new Promise(r=>setTimeout(r,25));}throw Error('timeout');};
 const api=gpsProject.api;let p=await api('/api/gps/projects/load?filename=path-browser.json');
 window.gpsProject={get current(){return p;},beforeStep:async()=>true,api,save:async(stage,payload)=>{p=await api('/api/gps/projects/save',{filename:p.filename,revision:p.project.revision,stage,...payload});return p;}};
 await dashboardModes.setBuildStep('path');const c=$('gps-path-canvas');await wait(()=>c.dataset.pointCount==='25'&&!gpsPath.busy);
 assert($('gps-path-vehicle').textContent.includes('1.328'),'Vehicle configuration loaded');
 $('gps-path-generate').click();await wait(()=>!gpsPath.busy&&c.dataset.valid==='true');assert(Number(c.dataset.outputCount)>100,'Ten centimetre output');assert(!$('gps-path-save').disabled,'Validated preview can save');
 const data=await api('/api/gps/projects/path-source?filename='+p.filename),points=data.points,r=c.getBoundingClientRect(),es=points.map(p=>p.e),ns=points.map(p=>p.n),a=Math.min(...es),b=Math.max(...es),d=Math.min(...ns),e=Math.max(...ns);
 const scale=Math.max(.0001,Math.min(Math.max(20,r.width-120)/Math.max(1,b-a),Math.max(20,r.height-150)/Math.max(1,e-d)));
 c.setPointerCapture=()=>{};const pt=points[12],x=r.left+r.width/2+(pt.e-(a+b)/2)*scale,y=r.top+r.height/2-(pt.n-(d+e)/2)*scale;
 for(const type of ['pointerdown','pointerup'])c.dispatchEvent(new PointerEvent(type,{clientX:x,clientY:y,pointerId:1,button:0,bubbles:true}));
 assert($('gps-path-selection').textContent.includes('순서 #13')&&$('gps-path-selection').textContent.includes('조향'),'Click shows ordered point error and steering');
 $('gps-path-distance').value='.15';$('gps-path-distance').dispatchEvent(new Event('input'));assert($('gps-path-save').disabled,'Changed settings require regeneration');
 $('gps-path-generate').click();await wait(()=>!gpsPath.busy&&c.dataset.valid==='true');await gpsPath.save();
 const saved=p.project.stages['8'];assert(saved.settings.output_spacing_m===.1&&!saved.settings.closed,'Open 10cm route saved');assert(saved.reference_point==='rear_axle_center','Rear axle reference');assert(saved.vehicle_config.gps_antenna_offset_x_m===.559,'GNSS lever arm snapshot');assert(saved.points.length>100,'Output GPS persisted');
 for(let i=1;i<saved.points.length-1;i++)assert(Math.abs(saved.points[i].s_m-saved.points[i-1].s_m-.1)<1e-6,'10cm spacing');
 await dashboardModes.setBuildStep('path');await wait(()=>!gpsPath.busy&&c.dataset.valid==='true');assert($('gps-path-distance').value==='0.15','Saved settings restored');assert($('gps-path-dirty').textContent==='저장된 상태','Saved state restored');
 $('gps-path-show-gps').click();assert(!$('gps-path-show-gps').checked,'Independent GPS overlay toggle');$('gps-path-show-gps').click();
 return 'Vehicle settings, constrained preview, point selection, stale-settings guard, open 10cm output, stage 7 save and restoration: passed';
}
