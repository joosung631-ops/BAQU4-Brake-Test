async function mapBuildBrowserCases(restored=false){
  const get=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);};
  const select=get('map-build-step'),canvas=get('gps-test-canvas');
  if(restored){
    assert(dashboardModes.current==='map-build'&&dashboardModes.buildStep==='matching','Stage persists after reload');
    assert(select.value==='matching'&&canvas.closest('[data-center-view]').hidden,'Stage 2 restored');
    return 'Stage persistence: passed';
  }
  const mode=get('center-mode');mode.value='map-build';mode.dispatchEvent(new Event('change'));
  assert(select.offsetParent!==null,'Small stage selector visible');
  select.value='points';select.dispatchEvent(new Event('change'));
  for(let i=0;i<150&&!get('gps-test-tracks').children.length;i++)await new Promise(r=>setTimeout(r,30));
  assert(!canvas.closest('[data-center-view]').hidden,'GPS editor in stage 1');
  const slider=get('gps-test-tracks').querySelector('input[type=range]');slider.value=10;slider.oninput();
  select.value='matching';select.dispatchEvent(new Event('change'));
  assert(dashboardModes.buildStep==='matching'&&canvas.closest('[data-center-view]').hidden,'Next hides editor');
  assert(get('gps-test-camera-title').closest('[data-mode-panel]').hidden,'Next hides camera');
  assert(!document.querySelector('[data-center-view][data-build-step="matching"]').hidden,'Next shows stage 2');
  select.value='points';select.dispatchEvent(new Event('change'));
  assert(slider.value==='10'&&!canvas.closest('[data-center-view]').hidden,'Back preserves current inspection');
  dashboardModes.set('none');assert(select.offsetParent===null,'Selector hidden outside builder');
  dashboardModes.setBuildStep('matching');
  return 'Builder selection, stage navigation, camera visibility and state preservation: passed';
}
