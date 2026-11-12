async function gpsProjectBrowserCases(){
 const $=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);},wait=async f=>{for(let i=0;i<300;i++){if(f())return;await new Promise(r=>setTimeout(r,25));}throw Error('timeout');};
 await dashboardModes.setBuildStep('project');await wait(()=>$('gps-project-files').options.length>0);
 $('gps-project-method').value='edit';$('gps-project-method').dispatchEvent(new Event('change'));
 $('gps-project-resume').value='existing';$('gps-project-resume').dispatchEvent(new Event('change'));
 const option=[...$('gps-project-files').options].find(o=>JSON.parse(o.value).filename==='lane-browser.json');assert(option,'Test project available');$('gps-project-files').value=option.value;
 $('gps-project-open').click();await wait(()=>gpsProject.current&&!gpsProject.busy);
 await dashboardModes.setBuildStep('validation');await wait(()=>!gpsLane.busy);assert(dashboardModes.buildStep==='validation','Resume saved stage 8 into validation');
 const original=JSON.stringify(gpsProject.current.project.stages['9']);
 let move=dashboardModes.setBuildStep('lane');await wait(()=>$('gps-project-rewind-dialog').open);$('gps-project-rewind-dialog').close('cancel');await move;
 assert(dashboardModes.buildStep==='validation','Cancel keeps validation open');
 move=dashboardModes.setBuildStep('lane');await wait(()=>$('gps-project-rewind-dialog').open);$('gps-project-rewind-dialog').close('continue');await move;await wait(()=>!gpsLane.busy);
 assert(dashboardModes.buildStep==='lane','Continue returns to lane editing');assert(JSON.stringify(gpsProject.current.project.stages['9'])===original,'Returning preserves stage 8 input');
 $('gps-lane-cancel').click();assert(!$('gps-lane-save').disabled,'Lane change pending save');await dashboardModes.setBuildStep('validation');await wait(()=>!gpsLane.busy);
 assert(dashboardModes.buildStep==='validation','Can advance after editing');assert(gpsProject.current.project.stages['9'].enabled===false,'Advancing automatically saves lane changes');assert($('gps-lane-canvas').dataset.edgeCount==='0','Validation uses the updated saved result');
 return 'Stage 9 resume, back-step confirmation/cancel, stage 8 preservation and automatic save before validation: passed';
}
