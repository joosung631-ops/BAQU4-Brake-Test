/* File-scoped workflow coordinator. All stages share one revisioned project. */
(() => {
  const $=id=>document.getElementById(id);let current=null,busy=false,resumeStage=0,refreshName=false;
  const stageNames=['','맵 파일 생성·불러오기','ROS bag 선택','GPS 노이즈 제거','임의 GPS 포인트 추가','인접 GPS 포인트 병합','다중 로스백 GPS 병합','GPS 순서 매칭','최종 주행 경로 생성','예상 차선 적용','과제 구간 설정','최종 예상 Map 검증','최종 Map 저장'];
  // Stage IDs remain compatible with existing files and editor APIs.
  const order=['project','bags','points','add-points','matching','fusion','ordering','path','lane','sections','validation','export'];
  stageNames[10.5]='최종 웨이포인트 추가';
  const stageFor=step=>step==='final-points'?10.5:order.indexOf(step)+1;
  stageNames[2.5]='MAP 병합하기';
  const lastStage=()=>Math.max(...Object.keys(current.project.stages).map(Number),current.project.map_merge_result?2.5:1);
  const mapMergeEnabled=()=>current?.project.stages['2']?.map_merge===true;
  const stageNumber=(stage,enabled=mapMergeEnabled())=>stage===2.5?3:(stage===10.5?11:stage+Number(stage>=11))+(enabled&&stage>=3?1:0);
  const formatStages=text=>String(text).replace(/(\d+)단계(?!_)/g,(_,n)=>`${stageNumber(Number(n))}단계`);
  function showSteps(){
    const select=$('map-build-step'),selected=window.dashboardModes?.buildStep||select.value;
    if(!select.querySelector('[value="map-merge"]')&&mapMergeEnabled())select.add(new Option('3. MAP 병합하기','map-merge'),2);
    if(!mapMergeEnabled())select.querySelector('[value="map-merge"]')?.remove();
    for(const option of select.options){const index=order.indexOf(option.value);if(index>=0)option.textContent=`${stageNumber(index+1)}. ${stageNames[index+1]}`;}
    if(!select.querySelector('[value="final-points"]'))select.add(new Option('최종 웨이포인트 추가','final-points'),select.querySelector('[value="validation"]'));
    select.querySelector('[value="final-points"]').textContent=`${stageNumber(10.5)}. 최종 웨이포인트 추가`;
    select.value=selected;
    document.querySelectorAll('[data-gps-stage-number]').forEach(el=>{el.textContent=stageNumber(Number(el.dataset.gpsStageNumber));});
  }
  const defaultName=()=>{const d=new Date(),p=n=>String(n).padStart(2,'0');return `1단계_${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}_`;};
  $('gps-project-name').value=defaultName();
  const msg=(s,error=false)=>{s=formatStages(s);$('gps-project-status').textContent=s;if(error){const step=window.dashboardModes?.buildStep,id=step==='final-points'?'gps-final-status':step==='sections'?'gps-section-status':step==='export'?'gps-export-status':(step==='lane'||step==='validation')?'gps-lane-status':step==='path'?'gps-path-status':step==='ordering'?'gps-order-status':step==='fusion'?'gps-fusion-status':step==='add-points'?'gps-add-status':step==='matching'?'gps-merge-status':step==='map-merge'?'gps-map-merge-status':step==='bags'?'gps-source-status':step==='points'?'gps-review-status':null;if(id)$(id).textContent=s;}};
  async function api(url,body){const r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Control':'1'},body:JSON.stringify(body)}:{cache:'no-store'});if(!r.ok)throw Error(await r.text());return r.json();}
  function show(){
    showSteps();
    $('gps-project-current').textContent=current?`작업 파일: ${current.filename} · 저장 ${current.project.revision}회`:'먼저 1단계에서 맵 파일을 생성하거나 불러오세요.';
    $('gps-project-path').textContent=current?`저장 경로: ${current.workspace_path}\n컨테이너: ${current.path}`:'저장 폴더: main/decision/script/map_generator/test/review/maps/';
    const edit=$('gps-project-method').value==='edit';$('gps-project-existing').hidden=!edit;
    const existing=edit&&$('gps-project-resume').value==='existing';
    $('gps-project-name').disabled=busy||existing;
    $('gps-project-open').hidden=!existing;$('gps-project-create').hidden=existing;
    $('gps-project-create').textContent=edit?'새 파일로 이어 작업':'새 맵 파일 생성';
    const option=$('gps-project-files').selectedOptions[0],stage=Number(option?.dataset.stage||1),number=stageNumber(stage,option?.dataset.mapMerge==='true');
    $('gps-project-progress').textContent=edit?`마지막 저장: ${number}단계 ${stageNames[stage]}. ${number}단계부터 진행하면 됩니다.`:'';
    for(const id of ['gps-project-create' ,'gps-project-open','gps-project-refresh'])$(id).disabled=busy;
  }
  async function list(){try{const data=await api('/api/gps/projects'),el=$('gps-project-files'),v=el.value;el.replaceChildren(...data.files.map(f=>{const o=new Option(`${f.kind==='legacy'?'[이전 단계 파일] ':f.kind==='review'?'[이전 GPS 검토] ':''}${f.filename}`,JSON.stringify({filename:f.filename,kind:f.kind}));o.dataset.mapMerge=String(f.map_merge===true);o.dataset.stage=String(f.last_stage||(f.kind==='legacy'?(f.stage===2?5:3):f.kind==='review'?3:1));return o;}));if([...el.options].some(o=>o.value===v))el.value=v;else if(current){const option=[...el.options].find(o=>JSON.parse(o.value).filename===current.filename);if(option)el.value=option.value;}show();}catch(e){msg(e.message,true);}}
  async function save(stage,payload){if(!current)throw Error('1단계에서 맵 파일을 먼저 준비하세요.');const r=await api('/api/gps/projects/save',{...payload,filename:current.filename,revision:current.project.revision,stage,refresh_name:true});current=r;show();await list();msg(stage==='map-merge'?'MAP 병합 배치를 저장했습니다.':`${stage}단계 저장 완료`);return r;}
  async function saveCurrent(){const step=window.dashboardModes?.buildStep;if(!current)return;
    if(step==='map-merge')await window.gpsMapMerge?.save();
    if(step==='bags'||step==='points')await window.gpsEditor?.save();
    if(step==='add-points')await window.gpsAdditions?.save();
    if(step==='matching')await window.gpsMerger?.save();
    if(step==='fusion')await window.gpsFusion?.save();
    if(step==='ordering')await window.gpsOrdering?.save();
    if(step==='path')await window.gpsPath?.save();
    if(step==='lane')await window.gpsLane?.save();
    if(step==='final-points')await window.gpsFinalPoints?.save();
    if(step==='sections')await window.gpsSections?.save();
    if(step==='validation')await window.gpsReplay?.save();
  }
  async function beforeLeave(){
    if(busy)return false;
    busy=true;show();
    const status=$('map-build-mode-status');delete status.dataset.lost;status.hidden=false;status.textContent='현재 작업을 자동 저장하는 중…';
    const panels=[...document.querySelectorAll('[data-mode-panel="map-build"], [data-center-view="map-build"]')];panels.forEach(el=>el.inert=true);
    try{
      const processing=()=>[window.gpsMapMerge,window.gpsEditor,window.gpsAdditions,window.gpsMerger,window.gpsFusion,window.gpsOrdering,window.gpsPath,window.gpsLane,window.gpsExport,window.gpsSections,window.gpsReplay,window.gpsFinalPoints].some(editor=>editor?.busy);
      while(processing()){status.textContent='진행 중인 처리가 끝나면 자동 저장 후 이동합니다…';await new Promise(resolve=>setTimeout(resolve,50));}
      status.textContent='현재 단계 자동 저장 중…';
      if(current){
        if(window.dashboardModes.buildStep==='export')await window.gpsExport?.save(true);
        else await saveCurrent();
        resumeStage=lastStage();
        // Return to the first screen without rewinding or deleting saved stages.
        window.dispatchEvent(new CustomEvent('gps:projectchange'));
      }
      return true;
    }catch(error){
      resumeStage=current?lastStage():0;
      window.dispatchEvent(new CustomEvent('gps:projectchange'));
      status.dataset.lost='true';status.textContent='저장에 실패하여 저장되지 않은 작업 내용이 유실되었습니다.';return true;
    }
    finally{busy=false;panels.forEach(el=>el.inert=false);show();}
  }
  function confirmRewind(){
    const dialog=$('gps-project-rewind-dialog');dialog.returnValue='cancel';
    return new Promise(resolve=>{dialog.addEventListener('close',()=>resolve(dialog.returnValue==='continue'),{once:true});dialog.showModal();});
  }
  async function beforeStep(step){if(busy)return false;busy=true;show();document.querySelectorAll('[data-mode-panel="map-build"], [data-center-view="map-build"]').forEach(e=>e.inert=true);
    try{
      const target=step==='map-merge'?2.5:stageFor(step);
      if(step==='map-merge'&&!mapMergeEnabled())throw Error('먼저 2단계에서 MAP 병합하기를 체크하고 저장하세요.');
      if(current&&target<Math.max(resumeStage,window.dashboardModes.buildStep==='map-merge'?2.5:stageFor(window.dashboardModes.buildStep))){
        if(window.gpsFinalPoints?.busy||window.gpsMapMerge?.busy||window.gpsEditor?.busy||window.gpsAdditions?.busy||window.gpsMerger?.busy||window.gpsFusion?.busy||window.gpsOrdering?.busy||window.gpsPath?.busy||window.gpsLane?.busy||window.gpsExport?.busy||window.gpsSections?.busy||window.gpsReplay?.busy)throw Error('처리 중인 작업이 끝난 뒤 다시 이동하세요.');
        if(!await confirmRewind())return false;
        current=await api('/api/gps/projects/rewind',{filename:current.filename,revision:current.project.revision,stage:target,refresh_name:refreshName});
        resumeStage=0;window.dispatchEvent(new CustomEvent('gps:projectchange'));show();await list();msg(step==='map-merge'?'MAP 병합하기 이후의 검토 내용을 파일에서 제거했습니다.':`${target}단계 이후의 검토 내용을 파일에서 제거했습니다.`);return true;
      }
      await saveCurrent();if(step!=='project'&&!current)throw Error('먼저 1단계에서 맵 파일을 생성하거나 불러오세요.');
      if(step==='map-merge'&&!mapMergeEnabled())throw Error('먼저 2단계에서 MAP 병합하기를 체크하고 저장하세요.');
      if((step==='points'||step==='map-merge')&&!current.project.stages['2'])throw Error('먼저 2단계에서 ROS bag을 불러오세요.');
      if(step==='points'&&mapMergeEnabled()&&!current.project.map_merge_result?.raw.tracks.some(t=>t.map_merge_clip))throw Error('먼저 MAP 병합에서 사용할 구간을 복사해 배치하세요. 기준 로스백은 배경 전용입니다.');
      if((step==='add-points'||step==='matching')&&!current.project.stages['3'])throw Error('먼저 3단계 GPS 노이즈 제거를 진행하세요.');if(step==='fusion'&&!current.project.stages['5'])throw Error('먼저 5단계를 저장하세요.');if(step==='ordering'&&!current.project.stages['6'])throw Error('먼저 6단계를 저장하세요.');if(step==='path'&&!current.project.stages['7'])throw Error('먼저 7단계 순서 매칭을 저장하세요.');if(step==='lane'&&!current.project.stages['8'])throw Error('8단계 웨이포인트를 먼저 저장하세요.');if((step==='final-points'||step==='sections'||step==='validation'||step==='export')&&!current.project.stages['9'])throw Error('먼저 9단계 예상 차선 적용 결과를 저장하세요.');if(['sections','final-points','validation','export'].includes(step)){const source=await api('/api/gps/projects/lane-source?filename='+encodeURIComponent(current.filename));if(!source.saved)throw Error('직선 보간선 기준으로 9단계 차선을 다시 적용하고 저장하세요.');}resumeStage=0;return true;
    }catch(e){msg(e.message,true);return false;}finally{busy=false;document.querySelectorAll('[data-mode-panel="map-build"], [data-center-view="map-build"]').forEach(e=>e.inert=false);show();}}
  async function selectProject(copy){if(busy)return;busy=true;show();try{
      await saveCurrent();const method=$('gps-project-method').value;let source={};
      if(method==='edit'){if(!$('gps-project-files').value)throw Error('불러올 파일을 선택하세요.');source=JSON.parse($('gps-project-files').value);}
      if(!copy){if(source.kind!=='project')throw Error('이전 저장 파일은 새 이름으로 복사하여 수정을 사용하세요.');const loaded=await api('/api/gps/projects/load?filename='+encodeURIComponent(source.filename));current=await api('/api/gps/projects/resume',{filename:source.filename,revision:loaded.project.revision});refreshName=true;}
      else{let filename=$('gps-project-name').value.trim();if(!filename)throw Error('파일 이름을 입력하세요.');if(!filename.endsWith('.json'))filename+='.json';current=await api('/api/gps/projects/create',{filename,source:source.filename,kind:source.kind});refreshName=false;}
      resumeStage=method==='edit'?lastStage():0;window.dispatchEvent(new CustomEvent('gps:projectchange'));msg(resumeStage?'':'맵 파일 준비 완료. 2단계부터 진행할 수 있습니다.');show();await list();
    }catch(e){msg(e.message,true);}finally{busy=false;show();}}
  $('gps-project-create').onclick=()=>selectProject(true);$('gps-project-open').onclick=()=>selectProject(false);
  $('gps-project-method').onchange=show;
  $('gps-project-resume').onchange=show;
  $('gps-project-files').onchange=show;
  $('gps-project-refresh').onclick=list;
  async function finalize(newName){
    await saveCurrent();
    const result=await api('/api/gps/projects/export',{filename:current.filename,revision:current.project.revision,new_filename:newName});
    current=result.working;refreshName=false;show();await list();return result;
  }
  window.gpsProject={api,save,stageNumber,formatStages,get mapMergeEnabled(){return mapMergeEnabled();},beforeStep,beforeLeave,finalize,get current(){return current;},get busy(){return busy;}};
  let referenceRaw=null,referenceProjection=null,referencePoints=[];
  const referenceLayers=new WeakMap();
  function referenceEnabled(){return mapMergeEnabled()&&stageFor(window.dashboardModes?.buildStep)>=3;}
  function getReferencePoints(projectPoint=null){
    if(!referenceEnabled())return [];
    const raw=current.project.stages['2'].raw;
    if(raw!==referenceRaw||projectPoint!==referenceProjection){
      referenceRaw=raw;referenceProjection=projectPoint;referencePoints=[];
      const rad=Math.PI/180,[a,b]=raw.origin.map(v=>v*rad),e2=6.6943799901413165e-3;
      const xyz=(lat,lon)=>{lat*=rad;lon*=rad;const n=6378137/Math.sqrt(1-e2*Math.sin(lat)**2);return [n*Math.cos(lat)*Math.cos(lon),n*Math.cos(lat)*Math.sin(lon),n*(1-e2)*Math.sin(lat)];},base=xyz(...raw.origin);
      for(const track of raw.tracks)for(const p of track.points){
        if(!Number.isFinite(p.lat)||!Number.isFinite(p.lon))continue;
        if(projectPoint)referencePoints.push(projectPoint(p));
        else{const d=xyz(p.lat,p.lon).map((v,i)=>v-base[i]);referencePoints.push({e:-Math.sin(b)*d[0]+Math.cos(b)*d[1],n:-Math.sin(a)*Math.cos(b)*d[0]-Math.sin(a)*Math.sin(b)*d[1]+Math.cos(a)*d[2]});}
      }
    }
    return referencePoints;
  }
  window.gpsReferencePoints=getReferencePoints;
  const noiseStorageKey='dashboard.gpsNoiseOpacity',noiseLayers=new WeakMap();
  let noiseOpacity=18,noiseRaw=null,noiseReview=null,noiseProjection=null,noisePoints=[];
  try{const saved=localStorage.getItem(noiseStorageKey);if(saved!==null&&saved.trim()!==''&&Number.isFinite(Number(saved)))noiseOpacity=Math.max(0,Math.min(100,Number(saved)));}catch(_){}
  const noiseEnabled=()=>!!current?.project.stages['3']&&stageFor(window.dashboardModes?.buildStep)>=4;
  function getNoisePoints(projectPoint=null){
    if(!noiseEnabled())return [];
    const raw=mapMergeEnabled()?current.project.map_merge_result?.raw:current.project.stages['2']?.raw,review=current.project.stages['3'];
    if(!raw)return [];
    if(raw!==noiseRaw||review!==noiseReview||projectPoint!==noiseProjection){
      noiseRaw=raw;noiseReview=review;noiseProjection=projectPoint;noisePoints=[];
      const rad=Math.PI/180,[a,b]=raw.origin.map(v=>v*rad),e2=6.6943799901413165e-3;
      const xyz=(lat,lon)=>{lat*=rad;lon*=rad;const n=6378137/Math.sqrt(1-e2*Math.sin(lat)**2);return [n*Math.cos(lat)*Math.cos(lon),n*Math.cos(lat)*Math.sin(lon),n*(1-e2)*Math.sin(lat)];},base=xyz(...raw.origin);
      const tracks=mapMergeEnabled()?raw.tracks.filter(t=>t.map_merge_clip):raw.tracks;
      // Review results follow the input track order, including recordings with duplicate names.
      tracks.forEach((track,index)=>{
        const spec=review.tracks[index];if(!spec)return;
        const excluded=new Set(spec.excluded_seq||[]);
        for(const p of track.points){
          const outside=(spec.start_seq!=null&&p.seq<spec.start_seq)||(spec.end_seq!=null&&p.seq>spec.end_seq);
          if((!excluded.has(p.seq)&&!outside)||!Number.isFinite(p.lat)||!Number.isFinite(p.lon))continue;
          if(projectPoint)noisePoints.push(projectPoint(p));
          else{const d=xyz(p.lat,p.lon).map((v,i)=>v-base[i]);noisePoints.push({e:-Math.sin(b)*d[0]+Math.cos(b)*d[1],n:-Math.sin(a)*Math.cos(b)*d[0]-Math.sin(a)*Math.sin(b)*d[1]+Math.cos(a)*d[2]});}
        }
      });
    }
    return noisePoints;
  }
  function drawNoise(ctx,width,height,pixelsPerMeter,centerE,centerN,projectPoint){
    const points=getNoisePoints(projectPoint),canvas=ctx.canvas;
    canvas.dataset.noisePointCount=String(points.length);canvas.dataset.noiseVisiblePointCount='0';canvas.dataset.noiseAlpha=points.length?String(noiseOpacity/100):'0';
    if(!points.length||noiseOpacity===0||width<1||height<1||!(pixelsPerMeter>0))return;
    let layer=noiseLayers.get(canvas);if(!layer){layer=document.createElement('canvas');noiseLayers.set(canvas,layer);}
    if(layer.width!==canvas.width||layer.height!==canvas.height){layer.width=canvas.width;layer.height=canvas.height;}
    const paint=layer.getContext('2d');paint.setTransform(1,0,0,1,0,0);paint.clearRect(0,0,layer.width,layer.height);paint.setTransform(ctx.getTransform());paint.fillStyle='#a0a8b1';
    let visible=0;paint.beginPath();
    for(const p of points){const x=width/2+(p.e-centerE)*pixelsPerMeter,y=height/2-(p.n-centerN)*pixelsPerMeter;if(x< -3||x>width+3||y< -3||y>height+3)continue;paint.moveTo(x+3,y);paint.arc(x,y,3,0,Math.PI*2);visible++;}
    // Apply opacity once, even when hundreds of discarded fixes overlap.
    paint.fill();ctx.save();ctx.setTransform(1,0,0,1,0,0);ctx.globalAlpha=noiseOpacity/100;ctx.drawImage(layer,0,0);ctx.restore();canvas.dataset.noiseVisiblePointCount=String(visible);
  }
  function noiseControls(){
    $('gps-noise-controls').hidden=!(window.dashboardModes?.current==='map-build'&&noiseEnabled());
    $('gps-noise-opacity').value=String(noiseOpacity);$('gps-noise-opacity-value').value=`${noiseOpacity}%`;
  }
  $('gps-noise-opacity').addEventListener('input',()=>{
    noiseOpacity=Number($('gps-noise-opacity').value);noiseControls();
    try{localStorage.setItem(noiseStorageKey,String(noiseOpacity));}catch(_){}
    window.dispatchEvent(new Event('gps:backgroundchange'));
  });
  window.addEventListener('dashboard:modechange',noiseControls);
  window.addEventListener('gps:projectchange',()=>{noiseRaw=null;noiseReview=null;noisePoints=[];noiseControls();});
  noiseControls();
  window.drawGpsReference=(ctx,width,height,pixelsPerMeter,centerE,centerN,projectPoint=null)=>{
    drawNoise(ctx,width,height,pixelsPerMeter,centerE,centerN,projectPoint);
    const points=getReferencePoints(projectPoint),canvas=ctx.canvas;
    canvas.dataset.referencePointCount=String(points.length);canvas.dataset.referenceVisiblePointCount='0';canvas.dataset.referenceAlpha=points.length?'0.18':'0';
    if(!points.length||width<1||height<1||!(pixelsPerMeter>0))return;
    let layer=referenceLayers.get(canvas);if(!layer){layer=document.createElement('canvas');referenceLayers.set(canvas,layer);}
    if(layer.width!==canvas.width||layer.height!==canvas.height){layer.width=canvas.width;layer.height=canvas.height;}
    const paint=layer.getContext('2d');paint.setTransform(1,0,0,1,0,0);paint.clearRect(0,0,layer.width,layer.height);paint.setTransform(ctx.getTransform());paint.fillStyle='#627991';
    let visible=0;paint.beginPath();
    for(const p of points){const x=width/2+(p.e-centerE)*pixelsPerMeter,y=height/2-(p.n-centerN)*pixelsPerMeter;if(x< -2||x>width+2||y< -2||y>height+2)continue;paint.moveTo(x+2,y);paint.arc(x,y,2,0,Math.PI*2);visible++;}
    paint.fill();ctx.save();ctx.setTransform(1,0,0,1,0,0);ctx.globalAlpha=.18;ctx.drawImage(layer,0,0);ctx.restore();canvas.dataset.referenceVisiblePointCount=String(visible);
  };
  function referenceNote(){const el=$('gps-reference-note');if(el)el.hidden=!(window.dashboardModes?.current==='map-build'&&referenceEnabled());}
  window.addEventListener('dashboard:modechange',referenceNote);window.addEventListener('gps:projectchange',()=>{referenceRaw=null;referencePoints=[];referenceNote();});
  // World-aligned metric grid: transparent background, shared by GPS editing stages.
  window.drawGpsGrid=(ctx,width,height,pixelsPerMeter,centerE,centerN)=>{
    if(![width,height,pixelsPerMeter,centerE,centerN].every(Number.isFinite)||pixelsPerMeter<=0||width<1||height<1)return;
    const wanted=80/pixelsPerMeter,power=10**Math.floor(Math.log10(wanted)),ratio=wanted/power;
    const spacing=(ratio>=5?5:ratio>=2?2:1)*power,pixels=spacing*pixelsPerMeter;
    const left=centerE-width/(2*pixelsPerMeter),bottom=centerN-height/(2*pixelsPerMeter);
    const firstE=Math.ceil(left/spacing),firstN=Math.ceil(bottom/spacing);
    const columns=Math.ceil(width/pixels)+1,rows=Math.ceil(height/pixels)+1;
    ctx.save();ctx.globalAlpha=1;ctx.setLineDash([]);ctx.lineWidth=1;
    for(const major of [false,true]){
      ctx.strokeStyle=major?'rgba(82,107,132,.20)':'rgba(82,107,132,.10)';ctx.beginPath();
      for(let j=0;j<columns;j++){const i=firstE+j;if((i%5===0)!==major)continue;const x=width/2+(i*spacing-centerE)*pixelsPerMeter;ctx.moveTo(x,0);ctx.lineTo(x,height);}
      for(let j=0;j<rows;j++){const i=firstN+j;if((i%5===0)!==major)continue;const y=height/2-(i*spacing-centerN)*pixelsPerMeter;ctx.moveTo(0,y);ctx.lineTo(width,y);}
      ctx.stroke();
    }
    ctx.restore();ctx.canvas.dataset.gridSpacingMeters=String(spacing);ctx.canvas.dataset.gridSpacingPixels=String(pixels);
  };
  window.drawGpsScale=(ctx,width,height,pixelsPerMeter)=>{
    if(!Number.isFinite(pixelsPerMeter)||pixelsPerMeter<=0||width<100||height<100)return;
    const wanted=Math.min(120,width*.25)/pixelsPerMeter,power=10**Math.floor(Math.log10(wanted));
    const ratio=wanted/power,distance=(ratio>=5?5:ratio>=2?2:1)*power,length=distance*pixelsPerMeter;
    const value=distance>=1000?distance/1000:distance<1?distance*100:distance,unit=distance>=1000?'km':distance<1?'cm':'m';
    const label=`${Number(value.toPrecision(3))} ${unit}`,x=18,y=height-52;
    ctx.save();ctx.globalAlpha=1;ctx.setLineDash([]);ctx.font='12px system-ui';ctx.textAlign='left';ctx.textBaseline='alphabetic';
    ctx.strokeStyle='#526b84';ctx.fillStyle='#526b84';ctx.lineWidth=2;
    ctx.beginPath();ctx.moveTo(x,y-5);ctx.lineTo(x,y);ctx.lineTo(x+length,y);ctx.lineTo(x+length,y-5);ctx.stroke();
    ctx.fillText(label,x,y-11);
    const grid=Number(ctx.canvas.dataset.gridSpacingMeters);
    if(grid>0){const unit=grid>=1000?'km':grid<1?'cm':'m',value=grid>=1000?grid/1000:grid<1?grid*100:grid;ctx.font='11px system-ui';ctx.fillText(`격자 한 칸: ${Number(value.toPrecision(3))} ${unit}`,x,y-31);}
    ctx.restore();
    ctx.canvas.dataset.scaleDistanceMeters=String(distance);ctx.canvas.dataset.scaleLengthPixels=String(length);
  };
  show();list();
})();
