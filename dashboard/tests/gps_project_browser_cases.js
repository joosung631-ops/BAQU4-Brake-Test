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
  await dashboardModes.setBuildStep('project');assert(gpsProject.current.project.stages['5'].tracks[0].points.length===1,'Stage 4 autosaved in same file');
  assert(Object.keys(gpsProject.current.project.stages).length===4,'All four stages in one project');
  const original=JSON.stringify(gpsProject.current.project);
  $('gps-project-method').value='edit';$('gps-project-method').dispatchEvent(new Event('change'));
  $('gps-project-refresh').click();await wait(()=>[...$('gps-project-files').options].some(o=>o.text==='browser-project-original.json'));
  $('gps-project-files').value=JSON.stringify({filename:'browser-project-original.json',kind:'project'});
  $('gps-project-name').value='browser-project-copy';$('gps-project-create').click();await wait(()=>gpsProject.current.filename==='browser-project-copy.json');
  await dashboardModes.setBuildStep('points');await new Promise(r=>setTimeout(r,200));const slider2=$('gps-test-tracks').querySelector('input[type=range]');slider2.value=1;slider2.oninput();assert($('gps-review-toggle').textContent==='선택 점 복원','Exclusions restored from copied file');$('gps-review-toggle').click();
  await dashboardModes.setBuildStep('project');assert(!gpsProject.current.project.stages['5'],'Changed noise invalidates later stage');assert(gpsProject.current.project.history.length,'Previous merged results retained in history');
  const saved=await (await realFetch('/api/gps/projects/load?filename=browser-project-original.json')).json();assert(JSON.stringify(saved.project)===original,'Original file unchanged by copy edits');
  assert($('gps-project-path').textContent.includes('review/maps/browser-project-copy.json'),'Save path shown');
  return 'Four-stage autosave, bag overlays, independent line toggles, exclusion, merge, copy/edit and original preservation: passed';
}
