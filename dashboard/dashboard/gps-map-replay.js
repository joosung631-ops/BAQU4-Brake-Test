/* Recorded-time playback: raw GPS coordinates are never snapped to the map. */
(() => {
 const $=id=>document.getElementById(id);if(!$('gps-map-bag'))return;
 const inPath=()=>dashboardModes.buildStep==='path';
 const inSections=()=>['lane','sections'].includes(dashboardModes.buildStep);
 const bagSelect=()=>$(inPath()?'gps-path-bag':inSections()?'gps-section-bag':'gps-map-bag');
 const setPosition=p=>{window.gpsLane?.setCurrentPosition(p);window.gpsSections?.setCurrentPosition(p);};
 const active=()=>dashboardModes.current==='map-build'&&['path','lane','sections','validation','export'].includes(dashboardModes.buildStep);
 let data=null,version=0,loadVersion=0,playing=false,camera=true,time=0,base=0,start=0,lastFrame=-1,lastRequest=0,inflight=false,url=null,controller=null,loading=false,saving=false;
 let reviewed=new Set(),catalogBags=[],waypoint=null,pathMatched=false;
 function reviewList(){const parent=$('gps-map-reviewed-list');parent.replaceChildren();for(const id of catalogBags){const label=document.createElement('label');label.style.cssText='display:block;margin:5px 0;overflow-wrap:anywhere';const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=reviewed.has(id);checkbox.dataset.bag=id;checkbox.onchange=()=>{checkbox.checked?reviewed.add(id):reviewed.delete(id);reviewCount();status('검증 목록 변경 · 11단계 저장을 누르세요.');};label.append(checkbox,' '+id);parent.append(label);}reviewCount();}
 function reviewCount(){$('gps-map-reviewed-count').textContent=`검증 체크 ${catalogBags.filter(id=>reviewed.has(id)).length}개`;}
 const status=s=>$(inPath()?'gps-path-replay-status':inSections()?'gps-section-replay-status':'gps-map-replay-status').textContent=gpsProject.formatStages(s);
 const frameMessage=s=>{window.gpsProjection?.clear();$('gps-map-camera-message').textContent=gpsProject.formatStages(s);$('gps-map-camera-image').hidden=true;};
 function clearImage(){window.gpsProjection?.clear();if(url)URL.revokeObjectURL(url);url=null;$('gps-map-camera-image').hidden=true;$('gps-map-camera-image').removeAttribute('src');}
 function stop(){playing=false;$('gps-map-play').textContent='재생';}
 function reset(){pathMatched=false;version++;loadVersion++;loading=false;stop();status('로스백을 선택하세요.');controller?.abort();controller=null;inflight=false;data=null;time=0;lastFrame=-1;clearImage();setPosition(null);frameMessage(camera?'로스백을 선택하세요.':'카메라 꺼짐');controls();}
 function controls(){$('gps-map-reviewed-list').disabled=saving;$('gps-map-review-save').disabled=loading||saving;const ready=!!data&&(!inPath()||pathMatched);for(const id of ['gps-map-play','gps-map-time'])$(id).disabled=!ready;for(const id of ['gps-map-frame-prev','gps-map-frame-next'])$(id).disabled=!ready||!data?.frames.length;bagSelect().disabled=loading;$('gps-map-time').max=data?.duration||0;$('gps-map-time').value=time;$('gps-map-clock').textContent=`${time.toFixed(2)} / ${(data?.duration||0).toFixed(2)} s`;if(!ready)$('gps-map-position').textContent='GPS 대기';}
 // Latest sample at or before the playhead; do not invent positions between fixes.
 function indexAt(rows,t,get=x=>x){let l=0,r=rows.length;while(l<r){const m=(l+r)>>1;if(get(rows[m])<=t)l=m+1;else r=m;}return l-1;}
 function position(){const i=indexAt(data.gps,time,p=>p.t),raw=i>=0?data.gps[i]:null,p=dashboardModes.buildStep==='lane'?(window.gpsProjection?.poseAt(data,time+(gpsLane.projectionSource?.view.time_offset_s||0))||(raw?{...raw,heading_rad:null}:null)):raw;setPosition(p);$('gps-map-position').textContent=p?`GPS ${p.lat.toFixed(7)}, ${p.lon.toFixed(7)} · 기록 ${p.t.toFixed(2)} s`:'현재 시각 이전 GPS 없음';controls();}
 async function showFrame(force=false){if(!camera||!data||!active()||inflight||(inPath()&&!pathMatched))return;const fps=Math.max(1,Math.min(30,Number($('gps-map-fps').value)||10)),now=performance.now();if(!force&&now-lastRequest<1000/fps)return;
  const i=indexAt(data.frames,time);if(i<0||time-data.frames[i]>1){lastFrame=-1;frameMessage(data.frames.length?'현재 시각의 카메라 프레임 없음':'카메라 기록 없음');return;}if(i===lastFrame)return;
  lastRequest=now;inflight=true;const v=version;controller=new AbortController();
  try{const response=await fetch(`/api/gps/source/replay-frame?token=${encodeURIComponent(data.token)}&index=${i}`,{signal:controller.signal});if(!response.ok)throw Error('카메라 프레임을 읽을 수 없습니다.');const blob=await response.blob();if(v!==version||!camera)return;
   const next=URL.createObjectURL(blob),img=$('gps-map-camera-image');window.gpsProjection?.clear();img.src=next;try{await img.decode();}catch(e){URL.revokeObjectURL(next);throw e;}if(v!==version||!camera){URL.revokeObjectURL(next);return;}if(url)URL.revokeObjectURL(url);url=next;img.hidden=false;$('gps-map-camera-message').textContent='';lastFrame=i;window.gpsProjection?.setFrame({data,time:data.frames[i],width:img.naturalWidth,height:img.naturalHeight});
  }catch(e){if(v===version&&e.name!=='AbortError')frameMessage(e.message);}finally{if(v===version)inflight=false;}
 }
 function seek(t){window.gpsProjection?.clear();stop();time=Math.max(0,Math.min(data.duration,t));version++;controller?.abort();inflight=false;lastFrame=-1;position();showFrame(true);}
 // Match a recorded GPS fix spatially, then require an actual frame within 0.5s.
 function inspectWaypoint(point){
  waypoint=point;if(!inPath())return;pathMatched=false;stop();version++;controller?.abort();inflight=false;lastFrame=-1;clearImage();
  const message=text=>{status(text);frameMessage(text);controls();};
  if(!point){message('지도에서 웨이포인트를 선택하세요.');return;}
  if(loading||!data){message(loading?'로스백을 읽는 중… 선택한 웨이포인트는 읽기가 끝나면 표시합니다.':'웨이포인트를 확인할 로스백을 선택하세요.');return;}
  if(!data.frames.length){message('선택한 로스백에는 카메라 기록이 없습니다.');return;}
  const radius=Number($('gps-path-camera-radius').value);
  if(!Number.isFinite(radius)||radius<.1||radius>100){message('GPS 검색 반경을 0.1~100m로 입력하세요.');return;}
  let nearest=Infinity,best=null;
  for(const p of data.gps){const r=Math.PI/180,a=(p.lat-point.lat)*r,b=(p.lon-point.lon)*r,h=Math.sin(a/2)**2+Math.cos(p.lat*r)*Math.cos(point.lat*r)*Math.sin(b/2)**2,d=6371008.8*2*Math.asin(Math.sqrt(Math.min(1,h)));nearest=Math.min(nearest,d);if(d>radius||best&&d>=best.distance)continue;
   const before=indexAt(data.frames,p.t),candidates=[before,before+1].filter(i=>i>=0&&i<data.frames.length);let frame=-1,delta=Infinity;
   for(const i of candidates){const dt=Math.abs(data.frames[i]-p.t);if(dt<delta){delta=dt;frame=i;}}
   if(frame>=0&&delta<=.5)best={distance:d,frame,delta,gps:p};
  }
  if(!best){message(nearest<=radius?'가까운 GPS 기록은 있지만 같은 시각(±0.5초)의 카메라 프레임이 없습니다.':Number.isFinite(nearest)?`검색 반경 ${radius}m 안에 GPS 기록이 없습니다. 가장 가까운 GPS ${nearest.toFixed(2)}m`:'선택한 로스백에 GPS 기록이 없습니다.');return;}
  pathMatched=true;status(`웨이포인트 #${point.index} · GPS 거리 ${best.distance.toFixed(2)}m · 영상 시각 차이 ${best.delta.toFixed(3)}초 · ${data.bag}`);seek(data.frames[best.frame]);
 }
 async function choose(){reset();if(!bagSelect().value)return;loading=true;controls();status('GPS와 카메라 기록을 읽는 중…');const v=loadVersion;
  try{const job=await gpsProject.api('/api/gps/source/replay-prepare',{bag:bagSelect().value});if(v!==loadVersion)return;let result;
   do{await new Promise(r=>setTimeout(r,500));if(v!==loadVersion)return;result=await gpsProject.api('/api/gps/source/replay-status');if(v!==loadVersion)return;if(result.token!==job.token)throw Error('다른 재생 요청으로 변경되었습니다. 로스백을 다시 선택하세요.');}while(result.phase==='running');
   if(result.phase!=='done')throw Error(result.error||'로스백 읽기 실패');data=result;time=0;status(`${result.bag} · GPS ${result.gps.length}점 · 카메라 ${result.frames.length}프레임`);if(inPath()){loading=false;inspectWaypoint(waypoint);}else{position();showFrame(true);}
  }catch(e){if(v===loadVersion)status(e.message);}finally{if(v===loadVersion){loading=false;controls();}}
 }
 async function catalog(){const step=dashboardModes.buildStep;try{
  const result=await gpsProject.api('/api/gps/source/bags');if(!active()||dashboardModes.buildStep!==step)return;
  const selected=new Set(gpsProject.current?.project.stages['2']?.bags||[]);
  const bags=result.bags.filter(b=>b.supported&&(!inSections()||selected.has(b.id)));
  const select=bagSelect(),previous=select.value;select.replaceChildren(new Option('선택 안 함',''));
  for(const bag of bags)select.add(new Option(inPath()?`${bag.id} · ${bag.camera_count?'카메라 '+bag.camera_count+'프레임':'카메라 없음'}`:bag.id,bag.id));select.value=previous;
  if(!inSections()&&!inPath()){catalogBags=bags.map(b=>b.id);reviewList();}
  else if(!bags.length)status('2단계에서 선택한 재생 가능한 로스백이 없습니다.');
 }catch(e){if(dashboardModes.buildStep===step)status(e.message);}}
 async function save(){if(loading||saving)throw Error('로스백을 처리 중입니다.');saving=true;controls();try{const result=await gpsProject.save(11,{bag:data?.bag||null,position_s:time,validated_bags:[...reviewed]});status('11단계 저장 완료 · '+result.filename);}finally{saving=false;controls();}}
 $('gps-map-review-save').onclick=()=>save().catch(e=>status(e.message));
 window.gpsReplay={save,inspectWaypoint,get busy(){return loading||saving;}};
 $('gps-map-bag').onchange=$('gps-section-bag').onchange=$('gps-path-bag').onchange=choose;
 $('gps-path-camera-radius').oninput=()=>inspectWaypoint(waypoint);
 $('gps-map-play').onclick=()=>{if(!data||(inPath()&&!pathMatched))return;if(playing){stop();return;}if(time>=data.duration)time=0;playing=true;base=time;start=performance.now();$('gps-map-play').textContent='일시정지';};
 $('gps-map-time').oninput=e=>{if(data)seek(Number(e.target.value));};
 $('gps-map-frame-prev').onclick=()=>{if(data?.frames.length)seek(data.frames[Math.max(0,indexAt(data.frames,time-1e-6))]);};
 $('gps-map-frame-next').onclick=()=>{if(data?.frames.length)seek(data.frames[Math.min(data.frames.length-1,indexAt(data.frames,time+1e-6)+1)]);};
 $('gps-map-camera-toggle').onclick=()=>{camera=!camera;version++;controller?.abort();inflight=false;lastFrame=-1;$('gps-map-camera-toggle').textContent=camera?'ON':'OFF';$('gps-map-camera-toggle').setAttribute('aria-pressed',String(camera));clearImage();frameMessage(camera?'카메라 대기':'카메라 꺼짐');if(camera)showFrame(true);};
 $('gps-map-fps').onchange=()=>{$('gps-map-fps').value=Math.max(1,Math.min(30,Math.round(Number($('gps-map-fps').value)||10)));};
 // Frame requests are capped by FPS and only one request can be in flight.
 setInterval(()=>{if(!active()||!data)return;if(playing){time=Math.min(data.duration,base+(performance.now()-start)/1000);position();if(time>=data.duration)stop();}showFrame();},33);
 let previousStep=null;
 window.addEventListener('dashboard:modechange',()=>{const step=active()?dashboardModes.buildStep:null;if(step!==previousStep){waypoint=null;reset();$('gps-map-bag').value='';$('gps-section-bag').value='';$('gps-path-bag').value='';previousStep=step;}if(active()){reviewed=new Set(gpsProject.current?.project.stages['11']?.validated_bags||[]);reviewList();catalog();}});
 window.addEventListener('gps:projectchange',()=>{reviewed=new Set();reviewList();waypoint=null;reset();$('gps-map-bag').value='';$('gps-section-bag').value='';$('gps-path-bag').value='';});window.addEventListener('pagehide',reset);
})();
