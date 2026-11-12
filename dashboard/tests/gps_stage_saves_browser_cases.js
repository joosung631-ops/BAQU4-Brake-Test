async function gpsProjectBrowserCases(){
 const $=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);},wait=async f=>{for(let i=0;i<400;i++){if(f())return;await new Promise(r=>setTimeout(r,25));}throw Error('timeout');};
 async function open(name){await wait(()=>$('gps-project-files').options.length>0);$('gps-project-method').value='edit';$('gps-project-method').dispatchEvent(new Event('change'));const o=[...$('gps-project-files').options].find(o=>JSON.parse(o.value).filename===name);assert(o,'fixture '+name);$('gps-project-files').value=o.value;$('gps-project-open').click();await wait(()=>!gpsProject.busy&&gpsProject.current?.filename.includes(name.slice(0,-5)));}
 await dashboardModes.setBuildStep('project');await open('early-test.json');
 await dashboardModes.setBuildStep('bags');await wait(()=>!gpsEditor.busy&&!$('gps-source-save').disabled);
 assert($('gps-source-used').textContent.includes('2026-09-20_4')&&$('gps-source-used').textContent.includes('저장됨'),'Extraction sources shown');
 let old=gpsProject.current.filename;$('gps-source-save').click();await wait(()=>!gpsEditor.busy&&gpsProject.current.filename!==old);assert(gpsProject.current.filename.startsWith('2단계_'),'Stage 2 save renames');
 await dashboardModes.setBuildStep('points');await wait(()=>!gpsEditor.busy&&!$('gps-review-save').disabled);$('gps-review-save').click();await wait(()=>!gpsEditor.busy&&gpsProject.current.filename.startsWith('3단계_'));
 let move=dashboardModes.setBuildStep('project');await wait(()=>$('gps-project-rewind-dialog').open);$('gps-project-rewind-dialog').close('continue');await move;
 await open('late-test.json');await dashboardModes.setBuildStep('validation');await wait(()=>$('gps-map-reviewed-list').querySelectorAll('input').length>2);
 const ids=['2026-09-20/2026-09-20_4','2026-09-20/2026-09-20_5'];for(const id of ids){const check=[...$('gps-map-reviewed-list').querySelectorAll('input')].find(e=>e.dataset.bag===id);assert(check,'bag in verification list');check.click();}
 $('gps-map-review-save').click();await wait(()=>!gpsReplay.busy&&gpsProject.current.filename.startsWith('11단계_'));
 assert(JSON.stringify(gpsProject.current.project.stages['11'].validated_bags)===JSON.stringify(ids),'Checked bag IDs saved');assert(JSON.stringify(gpsProject.current.project.stages['2'].bags)===JSON.stringify(ids),'Extraction IDs preserved');
 await dashboardModes.setBuildStep('validation');await wait(()=>!gpsReplay.busy);assert($('gps-map-reviewed-list').querySelectorAll('input:checked').length===2,'Saved checks restored');
 await dashboardModes.setBuildStep('export');assert($('gps-export-name').value.startsWith('12단계_'),'Stage 11 default filename');
 $('gps-export-name').value='12단계_2026-09-26_120000_검증테스트';$('gps-export-name').dispatchEvent(new Event('input'));$('gps-export-competition').checked=false;$('gps-export-save').click();await wait(()=>!gpsExport.busy);
 assert(gpsProject.current.filename.startsWith('12단계_')&&gpsProject.current.filename.endsWith('_검증테스트.json'),'Working file stored as stage 11');assert($('gps-export-output-path').textContent.includes('MAP_')&&$('gps-export-output-path').textContent.endsWith('_검증테스트.json'),'Separate MAP file');
 assert(gpsProject.current.project.stages['11'].validated_bags.length===2,'Verification history retained at final save');assert(gpsProject.current.project.stages['12'].export_filename.startsWith('MAP_'),'Final checkpoint recorded');
 return 'Numbered saves for stages 2, 3, 9, 10; extraction source display; verification checklist save/reload; separate final MAP: passed';
}
