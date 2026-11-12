/* Selected bag history and live /gnss/fix are independent read-only overlays. */
(() => {
  const $=id=>document.getElementById(id);if(!$('map-compare-canvas'))return;
  const active=()=>window.dashboardModes?.current==='map-compare'&&!document.hidden;
  const valid=p=>p&&Number.isFinite(p.lat)&&Number.isFinite(p.lon)&&Math.abs(p.lat)<=90&&Math.abs(p.lon)<=180;
  let gpsRequest=null,gpsTimer=null,current=null,receivedAt=null,connectionLost=false;
  let bagRequest=null,bagTimer=null,bagName='',loadedBag='',bagPoints=[],ended=false;
  function gpsStatus(){
    const fresh=Boolean(current&&!connectionLost&&receivedAt!==null&&performance.now()-receivedAt<3000);
    const label=$('map-compare-gps-status');label.dataset.active=String(fresh);
    label.textContent=!$('map-compare-current-show').checked?'현재 GPS 숨김':current?(fresh?'GPS 수신 중':connectionLost?'GPS 연결 끊김 · 마지막 위치':'GPS 수신 중단 · 마지막 위치'):'GPS 수신 대기';
    $('map-compare-gps-coordinates').textContent=current?`${current.lat.toFixed(8)}, ${current.lon.toFixed(8)}`:'—';
    const quality={0:'측위 없음',1:'SPP',2:'DGPS',4:'RTK Fixed',5:'RTK Float',6:'추정 위치'}[current?.quality]||'품질 미확인';
    $('map-compare-gps-time').textContent=current?`${new Date(current.t*1000).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})} KST · ${quality}`:'—';
    window.mapCompare.setCurrent(current,fresh);
  }
  async function pollGPS(){
    if(ended||!active()||!$('map-compare-current-show').checked)return;
    gpsRequest?.abort();const request=new AbortController();gpsRequest=request;
    const timeout=setTimeout(()=>request.abort(),3000);
    try{
      const response=await fetch('/api/gps/current',{cache:'no-store',signal:request.signal});if(!response.ok)throw Error(response.status);
      const data=await response.json();if(gpsRequest!==request||!active())return;
      if(data.point&&!valid(data.point))throw Error('GPS 좌표 오류');
      current=data.point||null;receivedAt=Number.isFinite(data.age_s)?performance.now()-data.age_s*1000:null;connectionLost=false;
    }catch(error){if(gpsRequest===request&&active())connectionLost=true;}
    finally{clearTimeout(timeout);if(gpsRequest===request){gpsRequest=null;if(active()){gpsStatus();gpsTimer=setTimeout(pollGPS,500);}}}
  }
  function stopGPS(){clearTimeout(gpsTimer);gpsRequest?.abort();gpsRequest=null;}
  function stopBag(){clearTimeout(bagTimer);bagRequest?.abort();bagRequest=null;}
  async function readBag(){
    if(ended||!active()||!bagName||!$('map-compare-bag-show').checked)return;
    if(loadedBag===bagName){window.mapCompare.setBagTrack(bagPoints);return;}
    stopBag();const name=bagName,request=new AbortController();bagRequest=request;
    $('map-compare-bag-status').textContent=`GPS 경로 읽는 중… ${name}`;
    const timeout=setTimeout(()=>request.abort(),15000);
    try{
      const response=await fetch('/api/bags/track?'+new URLSearchParams({bag:name}),{cache:'no-store',signal:request.signal});
      const data=await response.json();if(bagRequest!==request||bagName!==name||!active())return;
      if(!response.ok||data.phase==='error')throw Error(data.error||'로스백 GPS 읽기 실패');
      if(data.phase==='running'){bagTimer=setTimeout(readBag,400);return;}
      if(data.phase!=='done'||data.bag!==name||!Array.isArray(data.points)||!data.points.every(valid))throw Error('로스백 GPS 응답이 올바르지 않습니다.');
      loadedBag=name;bagPoints=data.points;window.mapCompare.setBagTrack(bagPoints);
      $('map-compare-bag-status').textContent=`${name} · GPS ${bagPoints.length.toLocaleString()}점${bagPoints.length?'':' · GPS 기록 없음'}`;
    }catch(error){if(bagRequest===request&&active())$('map-compare-bag-status').textContent=(error.name==='AbortError'?'로스백 GPS 읽기 시간 초과':error.message)+' · 목록에서 다시 선택하면 재시도합니다.';}
    finally{clearTimeout(timeout);if(bagRequest===request)bagRequest=null;}
  }
  function selectBag(name){
    if(name===bagName)return;
    stopBag();bagName=name;loadedBag='';bagPoints=[];window.mapCompare.setBagTrack([]);
    $('map-compare-bag-status').textContent=name?'선택 로스백: '+name:'아래 ros bag 재생 목록에서 선택하세요.';
    readBag();
  }
  function activate(){
    stopGPS();stopBag();
    if(active()){
      gpsStatus();pollGPS();
      const name=$('bag-select').value;
      if(name!==bagName)selectBag(name);else readBag();
    }
  }
  $('map-compare-current-show').onchange=()=>{stopGPS();gpsStatus();if(active()&&$('map-compare-current-show').checked)pollGPS();};
  $('map-compare-bag-show').onchange=()=>{stopBag();window.mapCompare.draw();if($('map-compare-bag-show').checked)readBag();};
  window.addEventListener('dashboard:bagchange',event=>{if(!active())return;if(event.detail.bag!==bagName)selectBag(event.detail.bag);});
  // A repeated selection also retries a failed or empty track request.
  $('bag-select').addEventListener('change',()=>{if(active()&&!bagRequest&&loadedBag!==bagName)readBag();});
  window.addEventListener('dashboard:modechange',activate);document.addEventListener('visibilitychange',activate);
  window.addEventListener('pagehide',()=>{ended=true;stopGPS();stopBag();});
  window.addEventListener('pageshow',()=>{ended=false;activate();});activate();
})();
