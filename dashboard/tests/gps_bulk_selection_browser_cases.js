/* Run with two fixture tracks of four points each, sharing the first three positions. */
async function gpsBulkSelectionBrowserCases(){
  const $=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);};
  const wait=async f=>{for(let i=0;i<200;i++){if(f())return;await new Promise(r=>setTimeout(r,20));}throw Error('GPS editor timeout');};
  window.dispatchEvent(new Event('dashboard:modechange'));
  await wait(()=>!gpsEditor.busy&&$('gps-test-tracks').children.length===2);
  const canvas=$('gps-test-canvas'),ctx=canvas.getContext('2d'),rows=[...$('gps-test-tracks').children];
  const coords=[],arc=ctx.arc;
  ctx.arc=function(x,y,r,...rest){if(r===4)coords.push([x,y]);return arc.call(this,x,y,r,...rest);};
  $('gps-test-fit').click();ctx.arc=arc;
  assert(coords.length===8,'Both fixture tracks rendered');
  // Synthetic events test the real canvas handlers; capture needs a physical pointer otherwise.
  canvas.setPointerCapture=()=>{};
  const event=(type,x,y,button=0)=>{const r=canvas.getBoundingClientRect();canvas.dispatchEvent(new PointerEvent(type,{clientX:r.left+x,clientY:r.top+y,pointerId:1,button,bubbles:true}));};
  const box=([x,y],button=0)=>{event('pointerdown',x-8,y-8,button);event('pointermove',x+8,y+8,button);event('pointerup',x+8,y+8,button);};
  const esc=()=>window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
  const count=n=>assert(canvas.dataset.selectedCount===String(n),`Expected ${n} selected, got ${canvas.dataset.selectedCount}`);
  const counts=(a,b)=>{assert(rows[0].textContent.includes(`남음 ${4-a} / 제외 ${a}점`),'First recording exclusion count');assert(rows[1].textContent.includes(`남음 ${4-b} / 제외 ${b}점`),'Second recording exclusion count');};
  box(coords[1]);count(2);box(coords[2]);count(4);box(coords[1]);count(4);
  assert($('gps-review-start').disabled&&$('gps-review-end').disabled,'Boundaries require a single selected point');
  $('gps-review-toggle').click();counts(2,2);
  assert($('gps-review-toggle').textContent==='선택 점 일괄 복원','Entire excluded selection can be restored');
  $('gps-review-undo').click();counts(0,0);
  assert($('gps-review-undo').disabled,'One undo restores both recordings atomically');
  // Mixed included/excluded selection must exclude every point, without toggling excluded points back on.
  esc();const slider=rows[0].querySelector('input[type=range]');slider.value=1;slider.oninput();
  $('gps-review-toggle').click();slider.value=slider.max;slider.oninput();esc();
  box(coords[1]);box(coords[2]);$('gps-review-toggle').click();counts(2,2);
  $('gps-review-undo').click();counts(1,0);
  $('gps-review-toggle').click();counts(2,2);
  await gpsEditor.save();
  assert(window.bulkSaved.stage===3,'Bulk edit uses stage 3 save');
  assert(window.bulkSaved.body.tracks.every(t=>JSON.stringify(t.excluded_seq)==='[2,3]'),'Saved exclusions include both records exactly once');
  $('gps-review-toggle').click();counts(0,0);
  esc();count(0);assert($('gps-review-toggle').disabled,'Escape clears action selection');
  // Existing click, overlapping candidate dropdown, slider and range operations still work.
  event('pointerdown',...coords[1]);event('pointerup',...coords[1]);count(1);
  assert($('gps-test-candidates').options.length===2,'Click keeps overlapping candidate chooser');
  $('gps-test-candidates').value='1';$('gps-test-candidates').onchange();count(1);
  slider.value=1;slider.oninput();$('gps-review-start').click();
  slider.value=2;slider.oninput();$('gps-review-end').click();
  slider.value=slider.max;slider.oninput();esc();
  box(coords[0]);count(2);box(coords[1]);count(4);$('gps-review-toggle').click();counts(3,2);
  $('gps-review-undo').click();counts(2,0);
  // Cancelled gestures do not select anything, and panning preserves selection.
  esc();event('pointerdown',0,0);event('pointermove',canvas.clientWidth,canvas.clientHeight);event('pointercancel',canvas.clientWidth,canvas.clientHeight);count(0);
  box(coords[1]);count(2);
  event('pointerdown',100,100,2);event('pointermove',130,120,2);event('pointerup',130,120,2);count(2);
  const check=rows[1].querySelector('input[type=checkbox]');esc();check.checked=false;check.onchange();$('gps-test-fit').click();
  event('pointerdown',0,0);event('pointermove',canvas.clientWidth,canvas.clientHeight);event('pointerup',canvas.clientWidth,canvas.clientHeight);count(4);
  check.checked=true;check.onchange();esc();
  // Stage 2 retains left-drag panning.
  dashboardModes.buildStep='bags';window.dispatchEvent(new Event('dashboard:modechange'));
  await wait(()=>!gpsEditor.busy);esc();
  event('pointerdown',0,0);event('pointermove',canvas.clientWidth,canvas.clientHeight);event('pointerup',canvas.clientWidth,canvas.clientHeight);count(0);
  assert(window.bulkErrors.length===0,'Browser errors: '+window.bulkErrors.join('; '));
  return 'PASS: overlap, additive drag, deduplication, cross-record exclude/restore, atomic undo, mixed exclusions, stage-3 save, click/candidates, range rules, Escape, cancellation, hidden records, panning and stage-2 behavior';
}
