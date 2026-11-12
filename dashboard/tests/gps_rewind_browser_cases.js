async function gpsProjectBrowserCases(){
  const $=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);},wait=async f=>{for(let i=0;i<300;i++){if(f())return;await new Promise(r=>setTimeout(r,25));}throw Error('Timeout: '+f);};
  const realFetch=window.fetch;let prepared=false;
  window.fetch=(url,...rest)=>{if(String(url).startsWith('/api/gps/source/')){
    let result;if(String(url).endsWith('/bags'))result={bags:['test-a','test-b'].map(id=>({id,name:id,supported:true,gps_count:5})),selected:prepared?['test-a','test-b']:[]};
    else if(String(url).endsWith('/prepare')){prepared=true;result={job_id:'test',phase:'running'};}
    else result={job_id:'test',phase:prepared?'done':'idle',total:2,point_count:10};
    return Promise.resolve(new Response(JSON.stringify(result),{headers:{'Content-Type':'application/json'}}));
  }return realFetch(url,...rest);};
  await dashboardModes.setBuildStep('project');assert($('map-build-step').options.length===4,'Four workflow stages');
  $('gps-project-name').value='browser-project-original';$('gps-project-create').click();await wait(()=>gpsProject.current?.filename==='browser-project-original.json');
  await dashboardModes.setBuildStep('bags');await wait(()=>$('gps-source-list').querySelectorAll('input').length===2);
  assert($('gps-review-raw').checked&&$('gps-review-curves').checked,'Both comparisons default checked');
  $('gps-source-all').click();$('gps-source-load').click();await wait(()=>$('gps-source-status').textContent.includes('불러오기 완료'));
  assert($('gps-test-canvas').dataset.pointCount==='10','Two bags overlaid');assert(Number($('gps-test-canvas').dataset.curveSegmentCount)>0,'Smoothed overlay visible');
  $('gps-review-curves').click();assert($('gps-test-canvas').dataset.curveSegmentCount==='0','Smooth toggle independent');$('gps-review-curves').click();
  $('gps-review-raw').click();assert($('gps-test-canvas').dataset.segmentCount==='0','Linear toggle independent');$('gps-review-raw').click();
  await dashboardModes.setBuildStep('points');await wait(()=>!$('gps-review-save').disabled);await new Promise(r=>setTimeout(r,200));
  assert(gpsProject.current.project.stages['2'].raw.tracks.length===2,'Stage 2 autosaved source GPS');
  const slider=$('gps-test-tracks').querySelector('input[type=range]');slider.value=1;slider.oninput();$('gps-review-toggle').click();
  await dashboardModes.setBuildStep('matching');await wait(()=>$('gps-merge-canvas').dataset.pointCount==='9');
  assert(gpsProject.current.project.stages['3'].tracks[0].excluded_seq.includes(2),'Stage 3 autosaved exclusions');
  const c=$('gps-merge-canvas');c.setPointerCapture=()=>{};const r=c.getBoundingClientRect();
  const event=(type,x,y)=>c.dispatchEvent(new PointerEvent(type,{clientX:r.left+x,clientY:r.top+y,pointerId:1,button:0,bubbles:true}));
  event('pointerdown',1,1);event('pointermove',r.width-1,r.height-1);event('pointerup',r.width-1,r.height-1);assert(c.dataset.selectedCount==='4','Active bag rectangle selection');$('gps-merge-confirm').click();
  assert(c.dataset.pointCount==='6','Only selected bag merged');

  await gpsMerger.save();const before=JSON.stringify(gpsProject.current);$('gps-merge-undo').click();
  const count=c.dataset.pointCount;
  let moving=dashboardModes.setBuildStep('points');await wait(()=>$('gps-project-rewind-dialog').open);
  assert($('gps-project-rewind-message').textContent==='앞 단계로 이동하면 뒷 단계의 검토 내용이 모두 제거됩니다. 계속하시겠습니까?','Exact confirmation message');
  $('gps-project-rewind-cancel').click();await moving;
  assert(dashboardModes.buildStep==='matching'&&$('map-build-step').value==='matching','Cancel stays in current stage');
  assert(c.dataset.pointCount===count&&JSON.stringify(gpsProject.current)===before,'Cancel preserves unsaved edits and project');
  let disk=await (await realFetch('/api/gps/projects/load?filename=browser-project-original.json')).json();assert(JSON.stringify(disk)===before,'Cancel does not write file');
  moving=dashboardModes.setBuildStep('points');await wait(()=>$('gps-project-rewind-dialog').open);$('gps-project-rewind-continue').click();await moving;
  assert(dashboardModes.buildStep==='points','Continue navigates to requested stage');
  assert(!gpsProject.current.project.stages['5']&&gpsProject.current.project.stages['3'].tracks[0].excluded_seq.includes(2),'Only downstream results removed');
  await new Promise(r=>setTimeout(r,250));
  moving=dashboardModes.setBuildStep('bags');await wait(()=>$('gps-project-rewind-dialog').open);$('gps-project-rewind-continue').click();await moving;
  await wait(()=>$('gps-test-canvas').dataset.pointCount==='10');
  assert(!gpsProject.current.project.stages['3']&&!gpsProject.current.project.stages['5'],'Rewind to bags clears review and merge');
  await new Promise(r=>setTimeout(r,250));
  moving=dashboardModes.setBuildStep('project');await wait(()=>$('gps-project-rewind-dialog').open);$('gps-project-rewind-continue').click();await moving;
  disk=await (await realFetch('/api/gps/projects/load?filename=browser-project-original.json')).json();assert(Object.keys(disk.project.stages).join()==='1','Rewind to stage 1 deletes all later stages from file');
  assert(!disk.project.history,'No downstream review history retained');
  return 'Rewind confirmation, cancel preservation, continue navigation, downstream file deletion: passed';
}
