async function gpsMergeBrowserCases(restored=false){
  const $=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);},wait=async f=>{for(let i=0;i<200;i++){if(f())return;await new Promise(r=>setTimeout(r,25));}throw Error('Timeout: '+f);};
  dashboardModes.setBuildStep('points');await wait(()=>!$('gps-review-save').disabled);
  assert(!$('gps-review-curves').checked,'Stage 1 displays original positions');
  $('gps-review-filename').value='2026-09-26-120000-browser-noise.json';$('gps-review-save').click();
  await wait(()=>$('gps-review-path').textContent.includes('browser-noise.json'));
  assert($('gps-review-path').textContent.includes('main/decision/'),'Stage 1 workspace path');
  dashboardModes.setBuildStep('matching');await wait(()=>$('gps-merge-files').options.length);
  $('gps-merge-files').value='2026-09-26-120000-browser-noise.json';$('gps-merge-load').click();
  const c=$('gps-merge-canvas');await wait(()=>c.dataset.pointCount==='5');await new Promise(r=>setTimeout(r,1500));
  c.setPointerCapture=()=>{};
  function event(type,x,y){const r=c.getBoundingClientRect();c.dispatchEvent(new PointerEvent(type,{clientX:r.left+x,clientY:r.top+y,pointerId:1,button:0,bubbles:true}));}
  function all(){const r=c.getBoundingClientRect();event('pointerdown',1,1);event('pointermove',r.width-1,r.height-1);event('pointerup',r.width-1,r.height-1);}
  all();assert(c.dataset.selectedCount==='5','Rectangle selection');
  let p=JSON.parse(c.dataset.preview);assert(Math.abs(p.lat-37.0002)<1e-10,'Mean preview');assert(c.dataset.pointCount==='5','Preview does not mutate');
  // The middle point is at the canvas center for this symmetric test track.
  const r=c.getBoundingClientRect();event('pointerdown',r.width/2,r.height/2);event('pointerup',r.width/2,r.height/2);
  assert(c.dataset.selectedCount==='4','Click toggles selection');assert($('gps-merge-confirm').disabled,'Nonconsecutive selection rejected');
  event('pointerdown',r.width/2,r.height/2);event('pointerup',r.width/2,r.height/2);assert(c.dataset.selectedCount==='5','Click adds selection');
  $('gps-merge-confirm').click();assert(c.dataset.pointCount==='1','Confirm collapses selected points');
  assert($('gps-merge-load').disabled,'Unsaved edits protected');
  $('gps-merge-undo').click();assert(c.dataset.pointCount==='5','Undo restores original points');
  all();$('gps-merge-confirm').click();$('gps-merge-filename').value='2026-09-26-120001-browser-merge.json';$('gps-merge-save').click();
  await wait(()=>$('gps-merge-path').textContent.includes('browser-merge.json'));
  await wait(()=>!$('gps-merge-load').disabled);
  $('gps-merge-files').value='2026-09-26-120001-browser-merge.json';$('gps-merge-load').click();
  await wait(()=>$('gps-merge-path').textContent.startsWith('입력:')&&c.dataset.pointCount==='1');
  assert(c.dataset.selectedCount==='0','Reload clears pending selection');
  dashboardModes.setBuildStep('points');assert(!$('gps-test-canvas').closest('[data-center-view]').hidden,'Stage 1 still usable');
  return 'Named stage saves, drag/click selection, mean preview, confirm, undo, reload and navigation: passed';
}
