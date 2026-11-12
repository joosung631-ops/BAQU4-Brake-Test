async function gpsProjectBrowserCases(){
 const $=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);},wait=async f=>{for(let i=0;i<400;i++){if(f())return;await new Promise(r=>setTimeout(r,25));}throw Error('timeout');};
 await dashboardModes.setBuildStep('project');await wait(()=>$('gps-project-files').options.length>0);
 $('gps-project-method').value='edit';$('gps-project-method').dispatchEvent(new Event('change'));
 const option=[...$('gps-project-files').options].find(o=>JSON.parse(o.value).filename==='lane-browser.json');assert(option,'fixture found');$('gps-project-files').value=option.value;
 $('gps-project-open').click();await wait(()=>gpsProject.current&&!gpsProject.busy);
 await dashboardModes.setBuildStep('export');assert(dashboardModes.buildStep==='export','Stage 11 opens');
 const original=gpsProject.current.filename;assert($('gps-export-name').value.startsWith('12단계_'),'Stage 11 default filename');
 assert($('gps-export-working-path').textContent.includes('12단계_'),'Stage 11 working path shown');assert($('gps-export-output-path').textContent.includes('MAP_'),'Export path preview shown');
 $('gps-export-name').value='1단계_2026-09-26_120000_최종테스트';$('gps-export-name').dispatchEvent(new Event('input'));
 $('gps-export-competition').checked=false;$('gps-export-save').click();await wait(()=>!gpsExport.busy);assert($('gps-export-status').textContent.includes('별도 파일로 저장'),'Final export succeeds');
 assert(gpsProject.current.filename.startsWith('12단계_')&&gpsProject.current.filename.endsWith('_최종테스트.json'),'Working filename changed');
 assert($('gps-export-output-path').textContent.includes('_최종테스트.json'),'Export uses entered suffix');
 const files=await gpsProject.api('/api/gps/projects');assert(!files.files.some(f=>f.filename===original),'Old working filename removed');assert(files.files.some(f=>f.filename===gpsProject.current.filename),'Renamed working file exists');assert(!files.files.some(f=>f.filename.startsWith('MAP_')),'Final maps excluded from editing project list');
 let move=dashboardModes.setBuildStep('validation');await wait(()=>$('gps-project-rewind-dialog').open);$('gps-project-rewind-dialog').close('continue');await move;assert(dashboardModes.buildStep==='validation','Return to read-only stage 9 supported');
 await dashboardModes.setBuildStep('export');assert($('gps-export-name').value.startsWith('12단계_')&&$('gps-export-name').value.endsWith('_최종테스트'),'Renamed suffix retained');
 return 'Stage 11 default filename, path previews, working-file rename, separate final map, and return to validation: passed';
}
