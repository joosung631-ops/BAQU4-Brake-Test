/* Central visualization modes. Map editing is saved before leaving its mode.
 * Extend with dashboardModes.register('id', {label:'Name'}) and matching
 * data-center-view="id" / data-mode-panel="id" elements. Listen for
 * dashboard:modechange to start/pause rendering in future visualizations.
 */
(() => {
  const select=document.getElementById('center-mode');
  if(!select)return;
  const modes=new Map([['none',{label:'< 선택 안 함 >'}],['rosbag',{label:'1. ROS Bag 보기'}],['map-build',{label:'2. GPS 지도 생성'}],['brake',{label:'3. 제동 테스트'}],['sensors',{label:'4. 센서 확인'}],['map-position',{label:'5. MAP-현재 위치'}],['map-compare',{label:'6. MAP 비교하기'}]]);
  const storageKey='dashboard.centerMode';
  const stepSelect=document.getElementById('map-build-step');
  const stepStorageKey='dashboard.mapBuildStep';
  let buildStep='project';

  let current=null,transitioning=false;
  const lockSelectors=value=>{select.disabled=value;if(stepSelect)stepSelect.disabled=value;};
  function applyMode(id) {
    const previous=current;current=id;select.value=id;document.body.dataset.centerMode=id;
    if(stepSelect)stepSelect.value=buildStep;
    const inStep=el=>!el.dataset.buildStep||el.dataset.buildStep.split(' ').includes(buildStep);
    document.querySelectorAll('[data-center-view]').forEach(el=>{el.hidden=!(el.dataset.centerView.split(' ').includes(id)&&inStep(el));});
    document.querySelectorAll('[data-mode-panel]').forEach(el=>{el.hidden=!(el.dataset.modePanel.split(' ').includes(id)&&inStep(el));});
    try{sessionStorage.setItem(storageKey,id);}catch(_){}
    window.dispatchEvent(new CustomEvent('dashboard:modechange',{detail:{mode:id,previous,buildStep}}));
  }
  async function setMode(id) {
    if(id==='test')id='map-build';
    if(!modes.has(id))id='none';
    if(transitioning){select.value=current;return false;}
    transitioning=true;lockSelectors(true);
    try{
      if(current==='map-build'&&id!=='map-build'){
        select.value=current;
        if(window.gpsProject?.beforeLeave&&!await window.gpsProject.beforeLeave())return false;
        buildStep='project';
      }
      if(id==='map-build'&&current!=='map-build')buildStep='project';
      try{sessionStorage.setItem(stepStorageKey,buildStep);}catch(_){}
      applyMode(id);
      const status=document.getElementById('map-build-mode-status');if(status){if(status.dataset.lost!=='true'){status.hidden=true;status.textContent='';}delete status.dataset.lost;}
      return true;
    }finally{transitioning=false;lockSelectors(false);select.value=current;}
  }
  function register(id,definition) {
    if(!/^[a-z][a-z0-9-]*$/.test(id)||typeof definition?.label!=='string')throw new Error('Invalid visualization mode');
    modes.set(id,{label:definition.label});
    select.replaceChildren(...[...modes].map(([value,mode])=>new Option(mode.label,value)));
    setMode(current??'rosbag');
  }
  async function setBuildStep(step){
    if(!['project','bags','map-merge','points','add-points','matching','fusion','ordering','path','lane','sections','final-points','validation','export'].includes(step))return;
    if(transitioning){if(stepSelect)stepSelect.value=buildStep;return;}
    transitioning=true;lockSelectors(true);
    try{
      if(window.gpsProject&&!await window.gpsProject.beforeStep(step)){if(stepSelect)stepSelect.value=buildStep;return;}
      buildStep=step;try{sessionStorage.setItem(stepStorageKey,step);}catch(_){}
      applyMode('map-build');
    }finally{transitioning=false;lockSelectors(false);}
  }
  window.dashboardModes={register,set:setMode,setBuildStep,get current(){return current;},get buildStep(){return buildStep;}};
  stepSelect?.addEventListener('change',()=>setBuildStep(stepSelect.value));
  select.addEventListener('change',()=>setMode(select.value));
  let initial='rosbag';try{initial=sessionStorage.getItem(storageKey)||initial;}catch(_){}
  if(!modes.has(initial))initial='rosbag';
  setMode(initial);
})();
