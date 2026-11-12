async function gpsRangeBrowserCases(restored=false){
  const get=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);};
  dashboardModes.setBuildStep('points');
  for(let i=0;i<150&&!get('gps-test-tracks').children.length;i++)await new Promise(r=>setTimeout(r,30));
  const row=get('gps-test-tracks').children[0],slider=row.querySelector('input[type=range]');
  const pick=seq=>{slider.value=seq-1;slider.oninput();};
  if(!restored){
    pick(15);get('gps-review-toggle').onclick();
    pick(10);get('gps-review-start').onclick();pick(20);get('gps-review-end').onclick();
    assert(row.textContent.includes('남음 10 / 제외 361점'),'Range and manual exclusion combine');
    pick(25);assert(get('gps-review-start').disabled,'Reversed boundary prevented');
    assert(get('gps-review-toggle').disabled,'Outside-range point cannot be individually restored');
    get('gps-review-range-reset').onclick();assert(row.textContent.includes('남음 370 / 제외 1점'),'Range reset preserves manual exclusion');
    get('gps-review-undo').onclick();assert(row.textContent.includes('범위 #10~#20'),'Undo restores range');
    await get('gps-review-save').onclick();assert(get('gps-review-status').textContent.includes('저장 완료'),'Range saved');
  }
  const state=await(await fetch('/api/gps/review')).json(),t=state.tracks[0];
  assert(t.start_seq===10&&t.end_seq===20,'Boundaries persist');
  assert(t.manual_excluded_seq.join(',')==='15','Manual exclusions separate');
  assert(t.retained_points.map(p=>p.seq).join(',')==='10,11,12,13,14,16,17,18,19,20','Remaining points exact');
  assert(row.textContent.includes('범위 #10~#20'),'UI restores boundaries');
  const canvas=get('gps-test-canvas'),ctx=canvas.getContext('2d'),fill=ctx.fillText,labels=[];
  ctx.fillText=function(s,...args){labels.push(s);return fill.call(this,s,...args);};get('gps-test-fit').onclick();ctx.fillText=fill;
  assert(labels.includes('2026-09-20_4 시작 #10')&&labels.includes('2026-09-20_4 끝 #20'),'Markers move to selected bounds');
  return 'Range selection, reset, undo, persistence and endpoint markers: passed';
}
