async function gpsMapMergeOptionBrowserCases(){
 const $=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);};
 const wait=async f=>{for(let i=0;i<400;i++){if(f())return;await new Promise(r=>setTimeout(r,25));}throw Error('timeout: '+f);};
 const option=step=>[...$('map-build-step').options].find(o=>o.value===step);
 async function open(name){
  await dashboardModes.set('map-build');
  await wait(()=>[...$('gps-project-files').options].some(o=>JSON.parse(o.value).filename===name));
  $('gps-project-method').value='edit';$('gps-project-method').dispatchEvent(new Event('change'));
  $('gps-project-files').value=[...$('gps-project-files').options].find(o=>JSON.parse(o.value).filename===name).value;
  $('gps-project-open').click();await wait(()=>!gpsProject.busy&&gpsProject.current?.filename.endsWith(name.replace(/^\d+단계_\d{4}-\d{2}-\d{2}_\d{6,12}_/,'')));
 }
 async function moveBack(step){const moving=dashboardModes.setBuildStep(step);await wait(()=>$('gps-project-rewind-dialog').open);$('gps-project-rewind-dialog').close('continue');await moving;}
 async function saveBags(){const rev=gpsProject.current.project.revision;$('gps-source-save').click();await wait(()=>!gpsEditor.busy&&gpsProject.current.project.revision>rev);}
 await open('optional-map.json');await dashboardModes.setBuildStep('bags');await wait(()=>!gpsEditor.busy&&!$('gps-source-save').disabled&&$('gps-source-list').querySelector('input'));
 assert(!$('gps-source-map-merge').checked,'Default is unchecked');assert(!option('map-merge'),'Default has no MAP merge step');
 await saveBags();assert(!option('map-merge'),'Default save preserves existing steps');
 await dashboardModes.setBuildStep('points');await wait(()=>!gpsEditor.busy);await gpsEditor.save();
 assert(gpsProject.current.filename.startsWith('3단계_'),'Default GPS noise save stays stage 3');
 await moveBack('bags');await wait(()=>!gpsEditor.busy&&!$('gps-source-save').disabled);
 $('gps-source-map-merge').click();assert(!option('map-merge'),'Checkbox only changes workflow after save');
 assert(!$('gps-source-load').disabled,'Changing merge option does not block GPS loading');
 await saveBags();assert(gpsProject.mapMergeEnabled,'Saved option enabled');
 assert(option('map-merge').textContent==='3. MAP 병합하기','MAP step inserted as stage 3');
 assert(option('points').textContent==='4. GPS 노이즈 제거','Noise becomes stage 4');
 assert(option('export').textContent==='13. 최종 Map 저장','Remaining stages shift consistently');
 assert($('gps-review-save').textContent==='4단계 저장','Noise save button shifts');
 assert($('gps-lane-save').textContent==='10단계 저장','Later save button shifts');
 await dashboardModes.setBuildStep('map-merge');assert(dashboardModes.buildStep==='map-merge','Placeholder can be entered');
 assert(!document.querySelector('[data-center-view="map-build"][data-build-step="map-merge"]').hidden,'Placeholder shown');
 await dashboardModes.setBuildStep('points');assert(dashboardModes.buildStep==='map-merge','Reference alone cannot become an editable path');
 const raw=gpsProject.current.project.stages['2'].raw,points=raw.tracks[0].points;
 await gpsProject.save('map-merge',{source_dataset_id:gpsProject.current.project.stages['2'].dataset_id,clips:[{id:'clip-option-browser',bag:'comparison',start_seq:points[0].seq,end_seq:points.at(-1).seq,points,offset_e:5,offset_n:0}]});
 await dashboardModes.setBuildStep('points');await wait(()=>!gpsEditor.busy);await gpsEditor.save();
 assert($('gps-test-canvas').dataset.referencePointCount===String(points.length),'Reference remains visible as background');
 assert(gpsProject.current.filename.startsWith('4단계_'),'Optional noise save uses stage 4 filename');
 assert(gpsProject.current.project.stages['3'].tracks.length===1,'Existing noise editing still saves GPS');
 await dashboardModes.setBuildStep('add-points');await wait(()=>!gpsAdditions.busy);await gpsAdditions.save();
 assert(gpsProject.current.filename.startsWith('5단계_'),'Following editor saves as stage 5');
 await dashboardModes.set('none');const saved=gpsProject.current.filename;
 await open(saved);assert($('gps-source-map-merge').checked&&option('map-merge'),'Option and workflow survive reopening');
 assert($('gps-project-progress').textContent.includes('5단계 임의 GPS 포인트 추가'),'Resume progress uses visible numbering');
 await dashboardModes.setBuildStep('add-points');await wait(()=>!gpsAdditions.busy);
 const move=dashboardModes.setBuildStep('map-merge');await wait(()=>$('gps-project-rewind-dialog').open);$('gps-project-rewind-dialog').close('cancel');await move;
 assert(dashboardModes.buildStep==='add-points','Cancel rewind keeps current editor');
 await moveBack('map-merge');assert(gpsProject.mapMergeEnabled&&!gpsProject.current.project.stages['3'],'Rewind to MAP placeholder preserves option and removes later data');
 await moveBack('bags');await wait(()=>!gpsEditor.busy&&!$('gps-source-save').disabled);
 $('gps-source-map-merge').click();await saveBags();assert(!option('map-merge')&&option('points').textContent==='3. GPS 노이즈 제거','Uncheck and save restores original workflow');
 await dashboardModes.setBuildStep('map-merge');assert(dashboardModes.buildStep==='bags','Disabled MAP step cannot be opened directly');
 await dashboardModes.set('none');await open('default-other.json');assert(!$('gps-source-map-merge').checked&&!option('map-merge'),'Option does not leak between projects');
 return 'Default flow, save-only activation, shifted numbering, placeholder navigation, GPS editing, reload, rewind/cancel, disabling and project isolation: passed';
}
