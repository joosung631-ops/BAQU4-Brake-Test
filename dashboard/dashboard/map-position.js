/* A read-only map and current fix share one WGS84 ENU origin. */
(() => {
  const canvas=document.getElementById('map-position-canvas');if(!canvas)return;
  const ctx=canvas.getContext('2d'),file=document.getElementById('map-position-file');
  const follow=document.getElementById('map-position-follow'),status=document.getElementById('map-position-map-status');
  const gpsStatus=document.getElementById('map-position-gps-status');
  let map=null,points=[],origin=null,current=null,active=false,timer=null,gpsRequest=null,mapRequest=null;
  let receivedAt=null,connectionLost=false,width=1,height=1,scale=1,cx=0,cy=0,drag=null,generation=0;
  const coordinate=p=>`${p.lat.toFixed(8)}, ${p.lon.toFixed(8)}`;
  const visible=()=>window.dashboardModes?.current==='map-position';
  const fresh=()=>current&&!connectionLost&&receivedAt!==null&&performance.now()-receivedAt<3000;
  function project(p) {
    if(!origin)return null;
    const rad=Math.PI/180,a=origin[0]*rad,b=origin[1]*rad;
    function ecef(lat,lon){lat*=rad;lon*=rad;const e2=6.6943799901413165e-3,n=6378137/Math.sqrt(1-e2*Math.sin(lat)**2);
      return [n*Math.cos(lat)*Math.cos(lon),n*Math.cos(lat)*Math.sin(lon),n*(1-e2)*Math.sin(lat)];}
    const base=ecef(...origin),delta=ecef(p.lat,p.lon).map((v,i)=>v-base[i]),[x,y,z]=delta;
    return {...p,e:-Math.sin(b)*x+Math.cos(b)*y,n:-Math.sin(a)*Math.cos(b)*x-Math.sin(a)*Math.sin(b)*y+Math.cos(a)*z};
  }
  const screen=p=>[width/2+(p.e-cx)*scale,height/2-(p.n-cy)*scale];
  function fit(includeGPS=true){
    if(!visible())return;
    let minE=Infinity,maxE=-Infinity,minN=Infinity,maxN=-Infinity;
    const add=p=>{if(!p)return;minE=Math.min(minE,p.e);maxE=Math.max(maxE,p.e);minN=Math.min(minN,p.n);maxN=Math.max(maxN,p.n);};
    points.forEach(add);if(includeGPS&&current)add(project(current));
    if(!Number.isFinite(minE)){draw();return;}
    cx=(minE+maxE)/2;cy=(minN+maxN)/2;
    scale=Math.max(.00001,Math.min((width-120)/Math.max(10,maxE-minE),(height-150)/Math.max(10,maxN-minN)));
    draw();
  }
  function marker(p,kind,label){
    const [x,y]=screen(p);ctx.save();ctx.lineWidth=3;ctx.strokeStyle='white';ctx.beginPath();
    if(kind==='start'){ctx.fillStyle='#15803d';ctx.arc(x,y,10,0,Math.PI*2);}
    else if(kind==='end'){ctx.fillStyle='#d97706';ctx.rect(x-8,y-8,16,16);}
    else{ctx.fillStyle=fresh()?'#dc2626':'#64748b';ctx.moveTo(x,y-9);ctx.lineTo(x+9,y);ctx.lineTo(x,y+9);ctx.lineTo(x-9,y);ctx.closePath();}
    ctx.fill();ctx.stroke();ctx.font='bold 12px sans-serif';ctx.lineWidth=4;
    const tx=kind==='current'?x-64:x+14,ty=kind==='start'?y-16:kind==='end'?y+25:y-14;
    ctx.strokeText(label,tx,ty);ctx.fillText(label,tx,ty);ctx.restore();
  }
  function draw(){
    if(!visible())return;
    ctx.clearRect(0,0,width,height);ctx.fillStyle='#f8fafc';ctx.fillRect(0,0,width,height);
    const step=Math.pow(10,Math.ceil(Math.log10(65/scale)));
    ctx.strokeStyle='#e2e8f0';ctx.lineWidth=1;ctx.beginPath();
    for(let e=Math.ceil((cx-width/2/scale)/step)*step;e<cx+width/2/scale;e+=step){const x=screen({e,n:0})[0];ctx.moveTo(x,0);ctx.lineTo(x,height);}
    for(let n=Math.ceil((cy-height/2/scale)/step)*step;n<cy+height/2/scale;n+=step){const y=screen({e:0,n})[1];ctx.moveTo(0,y);ctx.lineTo(width,y);}
    ctx.stroke();ctx.strokeStyle='#4e83ba';ctx.fillStyle='#4e83ba';ctx.lineWidth=1.5;ctx.beginPath();
    points.forEach((p,i)=>{const [x,y]=screen(p);if(i===0||p.break_before)ctx.moveTo(x,y);else ctx.lineTo(x,y);});ctx.stroke();
    ctx.beginPath();for(const p of points){const [x,y]=screen(p);ctx.moveTo(x+2,y);ctx.arc(x,y,2,0,2*Math.PI);}ctx.fill();
    if(points.length){marker(points[0],'start','시작');marker(points.at(-1),'end','끝');}
    const p=current?project(current):null;if(p)marker(p,'current',fresh()?'현재 GPS':'마지막 GPS');
    ctx.fillStyle='#64748b';ctx.font='12px sans-serif';ctx.fillText(`격자 ${step} m`,16,65);
    if(!points.length){ctx.textAlign='center';ctx.fillText('MAP 파일을 선택하면 GPS 포인트와 시작·끝을 표시합니다.',width/2,height/2);ctx.textAlign='left';}
  }
  function resize(){
    if(!visible())return;
    const bounds=canvas.getBoundingClientRect();if(!bounds.width||!bounds.height)return;
    width=bounds.width;height=bounds.height;const ratio=window.devicePixelRatio||1;
    canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);ctx.setTransform(ratio,0,0,ratio,0,0);
    if(follow.checked)fit();else draw();
  }
  function updateGPSStatus(){
    const live=Boolean(fresh());gpsStatus.dataset.active=String(live);
    gpsStatus.textContent=current?(live?'GPS 수신 중':connectionLost?'GPS 연결 끊김 · 마지막 위치':'GPS 수신 중단 · 마지막 위치'):'GPS 수신 대기';
    document.getElementById('map-position-coordinates').textContent=current?coordinate(current):'—';
    const quality=current?({0:'측위 없음',1:'SPP',2:'DGPS',4:'RTK Fixed',5:'RTK Float',6:'추정 위치'}[current.quality]||'품질 미확인'):'';
    document.getElementById('map-position-gps-time').textContent=current?
      `${new Date(current.t*1000).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})} KST · ${quality}`:'—';
  }
  async function poll(){
    if(!active)return;
    const request=new AbortController();gpsRequest=request;
    const timeout=setTimeout(()=>request.abort(),3000);
    try{
      const response=await fetch('/api/gps/current',{cache:'no-store',signal:request.signal});if(!response.ok)throw Error(response.status);
      const data=await response.json();if(!active)return;
      connectionLost=false;
      current=data.point||null;
      receivedAt=data.age_s===null?null:performance.now()-data.age_s*1000;
      if(current&&!origin)origin=[current.lat,current.lon];
    }catch(error){if(active)connectionLost=true;}
    finally{
      clearTimeout(timeout);
      if(gpsRequest===request)gpsRequest=null;
      if(active){updateGPSStatus();if(follow.checked)fit();else draw();timer=setTimeout(poll,500);}
    }
  }
  function clearMap(){
    map=null;points=[];origin=current?[current.lat,current.lon]:null;
    document.getElementById('map-position-start').textContent='—';document.getElementById('map-position-end').textContent='—';
    document.getElementById('map-position-title').textContent='지도 파일을 선택하세요.';
  }
  async function load(){
    const token=++generation;mapRequest?.abort();clearMap();draw();
    if(!file.value){status.textContent='지도 파일을 선택하세요.';return;}
    const request=new AbortController();mapRequest=request;status.textContent='지도 불러오는 중…';
    try{
      const response=await fetch('/api/map-position/maps/'+encodeURIComponent(file.value),{cache:'no-store',signal:request.signal});
      if(!response.ok)throw Error(await response.text());const data=await response.json();if(token!==generation)return;
      map=data;origin=[data.points[0].lat,data.points[0].lon];points=data.points.map(project);
      document.getElementById('map-position-title').textContent=data.filename;
      document.getElementById('map-position-start').textContent=coordinate(data.start);
      document.getElementById('map-position-end').textContent=coordinate(data.end);
      status.textContent=`${data.point_count.toLocaleString()}점 · ${data.source}${data.ordered?'':' · 시작·끝은 파일 순서 기준'}`;
      fit(true);
    }catch(error){if(token===generation&&error.name!=='AbortError'){status.textContent=error.message;clearMap();draw();}}
  }
  async function refresh(){
    const previous=file.value,button=document.getElementById('map-position-refresh');button.disabled=true;
    try{
      const response=await fetch('/api/map-position/maps',{cache:'no-store'});if(!response.ok)throw Error(await response.text());
      const data=await response.json();file.replaceChildren(new Option('< MAP 선택 >',''),...data.maps.map(name=>new Option(name,name)));
      file.value=data.maps.includes(previous)?previous:'';
      if(previous&&!file.value)load();
      if(!data.maps.length)status.textContent='선택할 지도 파일이 없습니다.';
    }catch(error){status.textContent='파일 목록 오류: '+error.message;}
    finally{button.disabled=false;}
  }
  function activate(){
    const next=visible();if(next===active){if(next)resize();return;}
    active=next;clearTimeout(timer);
    if(active){document.querySelector('.status-panels').scrollTop=0;resize();refresh().then(()=>{if(file.value&&!map)load();});poll();}
    else{gpsRequest?.abort();mapRequest?.abort();}
  }
  file.onchange=load;document.getElementById('map-position-refresh').onclick=refresh;
  document.getElementById('map-position-fit').onclick=()=>{follow.checked=false;fit(false);};
  document.getElementById('map-position-center').onclick=()=>{const p=current?project(current):null;if(!p)return;follow.checked=false;cx=p.e;cy=p.n;draw();};
  follow.onchange=()=>{if(follow.checked)fit(true);};
  canvas.addEventListener('wheel',event=>{event.preventDefault();follow.checked=false;
    const r=canvas.getBoundingClientRect(),x=event.clientX-r.left-width/2,y=event.clientY-r.top-height/2;
    const next=Math.max(.00001,Math.min(100000,scale*Math.exp(-event.deltaY*.001)));
    cx+=x/scale-x/next;cy-=y/scale-y/next;scale=next;draw();},{passive:false});
  canvas.addEventListener('pointerdown',event=>{follow.checked=false;drag=[event.clientX,event.clientY];canvas.setPointerCapture(event.pointerId);});
  canvas.addEventListener('pointermove',event=>{if(!drag)return;cx-=(event.clientX-drag[0])/scale;cy+=(event.clientY-drag[1])/scale;drag=[event.clientX,event.clientY];draw();});
  for(const name of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(name,()=>{drag=null;});
  canvas.addEventListener('dblclick',()=>{follow.checked=true;fit(true);});
  new ResizeObserver(resize).observe(canvas);
  window.addEventListener('dashboard:modechange',activate);
  window.addEventListener('pagehide',()=>{active=false;clearTimeout(timer);gpsRequest?.abort();mapRequest?.abort();});
  window.addEventListener('pageshow',activate);
  activate();
})();
