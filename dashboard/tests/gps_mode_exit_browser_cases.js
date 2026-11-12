async function gpsProjectBrowserCases(){
 const $=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);},wait=async f=>{for(let i=0;i<500;i++){if(f())return;await new Promise(r=>setTimeout(r,25));}throw Error('timeout');};
 await dashboardModes.setBuildStep('project');await wait(()=>$('gps-project-files').options.length>0);
 $('gps-project-method').value='edit';$('gps-project-method').dispatchEvent(new Event('change'));
 const option=[...$('gps-project-files').options].find(o=>JSON.parse(o.value).filename==='mode-exit-test.json');assert(option,'Fixture found');$('gps-project-files').value=option.value;
 $('gps-project-open').click();await wait(()=>gpsProject.current&&!gpsProject.busy);
 await dashboardModes.setBuildStep('lane');await wait(()=>!gpsLane.busy);$('gps-lane-apply').click();await wait(()=>!gpsLane.busy&&$('gps-lane-dirty').textContent.includes('미저장'));
 const originalSave=gpsProject.save;gpsProject.save=async()=>{throw Error('저장 실패 테스트');};
 const beforeFailure=JSON.stringify(gpsProject.current.project.stages['9']);
 assert(await dashboardModes.set('none')===true,'Failed autosave still switches modes');assert(dashboardModes.current==='none','Requested mode shown after save failure');assert($('map-build-mode-status').textContent==='저장에 실패하여 저장되지 않은 작업 내용이 유실되었습니다.'&&!$('map-build-mode-status').hidden,'Only the data-loss notice is shown');assert(JSON.stringify(gpsProject.current.project.stages['9'])===beforeFailure,'Previously saved work preserved');
 gpsProject.save=originalSave;await dashboardModes.set('map-build');assert(dashboardModes.buildStep==='project','Failure return starts at stage 1');
 await dashboardModes.setBuildStep('lane');await wait(()=>!gpsLane.busy);assert($('gps-lane-dirty').textContent==='저장된 상태','Failed preview was discarded');$('gps-lane-apply').click();await wait(()=>!gpsLane.busy&&$('gps-lane-dirty').textContent.includes('미저장'));
 let release;const gate=new Promise(resolve=>release=resolve);gpsProject.save=async(...args)=>{await gate;return originalSave(...args);};
 const leaving=dashboardModes.set('rosbag');await wait(()=>$('center-mode').disabled);assert(dashboardModes.current==='map-build','Remain in editor until save completes');assert(await dashboardModes.set('none')===false,'Concurrent switch ignored');release();assert(await leaving,'Mode changes after save');gpsProject.save=originalSave;
 assert(dashboardModes.current==='rosbag','Requested destination shown');assert(gpsProject.current.project.stages['9'].lane_width_m===3.2,'Latest lane edit saved');
 const saved=await gpsProject.api('/api/gps/projects/load?filename='+encodeURIComponent(gpsProject.current.filename));assert(saved.project.stages['9'].lane_width_m===3.2,'Persisted on disk');
 await dashboardModes.set('map-build');assert(dashboardModes.buildStep==='project','Re-entry starts at stage 1');assert(!$('gps-project-rewind-dialog').open,'Re-entry does not rewind saved stages');assert(gpsProject.current.project.stages['9'],'Saved stage 8 preserved');
 await dashboardModes.setBuildStep('validation');await wait(()=>$('gps-map-reviewed-list').querySelectorAll('input').length>0);const checkbox=$('gps-map-reviewed-list').querySelector('input');checkbox.click();const checked=checkbox.dataset.bag;
 $('center-mode').value='rosbag';$('center-mode').dispatchEvent(new Event('change'));await wait(()=>dashboardModes.current==='rosbag');assert(gpsProject.current.project.stages['11'].validated_bags.includes(checked),'Checkbox edit autosaved by dropdown navigation');
 await dashboardModes.set('map-build');assert(dashboardModes.buildStep==='project','Every re-entry resets to stage 1');
 await dashboardModes.setBuildStep('export');$('gps-export-name').value='자동저장테스트';$('gps-export-name').dispatchEvent(new Event('input'));
 await dashboardModes.set('none');assert(gpsProject.current.filename.startsWith('12단계_')&&gpsProject.current.filename.endsWith('_자동저장테스트.json'),'Stage 11 filename edit autosaved');assert(gpsProject.current.project.stages['12'].export_filename.startsWith('MAP_'),'Stage 11 final MAP exported');
 await dashboardModes.set('map-build');await dashboardModes.setBuildStep('export');$('gps-export-competition').checked=false;$('gps-export-save').click();await wait(()=>!gpsExport.busy);const revision=gpsProject.current.project.revision;
 await dashboardModes.set('rosbag');assert(gpsProject.current.project.revision===revision,'Already saved stage 11 is not exported twice');
 await dashboardModes.set('map-build');assert(dashboardModes.buildStep==='project','Final return starts at stage 1');
 return 'Autosave before mode exit, failure discard and notice, concurrent-switch guard, saved stage preservation, validation checks, stage 11 export and stage 1 re-entry: passed';
}
