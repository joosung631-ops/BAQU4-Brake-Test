async function gpsProjectBrowserCases(){
 const $=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);},wait=async f=>{for(let i=0;i<300;i++){if(f())return;await new Promise(r=>setTimeout(r,25));}throw Error('Timeout '+f);};
 const api=gpsProject.api,rv=await api('/api/gps/review');
 let p=await api('/api/gps/projects/create',{filename:'1단계_2026-01-01_010203_나의_경로.json'});
 p=await api('/api/gps/projects/save',{filename:p.filename,revision:p.project.revision,stage:2,dataset_id:rv.dataset_id,display:{linear:true,smooth:true}});
 p=await api('/api/gps/projects/save',{filename:p.filename,revision:p.project.revision,stage:3,dataset_id:rv.dataset_id,tracks:rv.tracks.map(t=>({id:t.id,excluded_seq:[2]}))});
 await dashboardModes.setBuildStep('project');$('gps-project-method').value='edit';$('gps-project-method').dispatchEvent(new Event('change'));$('gps-project-refresh').click();
 await wait(()=>[...$('gps-project-files').options].some(o=>JSON.parse(o.value).filename===p.filename));
 $('gps-project-files').value=JSON.stringify({filename:p.filename,kind:'project'});$('gps-project-files').dispatchEvent(new Event('change'));
 assert($('gps-project-name').disabled,'Existing mode disables filename');assert($('gps-project-progress').textContent.includes('3단계부터 진행'),'Saved-stage resume guidance');
 $('gps-project-open').click();await wait(()=>gpsProject.current?.filename.endsWith('_나의_경로.json'));
 const resumed=gpsProject.current.filename;assert(resumed!==p.filename&&resumed.startsWith('3단계_'),'Timestamp refreshed and suffix retained');
 assert((await fetch('/api/gps/projects/load?filename='+encodeURIComponent(p.filename))).status===404,'Previous file removed after successful resume');
 await wait(()=>!gpsProject.busy);
 let moving=dashboardModes.setBuildStep('bags');await wait(()=>$('gps-project-rewind-dialog').open);$('gps-project-rewind-cancel').click();await moving;
 assert(dashboardModes.buildStep==='project'&&gpsProject.current.project.stages['3'],'Cancel protects loaded downstream stages while in stage 1');
 $('gps-project-resume').value='new';$('gps-project-resume').dispatchEvent(new Event('change'));
 assert(!$('gps-project-name').disabled&&!$('gps-project-create').hidden,'New-file mode enables name input');
 $('gps-project-name').value='1단계_2026-09-26_000000_복사';$('gps-project-create').click();await wait(()=>gpsProject.current?.filename==='1단계_2026-09-26_000000_복사.json');await wait(()=>!gpsProject.busy);
 const original=await api('/api/gps/projects/load?filename='+encodeURIComponent(resumed));assert(original.project.stages['3'],'New-file mode preserves original');
 moving=dashboardModes.setBuildStep('bags');await wait(()=>$('gps-project-rewind-dialog').open);$('gps-project-rewind-continue').click();await moving;
 assert(dashboardModes.buildStep==='bags'&&!gpsProject.current.project.stages['3'],'Earlier-than-saved stage confirms and removes later data');
 const disk=await api('/api/gps/projects/load?filename='+encodeURIComponent(gpsProject.current.filename));assert(!disk.project.stages['3'],'Deletion persisted');
 assert((await api('/api/gps/projects/load?filename='+encodeURIComponent(resumed))).project.stages['3'],'Copied-file rewind preserves original');
 return 'Resume modes, filename enablement, progress guidance, timestamp rotation, loaded-stage rewind and copy preservation: passed';
}
