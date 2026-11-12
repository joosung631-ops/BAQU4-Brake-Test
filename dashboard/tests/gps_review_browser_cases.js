async function gpsReviewBrowserCases(restored=false) {
  const get=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);};
  const wait=async predicate=>{for(let i=0;i<150;i++){if(predicate())return;await new Promise(r=>setTimeout(r,40));}throw Error('Timed out: '+get('gps-review-status').textContent);};
  dashboardModes.setBuildStep('points');await wait(()=>get('gps-test-tracks').children.length===2);
  const row=get('gps-test-tracks').children[0],slider=row.querySelector('input[type=range]');
  const smooth=row.querySelector('input[type=number]'),complete=row.querySelectorAll('input[type=checkbox]')[1];
  assert(Number(get('gps-test-canvas').dataset.curveSegmentCount)>0,'Smooth curves rendered');
  slider.value=0;slider.oninput();
  if(restored){
    assert(get('gps-review-toggle').textContent==='선택 점 복원','Excluded point restored from disk');
    assert(Number(smooth.value)===1.2&&complete.checked,'Smoothing and completion persisted');
    assert(get('gps-review-save').disabled,'Reloaded state is clean');
    return 'Reload restores exclusion, smoothing and completed review: passed';
  }
  get('gps-review-toggle').onclick();assert(get('gps-review-selection').textContent.includes('제외됨'),'Point excluded');
  await wait(()=>!row.textContent.includes('계산 중'));
  assert(row.textContent.includes('남음 370 / 제외 1점'),'Counts reflect exclusion');
  get('gps-review-undo').onclick();assert(get('gps-review-toggle').textContent==='선택 점 제외','Undo restores point');
  get('gps-review-toggle').onclick();get('gps-review-toggle').onclick();
  assert(row.textContent.includes('남음 371 / 제외 0점'),'Direct restoration');
  get('gps-review-toggle').onclick();smooth.value=1.2;smooth.onchange();complete.checked=true;complete.onchange();
  await wait(()=>!row.textContent.includes('계산 중'));
  slider.value=slider.max;slider.oninput();
  assert(Number(get('gps-test-canvas').dataset.curveSegmentCount)>0,'Curve recomputed after edits');
  await get('gps-review-save').onclick();
  assert(get('gps-review-status').textContent.includes('저장 완료'),'Save acknowledged');
  const saved=await (await fetch('/api/gps/review')).json();
  assert(saved.tracks[0].excluded_seq.join(',')==='1','Excluded IDs persisted');
  assert(saved.tracks[0].retained_points.length===370&&!saved.tracks[0].retained_points.some(p=>p.seq===1),'Retained coordinates persisted');
  assert(saved.tracks[1].retained_points.length===163,'Other bag unchanged');
  return 'Curve preview, exclude, restore, undo and local persistence: passed';
}
