async function gpsProjectBrowserCases(){
 const $=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);},wait=async f=>{for(let i=0;i<1800;i++){if(f())return;await new Promise(r=>setTimeout(r,50));}throw Error('timeout');};
 const api=gpsProject.api;let p=await api('/api/gps/projects/load?filename=lane-browser.json');
 window.gpsProject={get current(){return p;},beforeStep:async()=>true,api,save:async(stage,payload)=>{p=await api('/api/gps/projects/save',{filename:p.filename,revision:p.project.revision,stage,...payload});return p;}};
 await dashboardModes.setBuildStep('lane');const c=$('gps-lane-canvas');await wait(()=>!gpsLane.busy&&c.dataset.pointCount==='31');
 assert(document.querySelector('option[value="lane"]').textContent.includes('예상 차선 적용'),'Stage renamed');
 if(c.dataset.edgeCount==='0'){$('gps-lane-apply').click();await wait(()=>!gpsLane.busy&&c.dataset.edgeCount==='31');}
 $('gps-lane-cancel').click();assert(c.dataset.edgeCount==='0','Cancel hides both boundaries');await gpsLane.save();assert(p.project.stages['9'].enabled===false,'Cancellation saved');
 await dashboardModes.setBuildStep('lane');await wait(()=>!gpsLane.busy);assert(c.dataset.edgeCount==='0','Cancellation restored');
 assert(!$('gps-map-camera-title').closest('aside').hidden,'Stage 8 shows projection playback camera');
 assert($('gps-map-bag').closest('[data-build-step]').hidden,'Stage 8 hides bag selection');
 await dashboardModes.setBuildStep('validation');await wait(()=>!gpsLane.busy);
 assert(!$('gps-map-camera-title').closest('aside').hidden,'Stage 10 shows playback camera');
 assert($('gps-lane-apply').closest('[data-build-step]').hidden,'Stage 10 hides lane editing');
 await wait(()=>$('gps-map-bag').options.length>2);const select=$('gps-map-bag');select.value='2026-09-20/2026-09-20_4';select.dispatchEvent(new Event('change'));
 // Toggling the camera during preparation must not discard the GPS preparation.
 $('gps-map-camera-toggle').click();assert($('gps-map-camera-toggle').textContent==='OFF','Camera off');
 await wait(()=>!$('gps-map-play').disabled);assert($('gps-map-replay-status').textContent.includes('371점'),'Actual selected bag GPS loaded');
 $('gps-map-camera-toggle').click();await wait(()=>!$('gps-map-camera-image').hidden&&$('gps-map-camera-image').naturalWidth>0);
 const slider=$('gps-map-time');slider.value=15;slider.dispatchEvent(new Event('input'));await wait(()=>c.dataset.currentEast!==undefined&&!$('gps-map-camera-image').hidden);
 const raw=await api('/api/gps/source/replay-status'),expected=raw.gps.filter(g=>g.t<=15).at(-1);
 assert($('gps-map-position').textContent.includes(expected.lat.toFixed(7)),'Recorded-time GPS matches playhead');
 assert(Math.abs(Number(c.dataset.currentHeading)-expected.heading_rad)<1e-10,'Heading follows the selected GPS timestamp');
 const context=c.getContext('2d'),originalFill=context.fillRect;let box;
 context.fillRect=function(x,y,w,h){if(this.fillStyle==='#159a80')box={x,y,w,h,transform:this.getTransform()};return originalFill.call(this,x,y,w,h);};
 gpsLane.setCurrentPosition({...expected,heading_rad:0});assert(box&&Math.abs(box.w/box.h-2.222/1.28)<1e-8,'Vehicle rectangle preserves configured dimensions');
 assert(Math.abs(box.x/box.w+.784/2.222)<1e-8,'GPS antenna anchors the vehicle at its physical offset');
 gpsLane.setCurrentPosition({...expected,heading_rad:Math.PI/2});assert(Math.abs(box.transform.a)<1e-6&&box.transform.b<0,'North heading rotates the front upward');
 context.fillRect=originalFill;
 const before=Number(slider.value);$('gps-map-frame-next').click();assert(Number(slider.value)>before,'Next recorded frame');$('gps-map-frame-prev').click();assert(Number(slider.value)<before+.1,'Previous frame');
 gpsLane.setCurrentPosition({lat:p.project.stages['8'].origin[0]+.001,lon:p.project.stages['8'].origin[1]});assert(Number(c.dataset.currentNorth)>100,'GPS marker independent from background path');
 $('gps-map-camera-toggle').click();assert($('gps-map-camera-image').hidden,'Camera OFF hides image');
 const start=Number(slider.value);$('gps-map-play').click();await new Promise(r=>setTimeout(r,1600));$('gps-map-play').click();assert(Number(slider.value)>start+1,'GPS playback continues with camera off');assert($('gps-map-play').textContent==='재생','Playback pauses');
 $('gps-map-camera-toggle').click();await wait(()=>!$('gps-map-camera-image').hidden);$('gps-map-fps').value=5;$('gps-map-fps').dispatchEvent(new Event('change'));
 const image=$('gps-map-camera-image'),view=image.parentElement.getBoundingClientRect();assert(image.getBoundingClientRect().width<=view.width+1,'Image fits camera panel');
 await dashboardModes.setBuildStep('lane');await wait(()=>!gpsLane.busy);
 assert($('gps-map-camera-image').hidden&&$('gps-map-play').disabled,'Returning to stage 8 stops playback');
 $('gps-lane-apply').click();await wait(()=>!gpsLane.busy&&c.dataset.edgeCount==='31');await gpsLane.save();
 await dashboardModes.setBuildStep('path');assert($('gps-map-camera-image').hidden,'Leaving stage stops camera');assert($('gps-map-play').disabled,'Leaving stage clears playback');
 await dashboardModes.setBuildStep('validation');await wait(()=>!gpsLane.busy);assert(c.dataset.edgeCount==='31','Stage 10 restores saved stage 8 lanes');
 return 'Real bag camera/GPS recorded-time playback, seeking, frame stepping, camera toggle during loading and playback, independent GPS marker, lane cancel/save/reload: passed';
}
