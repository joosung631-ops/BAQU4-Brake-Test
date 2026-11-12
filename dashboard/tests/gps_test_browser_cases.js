async function gpsTestBrowserCases() {
  const assert=(v,m)=>{if(!v)throw Error(m);}, get=id=>document.getElementById(id);
  dashboardModes.setBuildStep('points');
  for(let i=0;i<100 && !get('gps-test-tracks').children.length;i++)await new Promise(r=>setTimeout(r,50));
  const canvas=get('gps-test-canvas'),rows=[...get('gps-test-tracks').children];
  assert(rows.length===2,'Both raw bags loaded');
  assert(canvas.offsetParent!==null,'Test canvas visible');
  assert(canvas.dataset.pointCount==='534','All raw points retained');
  assert(canvas.dataset.segmentCount==='532','No connection between bags');
  assert(canvas.dataset.endpointCount==='4','Both start/end markers shown');
  const labels=[],ctx=canvas.getContext('2d'),original=ctx.fillText;
  ctx.fillText=function(text,...args){labels.push(text);return original.call(this,text,...args);};
  get('gps-test-fit').onclick();ctx.fillText=original;
  for(const name of ['2026-09-20_4','2026-09-20_5'])for(const kind of ['시작','끝'])
    assert(labels.some(s=>s.includes(`${name} ${kind} #`)),'Endpoint label identifies bag and sequence');
  const check=rows[0].querySelector('input[type=checkbox]');check.checked=false;check.onchange();
  assert(canvas.dataset.pointCount==='163','Individual visibility');
  assert(canvas.dataset.endpointCount==='2','Hidden bag markers hidden');
  const slider=rows[1].querySelector('input[type=range]');slider.value=0;slider.oninput();
  assert(canvas.dataset.pointCount==='1'&&canvas.dataset.segmentCount==='0','Slider reveals only prefix');
  assert(canvas.dataset.endpointCount==='2','Full-recording endpoints remain');
  assert(get('gps-test-info').textContent.includes('2026-09-20_5 · 원본 #1'),'Sequence and coordinate details');
  dashboardModes.set('none');assert(canvas.offsetParent===null,'None remains blank');
  dashboardModes.setBuildStep('points');assert(canvas.dataset.pointCount==='1','Mode switching preserves controls');
  check.checked=true;check.onchange();slider.value=slider.max;slider.oninput();get('gps-test-fit').onclick();
  // Click a rendered GPS point and resolve overlapping visits explicitly.
  const coords=[],arc=ctx.arc;
  ctx.arc=function(x,y,r,...args){if(r===4)coords.push([x,y]);return arc.call(this,x,y,r,...args);};
  get('gps-test-fit').onclick();ctx.arc=arc;
  const rect=canvas.getBoundingClientRect(),[x,y]=coords[0];
  const capture=canvas.setPointerCapture;canvas.setPointerCapture=()=>{};
  canvas.dispatchEvent(new PointerEvent('pointerdown',{clientX:rect.left+x,clientY:rect.top+y,pointerId:1}));
  canvas.dispatchEvent(new PointerEvent('pointerup',{clientX:rect.left+x,clientY:rect.top+y,pointerId:1}));
  canvas.setPointerCapture=capture;
  const candidates=get('gps-test-candidates');
  assert(!candidates.disabled&&candidates.options.length>0,'Map click selects candidate points');
  const target=[...candidates.options].find(o=>o.textContent==='2026-09-20_4 · #1');
  assert(target,'Clicked start point is selectable');
  candidates.value=target.value;candidates.onchange();
  const firstSlider=rows[0].querySelector('input[type=range]');firstSlider.value=0;firstSlider.oninput();
  async function loadedCamera(expected){
    for(let i=0;i<100;i++){
      const img=get('gps-test-camera-image');
      if(!img.hidden&&img.complete&&img.naturalWidth>0&&get('gps-test-camera-info').textContent.includes(expected))return;
      await new Promise(r=>setTimeout(r,30));
    }
    throw Error('Camera did not load: '+expected+' / '+get('gps-test-camera-message').textContent);
  }
  await loadedCamera('2026-09-20_4 · 원본 #1');
  assert(get('gps-test-camera-info').textContent.includes('ms'),'Timestamp difference shown');
  const firstSource=get('gps-test-camera-image').src;
  slider.value=0;slider.oninput();await loadedCamera('2026-09-20_5 · 원본 #1');
  assert(get('gps-test-camera-image').src!==firstSource,'Frame belongs to selected bag');
  firstSlider.value=10;firstSlider.oninput();slider.value=20;slider.oninput();
  await loadedCamera('2026-09-20_5 · 원본 #21');
  assert(get('gps-test-camera-image').alt.includes('2026-09-20_5 GPS #21'),'Rapid changes keep newest frame');
  return 'Raw paths, endpoint markers, sliders, camera sync and selection races: passed';
}
