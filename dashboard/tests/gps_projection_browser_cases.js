async function gpsProjectBrowserCases(){
 const $=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);},wait=async(f,label='condition')=>{for(let i=0;i<1800;i++){if(f())return;await new Promise(r=>setTimeout(r,50));}throw Error('timeout: '+label+' / '+$('gps-projection-status').textContent);};
 await dashboardModes.setBuildStep('project');await wait(()=>$('gps-project-files').options.length>0);
 $('gps-project-method').value='edit';$('gps-project-method').dispatchEvent(new Event('change'));
 const option=[...$('gps-project-files').options].find(o=>JSON.parse(o.value).filename==='projection-test.json');assert(option,'fixture');$('gps-project-files').value=option.value;$('gps-project-open').click();await wait(()=>gpsProject.current&&!gpsProject.busy);
 await dashboardModes.setBuildStep('lane');await wait(()=>!gpsLane.busy&&$('gps-section-bag').options.length>1&&$('gps-projection-config').textContent.includes('1280'));
 assert(Number($('gps-lane-width-input').value)===3.2,'Initial lane width from config');$('gps-lane-width-input').value=4.2;$('gps-lane-width-input').dispatchEvent(new Event('input'));assert(!$('gps-map-camera-title').closest('aside').hidden,'Stage 8 camera visible');assert($('gps-section-bag').closest('.camera-panel'),'Bag selection in camera panel');
 const config=await gpsProject.api('/api/gps/projects/projection-config'),g=gpsProjectionGeometry;
 // Independent reference values obtained from cv2.projectPoints (OpenCV 4.5.4).
 const optical=[[-1.5,1.14,5],[1.5,1.14,5],[0,1.14,10],[2,2,20]],expected=[[397.0684783932204,562.0208618149177],[875.1077791083057,560.4597718655848],[637.8579022046762,471.5430293902404],[718.0764036952929,460.17299536576263]];
 optical.forEach(([x,y,z],i)=>{const p=g.pixel({x,y,z},config.calibration,1280,720);assert(Math.hypot(p.x-expected[i][0],p.y-expected[i][1])<1e-8,'Matches OpenCV projection including distortion');const half=g.pixel({x,y,z},config.calibration,640,360);assert(Math.abs(half.x-p.x/2)<1e-10,'Resolution scaling');});
 assert(g.pixel({x:0,y:0,z:-1},config.calibration,1280,720)===null,'Behind-camera point rejected');
 const simple={...config,camera:{height_above_ground_m:1,distance_from_rear_m:.7,lateral_offset_m:0,pitch_deg:0},vehicle:{rear_axle_distance_from_rear_m:.2,gps_antenna_offset_x_m:.5,gps_antenna_offset_y_m:0}},pose={e:0,n:0,heading_rad:0};
 const p=g.optical({e:10,n:0},pose,simple);assert(Math.abs(p.z-10)<1e-8&&p.y===1,'Physical GPS to camera offset');const up=g.optical({e:10,n:0},pose,{...simple,camera:{...simple.camera,pitch_deg:10}});assert(up.y/up.z>p.y/p.z,'Positive pitch looks upward');
 const north=g.optical({e:0,n:10},{...pose,heading_rad:Math.PI/2},simple);assert(Math.abs(north.x)<1e-8&&Math.abs(north.z-10)<1e-8,'Path heading rotates correctly');
 const path=[{s_m:0,heading_rad:0},{s_m:10,heading_rad:Math.PI/2}],track=[{t:0,e:0,n:0,lat:37,lon:127,s_m:0,distance_m:0},{t:1,e:2,n:0,lat:37,lon:127.00001,s_m:2,distance_m:0}];
 assert(g.poseAtTrack(track,path,.5).e===1,'GPS interpolated at frame time');assert(g.poseAtTrack(track,path,2)===null,'No extrapolation after GPS end');assert(g.poseAtTrack([track[0],{...track[1],t:5}],path,2)===null,'Long GPS gaps rejected');
 $('gps-lane-apply').click();await wait(()=>!gpsLane.busy&&Number($('gps-lane-canvas').dataset.edgeCount)>0);
 const bag=$('gps-section-bag');bag.value=[...bag.options].find(o=>o.value.endsWith('_4'))?.value||bag.options[1].value;bag.dispatchEvent(new Event('change'));await wait(()=>!$('gps-map-play').disabled,'bag loaded');
 const slider=$('gps-map-time'),overlay=$('gps-camera-projection'),raw=await gpsProject.api('/api/gps/source/replay-status');const inside=raw.gps.find(sample=>{const pose=gpsProjection.poseAt(raw,sample.t);return pose&&pose.distance_m<3&&pose.s_m>10&&pose.s_m<gpsLane.projectionSource.points.at(-1).s_m-70;});assert(inside,'Recorded GPS reaches mapped route');slider.value=inside.t+.1;slider.dispatchEvent(new Event('input'));await wait(()=>!$('gps-map-camera-image').hidden&&Number(overlay.dataset.segmentCount)>0,'projected actual frame');
 assert(Number($('gps-lane-canvas').dataset.appliedWidth)===4.2,'Custom width applied');$('gps-lane-width-input').value=3.6;$('gps-lane-width-input').dispatchEvent(new Event('input'));assert(Number($('gps-lane-canvas').dataset.appliedWidth)===3.6&&!overlay.hidden,'Width change updates map and projection immediately');assert(Math.abs(Number(overlay.dataset.gpsTime)-Number(overlay.dataset.frameTime))<1e-8,'Projection aligned to decoded frame, not current playhead');
 const at=gpsProjection.poseAt(raw,Number(overlay.dataset.gpsTime));assert(Math.abs(Number(overlay.dataset.heading)-at.heading_rad)<1e-10,'Projection uses path tangent');
 $('gps-projection-offset').value=.25;$('gps-projection-offset').dispatchEvent(new Event('change'));assert(Math.abs(Number(overlay.dataset.gpsTime)-Number(overlay.dataset.frameTime)-.25)<1e-8,'Positive offset uses later GPS');
 $('gps-projection-enabled').click();assert(!overlay.hidden&&Number(overlay.dataset.laneSegmentCount)===0&&Number(overlay.dataset.centerSegmentCount)>0,'Independent lane toggle');$('gps-projection-center').click();assert(overlay.hidden,'All components off');$('gps-projection-center').click();$('gps-projection-enabled').click();assert(!overlay.hidden,'Overlay toggle on');
 const t=Number(slider.value);$('gps-map-frame-next').click();await wait(()=>!overlay.hidden,'next frame overlay');assert(Number(overlay.dataset.frameTime)>=t,'Frame stepping updates projection');
 $('gps-map-play').click();await new Promise(r=>setTimeout(r,900));$('gps-map-play').click();assert(Number(slider.value)>t+.5,'Playback with projection');await wait(()=>!overlay.hidden&&Number(overlay.dataset.segmentCount)>0,'playback overlay');
 $('gps-lane-save').click();await wait(()=>!gpsLane.busy);assert(gpsProject.current.project.stages['9'].lane_width_m===3.6,'Custom width saved');assert(gpsProject.current.project.stages['9'].projection.time_offset_s===.25,'Time correction saved in stage 8');
 $('gps-lane-cancel').click();assert(!overlay.hidden&&Number(overlay.dataset.laneSegmentCount)===0&&Number(overlay.dataset.centerSegmentCount)>0,'Cancel lanes retains independent center');$('gps-lane-apply').click();await wait(()=>!gpsLane.busy&&!overlay.hidden,'Reapply lane preview projects without saving');
 $('gps-map-camera-toggle').click();assert(overlay.hidden,'Camera off clears overlay');$('gps-map-camera-toggle').click();await wait(()=>!overlay.hidden,'Camera on restores overlay');
 await dashboardModes.set('none');assert(overlay.hidden,'Leaving clears overlay');await dashboardModes.set('map-build');await dashboardModes.setBuildStep('lane');await wait(()=>!gpsLane.busy);assert(Number($('gps-lane-width-input').value)===3.6,'Saved width restored instead of config default');assert(Number($('gps-projection-offset').value)===.25,'Saved projection controls restored');
 await dashboardModes.setBuildStep('sections');await wait(()=>!gpsSections.busy);assert(overlay.hidden,'Stage switch clears old camera frame');
 $('gps-section-bag').value=raw.bag;$('gps-section-bag').dispatchEvent(new Event('change'));await wait(()=>!$('gps-map-play').disabled);
 slider.value=inside.t+.1;slider.dispatchEvent(new Event('input'));await wait(()=>!overlay.hidden&&Number(overlay.dataset.centerSegmentCount)>0,'Stage 9 projection');
 const src=gpsSections.projectionSource,station=gpsProjection.poseAt(raw,Number(overlay.dataset.gpsTime)).s_m;
 const geometry=gpsSectionGeometry,prepared=geometry.prepare(src);
 const boundaryAt=s=>{let i=prepared.points.findIndex(p=>p.s_m>=s);i=Math.max(1,i);const a=prepared.points[i-1],b=prepared.points[i];return geometry.boundary(prepared,i-1,(s-a.s_m)/(b.s_m-a.s_m));};
 src.task_sections.push({name:'영상 검증',description:'구간 구분선',start:boundaryAt(station+10),end:boundaryAt(station+20)});
 window.dispatchEvent(new CustomEvent('gps:sectionschange'));
 assert(Number(overlay.dataset.sectionSegmentCount)>0,'Live unsaved section boundaries projected');
 $('gps-projection-sections').click();assert(Number(overlay.dataset.sectionSegmentCount)===0&&Number(overlay.dataset.centerSegmentCount)>0,'Independent sections toggle');$('gps-projection-sections').click();
 await gpsSections.save();
 for(const step of ['validation','export']){
  await dashboardModes.setBuildStep(step);await wait(()=>!gpsLane.busy&&$('gps-map-bag').options.length>1);
  $('gps-map-bag').value=raw.bag;$('gps-map-bag').dispatchEvent(new Event('change'));await wait(()=>!$('gps-map-play').disabled);
  slider.value=inside.t+.1;slider.dispatchEvent(new Event('input'));await wait(()=>!overlay.hidden&&Number(overlay.dataset.sectionSegmentCount)>0,step+' saved sections projection');
  $('gps-projection-center').click();assert(Number(overlay.dataset.centerSegmentCount)===0&&Number(overlay.dataset.sectionSegmentCount)>0,'Independent center toggle');$('gps-projection-center').click();
 }
 const back=dashboardModes.setBuildStep('lane');await wait(()=>$('gps-project-rewind-dialog').open);$('gps-project-rewind-dialog').close('continue');await back;await wait(()=>!gpsLane.busy&&$('gps-section-bag').options.length>1);
 $('gps-section-bag').value=raw.bag;$('gps-section-bag').dispatchEvent(new Event('change'));await wait(()=>!$('gps-map-play').disabled);slider.value=inside.t+.1;slider.dispatchEvent(new Event('input'));await wait(()=>!overlay.hidden&&Number(overlay.dataset.segmentCount)>0,'Final visual check');
 return 'OpenCV projection parity, pitch/lever arm, interpolation, real stage 8 camera overlay, frame synchronization, preview/cancel, playback, time correction persistence, independent component toggles and live/saved section projection in stages 9–11: passed';
}
