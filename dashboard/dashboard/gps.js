(() => {
  const canvas = document.getElementById('gps-canvas'), ctx = canvas.getContext('2d');
  const message = document.getElementById('gps-message'), list = document.getElementById('gps-bags');
  const live = {id:'재생 중 GPS', color:'#2563eb', points:[]};
  let origin, session, clearedSeq = 0, latestSeq = 0, socket, stopped = false;
  const follow = document.getElementById('gps-follow');
  let bags = [live], selected = new Set([live.id]), scale = 1, cx = 0, cy = 0, width = 1, height = 1, drag;
  const visible = () => bags.filter(b => selected.has(b.id));
  const xy = p => [width/2 + (p.e-cx)*scale, height/2 - (p.n-cy)*scale];
  function fit() {
    if (canvas.offsetParent === null) return;
    const points = visible().flatMap(b => b.points);
    if (!points.length) { draw(); return; }
    const es = points.map(p => p.e), ns = points.map(p => p.n);
    const minE = Math.min(...es), maxE = Math.max(...es), minN = Math.min(...ns), maxN = Math.max(...ns);
    cx = (minE+maxE)/2; cy = (minN+maxN)/2;
    scale = Math.max(.001, Math.min((width-80)/Math.max(20,maxE-minE), (height-80)/Math.max(20,maxN-minN)));
    draw();
  }
  function draw() {
    if (canvas.offsetParent === null) return;
    ctx.clearRect(0,0,width,height);
    ctx.fillStyle = '#f8fafc'; ctx.fillRect(0,0,width,height);
    const step = Math.pow(10, Math.ceil(Math.log10(65/scale)));
    ctx.strokeStyle = '#e2e8f0'; ctx.lineWidth = 1;
    ctx.beginPath();
    for (let e = Math.ceil((cx-width/2/scale)/step)*step; e < cx+width/2/scale; e += step) {
      const x = xy({e,n:0})[0]; ctx.moveTo(x,0); ctx.lineTo(x,height);
    }
    for (let n = Math.ceil((cy-height/2/scale)/step)*step; n < cy+height/2/scale; n += step) {
      const y = xy({e:0,n})[1]; ctx.moveTo(0,y); ctx.lineTo(width,y);
    }
    ctx.stroke();
    for (const bag of visible()) {
      ctx.strokeStyle = bag.color; ctx.fillStyle = bag.color; ctx.lineWidth = 2;
      ctx.beginPath(); let previous;
      for (const p of bag.points) {
        const [x,y] = xy(p);
        if (!previous || p.break || p.t-previous.t > 3 || p.t <= previous.t) ctx.moveTo(x,y); else ctx.lineTo(x,y);
        previous = p;
      }
      ctx.stroke();
      for (const p of bag.points) { const [x,y] = xy(p); ctx.beginPath(); ctx.arc(x,y,2,0,2*Math.PI); ctx.fill(); }
      if (bag.points.length) {
        const first = xy(bag.points[0]), last = xy(bag.points.at(-1));
        ctx.beginPath(); ctx.arc(...first,5,0,2*Math.PI); ctx.fill();
        ctx.fillRect(last[0]-4,last[1]-4,8,8);
      }
    }
    ctx.fillStyle = '#475569'; ctx.font = '12px sans-serif';
    ctx.fillText(`격자 ${step} m · 북 ↑ / 동 →`,12,22);
    ctx.fillText('● 시작  ■ 현재 위치 · 드래그 이동 / 휠 확대',12,height-14);
    if (!visible().some(b => b.points.length)) ctx.fillText('09-20 rosbag의 GPS 수신을 기다립니다.',20,height/2);
  }
  function resize() {
    if (canvas.offsetParent === null) return;
    const bounds = canvas.getBoundingClientRect(), ratio = window.devicePixelRatio || 1;
    width = bounds.width; height = bounds.height;
    canvas.width = Math.round(width*ratio); canvas.height = Math.round(height*ratio);
    ctx.setTransform(ratio,0,0,ratio,0,0); draw();
  }
  canvas.addEventListener('wheel', event => {
    event.preventDefault(); follow.checked = false;
    const r = canvas.getBoundingClientRect(), x = event.clientX-r.left-width/2, y = event.clientY-r.top-height/2;
    const next = Math.max(.001, Math.min(10000, scale*Math.exp(-event.deltaY*.001)));
    cx += x/scale-x/next; cy -= y/scale-y/next; scale = next; draw();
  }, {passive:false});
  canvas.addEventListener('pointerdown', event => { follow.checked = false; drag = [event.clientX,event.clientY]; canvas.setPointerCapture(event.pointerId); });
  canvas.addEventListener('pointermove', event => {
    if (drag) { cx -= (event.clientX-drag[0])/scale; cy += (event.clientY-drag[1])/scale; drag = [event.clientX,event.clientY]; draw(); return; }
    const r = canvas.getBoundingClientRect(), x = event.clientX-r.left, y = event.clientY-r.top;
    let nearest, distance = 100;
    for (const bag of visible()) for (const p of bag.points) {
      const [px,py] = xy(p), d = (x-px)**2+(y-py)**2;
      if (d < distance) { nearest = {bag,p}; distance = d; }
    }
    if (nearest) {
      const {bag,p} = nearest;
      const quality = {0:'GPS Fix',1:'SBAS Fix',2:'GBAS Fix'}[p.status] || '상태 미확인';
      message.textContent = `${bag.id} · ${new Date(p.t*1000).toLocaleTimeString('ko-KR',{timeZone:'Asia/Seoul'})} KST · ${p.lat.toFixed(7)}, ${p.lon.toFixed(7)} · ${quality}`;
    }
  });
  canvas.addEventListener('pointerup', () => { drag = null; });
  canvas.addEventListener('pointercancel', () => { drag = null; });
  document.getElementById('gps-fit').onclick = fit;
  document.getElementById('gps-clear').onclick = () => {
    clearedSeq = latestSeq; live.points = []; draw();
    message.textContent = '화면 경로를 지웠습니다. 이후 수신되는 위치부터 표시합니다.';
  };
  follow.onchange = () => { if (follow.checked) fit(); };
  new ResizeObserver(resize).observe(canvas);
  function project(p) {
    const rad = Math.PI/180, a = origin[0]*rad, b = origin[1]*rad, h = origin[2] || 0;
    function ecef(lat,lon) {
      lat *= rad; lon *= rad;
      const e2 = 6.6943799901413165e-3, n = 6378137/Math.sqrt(1-e2*Math.sin(lat)**2);
      return [(n+h)*Math.cos(lat)*Math.cos(lon),(n+h)*Math.cos(lat)*Math.sin(lon),(n*(1-e2)+h)*Math.sin(lat)];
    }
    const base = ecef(origin[0],origin[1]), delta = ecef(p.lat,p.lon).map((v,i)=>v-base[i]);
    const [x,y,z] = delta;
    return {...p,e:-Math.sin(b)*x+Math.cos(b)*y,n:-Math.sin(a)*Math.cos(b)*x-Math.sin(a)*Math.sin(b)*y+Math.cos(a)*z};
  }
  function connect() {
    if (stopped) return;
    socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws/gps`);
    socket.onmessage = event => {
      const data = JSON.parse(event.data);
      if (data.session !== session) {
        session = data.session; clearedSeq = 0; latestSeq = 0; live.points = [];
      }
      if (data.reset) live.points = [];
      origin = data.origin || origin;
      if (!origin && data.points.length) origin = [data.points[0].lat,data.points[0].lon,0];
      const incoming = data.points.filter(p=>p.seq > clearedSeq && (data.reset || p.seq > latestSeq));
      live.points.push(...incoming.map(project));
      if (live.points.length > 10000) live.points.splice(0,live.points.length-10000);
      latestSeq = data.seq;
      document.getElementById('gps-origin').textContent = origin ? `공통 원점 ${origin[0].toFixed(7)}, ${origin[1].toFixed(7)} · ENU 평면도` : '공통 원점 대기 중';
      list.textContent = `${data.active ? 'GPS 수신 중' : 'GPS 대기 / 재생 일시정지 또는 수신 중단'} · 표시 ${live.points.length}점`;
      if (incoming.length && follow.checked) fit(); else draw();
    };
    socket.onclose = () => { list.textContent = '지도 연결 끊김 · 다시 연결 중…'; if (!stopped) setTimeout(connect,1500); };
    socket.onerror = () => socket.close();
  }
  window.addEventListener('pagehide',()=>{ stopped = true; if (socket) socket.close(); });
  window.addEventListener('pageshow',event=>{ if (event.persisted) { stopped=false; connect(); } });
  message.textContent = '09-20 rosbag을 재생하면 위치와 경로가 추가됩니다. 점 위에서 좌표·시각을 확인하세요.';
  connect();
})();
