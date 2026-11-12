/* Live raw GPS points on the dashboard background; no interpolation or clustering. */
(() => {
  const canvas = document.getElementById('gps-live-canvas');
  if (!canvas || window.dashboardBagGPS) return;
  const ctx = canvas.getContext('2d');
  const status = document.getElementById('gps-live-status');
  const coords = document.getElementById('gps-live-coordinates');
  const results = document.getElementById('bag-results-only');
  const clear = document.getElementById('gps-live-clear');
  let points = [], origin = null, session = null, seq = 0, cleared = 0;
  let selectedBag = '', loadedBag = '', fullPoints = [], fullOrigin = null, trackTimes = new Set(), current = null;
  let preparation = null, controller = null, loading = false, loadError = '', active = false;
  const fixed = () => results.checked && loadedBag === selectedBag && !!loadedBag;
  const displayed = () => fixed() ? fullPoints : points;
  let width = 1, height = 1, scale = 1, cx = 0, cy = 0, follow = true;
  let socket, timer, stopped = false, drag = null;
  const pointColor = p => p.quality == null ? '#94a3b8' : [4,5].includes(p.quality) ? '#4e83ba' : '#dc4545';
  const qualityName = p => ({0:'측위 없음',1:'SPP',2:'DGPS',4:'RTK Fixed',5:'RTK Float',6:'추정 위치'}[p.quality] || '품질 미확인');
  const xy = p => [width / 2 + (p.e - cx) * scale, height / 2 - (p.n - cy) * scale];
  function project(p) {
    const rad = Math.PI / 180, a = origin[0] * rad, b = origin[1] * rad;
    function ecef(lat, lon) {
      lat *= rad; lon *= rad;
      const e2 = 6.6943799901413165e-3, n = 6378137 / Math.sqrt(1-e2*Math.sin(lat)**2);
      return [n*Math.cos(lat)*Math.cos(lon), n*Math.cos(lat)*Math.sin(lon), n*(1-e2)*Math.sin(lat)];
    }
    const base = ecef(...origin), d = ecef(p.lat, p.lon).map((v, i) => v-base[i]);
    return {...p, e: -Math.sin(b)*d[0]+Math.cos(b)*d[1],
      n: -Math.sin(a)*Math.cos(b)*d[0]-Math.sin(a)*Math.sin(b)*d[1]+Math.cos(a)*d[2]};
  }
  function gridSpacing() {
    const wanted = Math.max(.0001, 70/scale), power = 10**Math.floor(Math.log10(wanted));
    return [1, 2, 5, 10].map(v => v*power).find(v => v >= wanted);
  }
  function drawGrid(distance) {
    const left = cx-width/(2*scale), right = cx+width/(2*scale);
    const bottom = cy-height/(2*scale), top = cy+height/(2*scale);
    ctx.save();
    function line(index, x1, y1, x2, y2) {
      ctx.strokeStyle = index === 0 ? '#c3ceda' : index % 5 === 0 ? '#d4dce5' : '#e5eaf0';
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    }
    // Anchor to the first GPS point's E/N origin, so the grid moves with the map.
    for (let i = Math.ceil(left/distance); i <= Math.floor(right/distance); i++) {
      const x = width/2+(i*distance-cx)*scale;
      line(i, x, 0, x, height);
    }
    for (let i = Math.ceil(bottom/distance); i <= Math.floor(top/distance); i++) {
      const y = height/2-(i*distance-cy)*scale;
      line(i, 0, y, width, y);
    }
    ctx.restore();
  }
  function draw() {
    const shown = displayed(), marker = fixed() ? current : points.at(-1);
    canvas.dataset.pointCount = String(shown.length);
    canvas.dataset.resultMode = String(fixed());
    canvas.dataset.currentLat = marker ? String(marker.lat) : '';
    canvas.dataset.currentLon = marker ? String(marker.lon) : '';
    ctx.clearRect(0, 0, width, height); // Transparent: use the page background directly.
    const distance = gridSpacing();
    drawGrid(distance);
    ctx.fillStyle = '#4e83ba';
    for (const p of shown) {
      ctx.fillStyle = pointColor(p);
      const [x, y] = xy(p);
      ctx.beginPath(); ctx.arc(x, y, 2.5, 0, Math.PI*2); ctx.fill();
    }
    if (marker) {
      const p = marker, [x, y] = xy(p);
      ctx.strokeStyle = '#172f50'; ctx.lineWidth = 2.5;
      ctx.beginPath(); ctx.arc(x, y, 8, 0, Math.PI*2); ctx.stroke();
      ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI*2); ctx.fill();
      ctx.fillStyle = pointColor(p); ctx.beginPath(); ctx.arc(x, y, 3.5, 0, Math.PI*2); ctx.fill();
      coords.textContent = `위도 ${p.lat.toFixed(8)} · 경도 ${p.lon.toFixed(8)} · ${qualityName(p)} | E ${p.e.toFixed(2)} m · N ${p.n.toFixed(2)} m`;
    } else coords.textContent = '/gnss/fix 수신 대기 · 첫 측정점 기준 동쪽 E / 북쪽 N';
    ctx.fillStyle = '#7c8998'; ctx.font = '11px system-ui';
    if (!shown.length) {
      ctx.textAlign = 'center'; ctx.fillText(fixed() ? '이 로스백에는 유효한 /gnss/fix GPS 기록이 없습니다.' : 'rosbag을 재생하면 GPS 측정점이 표시됩니다.', width/2, height/2); ctx.textAlign = 'left';
    }
    const length = distance*scale;
    const label = distance >= 1000 ? `${Number((distance/1000).toPrecision(3))} km` : `${Number(distance.toPrecision(3))} m`;
    ctx.strokeStyle = '#9aa7b4'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(18, height-44); ctx.lineTo(18+length, height-44);
    ctx.moveTo(18, height-48); ctx.lineTo(18, height-40);
    ctx.moveTo(18+length, height-48); ctx.lineTo(18+length, height-40); ctx.stroke();
    ctx.fillText(`격자 한 칸 ${label} · 북 ↑ / 동 →`, 18, height-52);
  }
  function fit() {
    if (displayed().length) {
      let minE=Infinity, maxE=-Infinity, minN=Infinity, maxN=-Infinity;
      for (const p of displayed()) { minE=Math.min(minE,p.e); maxE=Math.max(maxE,p.e); minN=Math.min(minN,p.n); maxN=Math.max(maxN,p.n); }
      cx=(minE+maxE)/2; cy=(minN+maxN)/2;
      scale=Math.max(.0001,Math.min(Math.max(20,width-90)/Math.max(2,maxE-minE),Math.max(20,height-150)/Math.max(2,maxN-minN)));
    }
    draw();
  }
  function resize() {
    const rect=canvas.getBoundingClientRect(), dpr=window.devicePixelRatio || 1;
    width=Math.max(1,rect.width); height=Math.max(1,rect.height);
    canvas.width=Math.round(width*dpr); canvas.height=Math.round(height*dpr);
    ctx.setTransform(dpr,0,0,dpr,0,0);
    if (follow) fit(); else draw();
  }
  document.getElementById('gps-live-fit').onclick=()=>{follow=true;fit();};
  function updateStatus() {
    status.textContent = loading ? '전체 GPS 불러오는 중…' : loadError ||
      (fixed() ? `결과만 보기 · 전체 ${fullPoints.length.toLocaleString()}점 · ${active?'현재 위치 수신 중':'GPS 대기 / 재생 일시정지'}` :
        `${active?'GPS 수신 중':'GPS 대기 / 재생 일시정지'} · ${points.length.toLocaleString()}점`);
    clear.disabled = results.checked;
    clear.title = results.checked ? '결과만 보기를 해제하면 화면을 지울 수 있습니다.' : '';
  }
  function selectBag(bag) {
    if (selectedBag === bag) return;
    selectedBag = bag; controller?.abort(); preparation = null;
    loadedBag = ''; fullPoints = []; fullOrigin = null; trackTimes = new Set(); current = null;
    loading = false; loadError = ''; updateStatus(); draw();
  }
  async function prepare(bag) {
    selectBag(bag);
    if (!results.checked || !bag || loadedBag === bag) return;
    if (preparation) return preparation;
    const abort = new AbortController(); controller = abort;
    loading = true; loadError = ''; updateStatus();
    const work = (async () => {
      try {
        let data;
        do {
          const response = await fetch('/api/bags/track?'+new URLSearchParams({bag}), {cache:'no-store', signal:abort.signal});
          data = await response.json();
          if (!response.ok || data.phase === 'error') throw new Error(data.error || '전체 GPS 불러오기 실패');
          if (data.phase === 'running') await new Promise(resolve => setTimeout(resolve, 400));
        } while (data.phase === 'running' && !abort.signal.aborted);
        if (abort.signal.aborted) return;
        if (data.phase !== 'done' || data.bag !== bag || !Array.isArray(data.points)) throw new Error('전체 GPS 응답을 확인할 수 없습니다.');
        loadedBag = bag;
        if (data.points.length) origin = fullOrigin = [data.points[0].lat, data.points[0].lon];
        fullPoints = data.points.map(project);
        trackTimes = new Set(data.points.map(p=>p.t));
        points = points.map(project);
        const latest = points.at(-1);
        current = latest && trackTimes.has(latest.t) ? latest : null;
        follow = true; fit();
      } catch (error) {
        if (abort.signal.aborted) return;
        loadError = error.message; throw error;
      } finally {
        if (controller === abort) {loading = false; preparation = null; updateStatus();}
      }
    })();
    preparation = work;
    return work;
  }
  window.dashboardBagGPS = {select:selectBag, prepare, begin:()=>{current=null;draw();}};
  results.addEventListener('change',()=>{
    if (!results.checked) {controller?.abort(); preparation=null;loading=false;loadError='';}
    if (fixed() && fullOrigin) {
      origin=fullOrigin;points=points.map(project);
      const latest=points.at(-1);current=latest&&trackTimes.has(latest.t)?latest:null;
    }
    updateStatus(); follow=true;fit();
    if (results.checked) prepare(document.getElementById('bag-select').value).catch(()=>{});
  });
  // 이전: 브라우저 points만 비웠으나 재접속 시 복원되는 문제를 방지하기 위해 서버도 지웁니다.
  document.getElementById('gps-live-clear').onclick=async()=>{
    const button=document.getElementById('gps-live-clear');button.disabled=true;
    try {
      const response=await fetch('/api/gps/clear',{method:'POST',headers:{'X-Dashboard-Control':'1'}});
      if(!response.ok)throw new Error('화면 지우기 실패');
      cleared=seq;points=[];origin=null;current=null;follow=true;
      status.textContent='화면을 지웠습니다 · 다음 측정점 대기';draw();
    } catch(error){status.textContent=error.message;}
    finally{button.disabled=false;}
  };
  canvas.addEventListener('wheel',event=>{
    event.preventDefault(); follow=false;
    const r=canvas.getBoundingClientRect(), x=event.clientX-r.left-width/2, y=event.clientY-r.top-height/2;
    const next=Math.max(.0001,Math.min(100000,scale*Math.exp(-event.deltaY*.001)));
    cx+=x/scale-x/next; cy-=y/scale-y/next; scale=next; draw();
  },{passive:false});
  canvas.addEventListener('pointerdown',event=>{follow=false;drag=[event.clientX,event.clientY];canvas.setPointerCapture(event.pointerId);});
  canvas.addEventListener('pointermove',event=>{
    if (!drag) return;
    cx-=(event.clientX-drag[0])/scale;cy+=(event.clientY-drag[1])/scale;drag=[event.clientX,event.clientY];draw();
  });
  for (const name of ['pointerup','pointercancel','lostpointercapture']) canvas.addEventListener(name,()=>{drag=null;});
  canvas.addEventListener('dblclick',()=>{follow=true;fit();});
  new ResizeObserver(resize).observe(canvas);

  window.addEventListener('dashboard:modechange',()=>{follow=true;resize();});

  function connect() {
    if (stopped) return;
    // 이전: socket=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/ws/gps`);
    // 이전: const internet = new URLSearchParams(location.search).get('internet') === '0' ? '0' : '1';
    const internet = '1';
    socket=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/ws/gps?internet=${internet}`);
    socket.onmessage=event=>{
      const data=JSON.parse(event.data);
      if (data.session!==session) {session=data.session;points=[];current=null;if(!fixed())origin=null;seq=0;cleared=0;if(!fixed())follow=true;}
      if (data.reset) points=[];
      if (!origin && data.points.length) origin=[data.points[0].lat,data.points[0].lon];
      const incoming=data.points.filter(p=>p.seq>cleared && (data.reset || p.seq>seq));
      for (const p of incoming) points.push(project(p));
      if (fixed()) {
        for (const p of incoming) if (trackTimes.has(p.t)) current=project(p);
      }
      // 이전: 10000점 초과분 자동 삭제. 이제 화면 지우기 전까지 유지합니다.
      seq=data.seq;
      active=data.active;updateStatus();
      if (incoming.length && follow && !fixed()) fit(); else draw();
    };
    socket.onclose=()=>{status.textContent='GPS 연결 재시도 중…';if(!stopped) timer=setTimeout(connect,1500);};
    socket.onerror=()=>socket.close();
  }
  window.addEventListener('pagehide',()=>{stopped=true;clearTimeout(timer);socket?.close();});
  window.addEventListener('pageshow',event=>{if(event.persisted){stopped=false;connect();}});
  connect();
})();
