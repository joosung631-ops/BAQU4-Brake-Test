(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const canvas = el('map'), ctx = canvas.getContext('2d');
  let state = {}, path = null, trail = [], session = '', revision = '', sequence = 0;
  let width = 1, height = 1, cx = 0, cy = 0, scale = 1, view = 'fit', drag = null;
  let stopped = false, timer = null, receivedAt = performance.now(), transportFailed = false, requestAge = 0;
  const xy = p => [width / 2 + (p[0] - cx) * scale, height / 2 - (p[1] - cy) * scale];
  const number = (v, digits = 2) => Number.isFinite(v) ? v.toFixed(digits) : '—';
  const elapsed = () => Math.max(0, (performance.now() - receivedAt) / 1000);
  const serverAge = () => (Number.isFinite(state.server_age_s) ? state.server_age_s : 0) + requestAge + elapsed();
  const active = () => !!state.active && !transportFailed && serverAge() < 1;
  const age = value => value ? Math.max(0, value.source_age_s || 0) +
    Math.max(0, value.received_age_s || 0) + serverAge() : Infinity;
  const fresh = value => active() && value?.fresh && age(value) <= .5;
  const same = value => value && path && path.source !== 'preview' && value.frame === path.frame;
  const finiteXY = value => Number.isFinite(value?.x) && Number.isFinite(value?.y);
  const livePose = () => fresh(state.pose) && state.pose.position_valid && same(state.pose) && finiteXY(state.pose);
  const lastPose = () => same(state.last_good_pose) && finiteXY(state.last_good_pose) ? state.last_good_pose : null;
  const lastAge = () => state.last_good_pose ? Math.max(0, state.last_good_pose.age_s || 0) + serverAge() : Infinity;
  const ageText = seconds => seconds < 60 ? `${number(seconds, 1)}초 전` : `${Math.floor(seconds / 60)}분 ${Math.floor(seconds % 60)}초 전`;
  const reasons = {
    GNSS_ANTENNA_OBSERVATION_UNAVAILABLE: 'GNSS 안테나 위치 관측 없음',
    GNSS_UNAVAILABLE: 'GNSS 위치 입력 없음', INVALID_OR_STALE_GNSS_POSITION: 'GNSS 위치 무효 또는 입력 만료',
    INVALID_OR_STALE_GNSS_POSE: 'GNSS 위치·방향 무효 또는 입력 만료',
    YAW_NOT_INITIALIZED: '위치 수신 중 · 방향 초기화 대기', AUTO_PAUSED: '일시정지',
    HEADING_BOOTSTRAP_ACTIVE: '출발 방향 확보 중', PURE_PURSUIT_COMPUTE_FAILED: '경로 추종 목표점 계산 실패',
    PATH_DEVIATION_EXCEEDED: '경로 허용 거리 초과', INVALID_OR_STALE_STATE_OR_PLAN: '위치 또는 주행 계획 무효',
    GOAL_REACHED: '경로 주행 완료', PURE_PURSUIT_ACTIVE: '경로 추종 중'
  };
  const describe = reason => reasons[reason] || reason || '입력 수신 대기';

  function markerPose() { return livePose() ? state.pose : lastPose(); }
  function fit() {
    const points = [...(path?.points || [])];
    if (path?.source !== 'preview' && (same(state.pose) || same(state.last_good_pose))) {
      points.push(...trail.map(p => [p.x, p.y]));
      const pose = markerPose();
      if (pose) points.push([pose.x, pose.y]);
    }
    if (!points.length) return;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const [x, y] of points) {
      minX = Math.min(minX, x); maxX = Math.max(maxX, x);
      minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }
    // Reserve the status banner above and view controls below the geometry.
    const top = width < 800 ? 125 : 115, bottom = 105;
    scale = Math.max(.001, Math.min(Math.max(20, width - 160) / Math.max(8, maxX - minX),
      Math.max(20, height - top - bottom) / Math.max(8, maxY - minY)));
    cx = (minX + maxX) / 2;
    cy = (minY + maxY) / 2 - (top - bottom) / (2 * scale);
  }
  function updateView() {
    if (view === 'fit') fit();
    if (view === 'follow') {
      const pose = markerPose();
      if (pose) { cx = pose.x; cy = pose.y; }
    }
    el('fit').setAttribute('aria-pressed', String(view === 'fit'));
    el('follow').setAttribute('aria-pressed', String(view === 'follow'));
  }
  function line(points, color, lineWidth) {
    if (!points.length) return;
    ctx.beginPath();
    points.forEach((p, i) => { const [x, y] = xy(p); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.strokeStyle = color; ctx.lineWidth = lineWidth; ctx.lineJoin = ctx.lineCap = 'round'; ctx.stroke();
  }
  function pill(text, x, y, color, background = '#ffffffef') {
    ctx.font = '600 12px system-ui';
    const size = ctx.measureText(text).width + 18;
    x = Math.max(6, Math.min(width - size - 6, x));
    y = Math.max(6, Math.min(height - 28, y));
    ctx.fillStyle = background; ctx.fillRect(x, y, size, 24);
    ctx.fillStyle = color; ctx.fillText(text, x + 9, y + 16);
  }
  function grid() {
    const wanted = 65 / scale, power = 10 ** Math.floor(Math.log10(Math.max(.001, wanted)));
    const spacing = [1, 2, 5, 10].map(v => v * power).find(v => v >= wanted);
    ctx.strokeStyle = '#e6edf3'; ctx.lineWidth = 1;
    ctx.beginPath();
    const left = cx - width / (2 * scale), right = cx + width / (2 * scale);
    const bottom = cy - height / (2 * scale), top = cy + height / (2 * scale);
    for (let x = Math.ceil(left / spacing) * spacing; x <= right; x += spacing) {
      const px = xy([x, 0])[0]; ctx.moveTo(px, 0); ctx.lineTo(px, height);
    }
    for (let y = Math.ceil(bottom / spacing) * spacing; y <= top; y += spacing) {
      const py = xy([0, y])[1]; ctx.moveTo(0, py); ctx.lineTo(width, py);
    }
    ctx.stroke();
    ctx.fillStyle = '#627d90'; ctx.font = '11px system-ui';
    ctx.fillText(`격자 ${number(spacing, spacing < 1 ? 2 : 0)} m`, width - 110, height - 20);
  }
  function drawRoute() {
    const points = path?.points || [];
    line(points, '#ffffff', 7); line(points, '#889aa9', 3);
    if (points.length < 2) return;
    // Small direction arrows follow the route, not a chord joining its ends.
    const step = Math.max(1, Math.floor(points.length / 6));
    for (let i = step; i < points.length - 1; i += step) {
      const a = xy(points[i]), b = xy(points[Math.min(points.length - 1, i + 1)]);
      const angle = Math.atan2(b[1] - a[1], b[0] - a[0]);
      ctx.strokeStyle = '#758b9e'; ctx.lineWidth = 2; ctx.beginPath();
      ctx.moveTo(a[0] - 7 * Math.cos(angle - .5), a[1] - 7 * Math.sin(angle - .5));
      ctx.lineTo(...a); ctx.lineTo(a[0] - 7 * Math.cos(angle + .5), a[1] - 7 * Math.sin(angle + .5)); ctx.stroke();
    }
    points.filter((_, i) => i === 0 || i === points.length - 1).forEach((p, index) => {
      const [x, y] = xy(p); ctx.fillStyle = '#fff'; ctx.strokeStyle = '#5d768c'; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(x, y, 6, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
      pill(index ? '맵 끝점' : '맵 시작점', x + 10, y + (index ? 7 : -32), '#526b80');
    });
  }
  function drawVehicle() {
    const live = livePose(), pose = live ? state.pose : lastPose();
    canvas.dataset.vehicleState = live ? 'live' : pose ? 'last-known' : 'none';
    if (!pose) return;
    const [x, y] = xy([pose.x, pose.y]);
    ctx.save(); ctx.strokeStyle = live ? '#176bb4' : '#8a99a5'; ctx.lineWidth = 2;
    ctx.fillStyle = live ? '#176bb420' : '#8a99a51a'; ctx.setLineDash(live ? [] : [4, 4]);
    ctx.beginPath(); ctx.arc(x, y, 19, 0, 2 * Math.PI); ctx.fill(); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = live ? '#176bb4' : '#8a99a5'; ctx.strokeStyle = '#fff'; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.arc(x, y, 9, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
    if (live && pose.valid && Number.isFinite(pose.yaw)) {
      const angle = -pose.yaw; ctx.fillStyle = '#176bb4'; ctx.beginPath();
      ctx.moveTo(x + 31 * Math.cos(angle), y + 31 * Math.sin(angle));
      ctx.lineTo(x + 17 * Math.cos(angle) + 6 * Math.sin(angle), y + 17 * Math.sin(angle) - 6 * Math.cos(angle));
      ctx.lineTo(x + 17 * Math.cos(angle) - 6 * Math.sin(angle), y + 17 * Math.sin(angle) + 6 * Math.cos(angle)); ctx.closePath(); ctx.fill();
    }
    pill(live ? '현재 차량' : `마지막 정상 위치 · ${ageText(lastAge())}`, x + 25, y - 42,
      live ? '#155f9e' : '#657987'); ctx.restore();
  }
  function updateStatus(targetValid) {
    const pose = state.pose, history = lastPose(), connected = active();
    let title, detail, level = 'waiting';
    if (!connected) {
      title = state.session ? '모니터 연결 끊김' : '모니터 연결 대기';
      detail = history ? `마지막 정상 위치는 ${ageText(lastAge())}입니다. 현재 위치로 사용하지 마세요.` : '차량 위치가 아직 확인되지 않았습니다. 예정 경로는 계속 표시합니다.';
      level = state.session ? 'error' : 'waiting';
    } else if (path?.source === 'preview') {
      title = '지도 미리보기 · 차량 좌표 기준 대기';
      detail = '예정 경로를 먼저 표시합니다. GNSS 좌표 기준이 준비되면 차량 위치를 겹쳐 표시합니다.';
    } else if (pose && !pose.position_valid) {
      title = describe(pose.reason) === pose.reason ? '현재 위치 무효' : describe(pose.reason);
      detail = history ? `마지막 정상 위치를 표시합니다 · ${ageText(lastAge())}` : '현재 차량 위치는 표시하지 않습니다. 예정 경로는 확인할 수 있습니다.';
      level = 'error';
    } else if (pose && path && !same(pose)) {
      title = '위치 좌표 기준 불일치'; detail = '차량과 경로의 좌표 기준이 달라 위치를 겹쳐 표시하지 않습니다.'; level = 'error';
    } else if (pose && !fresh(pose)) {
      title = '현재 위치 수신 중단'; detail = history ? `마지막 정상 위치 · ${ageText(lastAge())}` : '새 GNSS 위치 입력을 기다리고 있습니다.'; level = 'error';
    } else if (livePose()) {
      title = '현재 차량 위치 표시 중'; level = 'ok';
      detail = `파란 마커가 현재 차량입니다 · ${ageText(age(pose))}${pose.valid ? ' · 화살표는 차량 방향' : ' · 방향 초기화 대기'}`;
    } else {
      title = '현재 위치 수신 대기'; detail = path?.points?.length ? '회색선은 예정 경로입니다. 정상 위치가 들어오면 파란 차량 마커를 표시합니다.' : '선택한 주행 지도와 정상 위치 입력을 기다리고 있습니다.';
    }
    el('status').textContent = title; el('status-detail').textContent = detail; el('status-box').dataset.level = level;
    el('connection').textContent = connected ? '연결됨' : state.session ? '끊김' : '대기';
    el('position-state').textContent = livePose() ? '표시 중' : history ? '마지막 정상 위치' : '확인되지 않음';
    el('pose-age').textContent = livePose() ? `현재 위치 갱신 · ${ageText(age(pose))}` : history ? `마지막 정상 위치 · ${ageText(lastAge())}` : '정상 위치 수신 이력 없음';
    const control = state.control;
    el('control-state').textContent = fresh(control) ? control.paused ? '일시정지' : control.fsm_state === 2 ? '주행 제어 중' : describe(control.reason) : '수신 대기';
    el('target-state').textContent = targetValid ? '표시 중' : describe(state.diagnostic?.reason);
    el('follow').disabled = !markerPose();
    el('empty-map').hidden = !!path?.points?.length;
    el('map-name').textContent = path?.name || (path?.points?.length ? '수신된 주행 경로' : '선택 지도 대기');
    el('frame').textContent = `${path?.source === 'preview' ? '위치 수신 전 지도 미리보기' : '후륜축 기준 위치'} · 북 ↑ / 동 → · 단위 m`;
    const reference = state.reference;
    el('reason').textContent = `위치: ${pose?.reason || '수신 대기'}\nPP: ${state.diagnostic?.reason || '수신 대기'}\n주행 경로: ${reference ? reference.count + '점' : '수신 대기'}`;
  }
  function draw() {
    updateView(); ctx.clearRect(0, 0, width, height); grid(); drawRoute();
    const compatibleTrail = path?.source !== 'preview' && (same(state.pose) || same(state.last_good_pose));
    if (compatibleTrail) line(trail.map(p => [p.x, p.y]), '#176bb4', 3);
    canvas.dataset.trailVisible = String(!!compatibleTrail && trail.length > 0);
    const diag = state.diagnostic;
    const valid = livePose() && fresh(diag) && diag.valid && same(diag) && Array.isArray(diag.target) && diag.target.every(Number.isFinite);
    canvas.dataset.targetVisible = String(!!valid); canvas.dataset.routePoints = String(path?.points?.length || 0);
    if (valid) {
      line([[state.pose.x, state.pose.y], diag.target], '#72b9a0', 1.5);
      const [x, y] = xy(diag.target); ctx.fillStyle = '#23916b'; ctx.beginPath(); ctx.arc(x, y, 6, 0, 2 * Math.PI); ctx.fill();
    }
    drawVehicle(); updateStatus(valid);
    el('speed').textContent = fresh(state.motion) && state.motion.valid ? number(state.motion.speed * 3.6) + ' km/h' : '—';
    el('lateral').textContent = valid ? number(diag.lateral, 3) + ' m' : '—';
    el('heading').textContent = valid ? number(diag.heading * 180 / Math.PI) + '°' : '—';
    el('lookahead').textContent = valid ? number(diag.lookahead) + ' m' : '—';
    el('steering').textContent = valid ? number(diag.steering * 180 / Math.PI) + '°' : '—';
    el('command').textContent = fresh(state.command) && state.command.valid ? number(state.command.steering * 180 / Math.PI) + '°' : '—';
  }
  function resize() {
    const rect = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    width = Math.max(1, rect.width); height = Math.max(1, rect.height);
    canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0); draw();
  }
  el('fit').onclick = () => { view = 'fit'; draw(); };
  el('follow').onclick = () => { view = 'follow'; scale = Math.max(1, Math.min(width, height) / 55); draw(); };
  canvas.addEventListener('wheel', event => {
    event.preventDefault(); view = 'free'; scale = Math.max(.001, Math.min(10000, scale * Math.exp(-event.deltaY * .001))); draw();
  }, {passive: false});
  canvas.onpointerdown = event => { view = 'free'; drag = [event.clientX, event.clientY]; canvas.setPointerCapture(event.pointerId); };
  canvas.onpointermove = event => {
    if (!drag) return;
    cx -= (event.clientX - drag[0]) / scale; cy += (event.clientY - drag[1]) / scale;
    drag = [event.clientX, event.clientY]; draw();
  };
  for (const event of ['pointerup', 'pointercancel', 'lostpointercapture']) canvas.addEventListener(event, () => { drag = null; });
  async function poll() {
    if (stopped) return;
    try {
      const query = new URLSearchParams({session, revision, after: String(sequence)});
      const requestedAt = performance.now();
      const response = await fetch('/api/monitor-1021?' + query, {cache: 'no-store', signal: AbortSignal.timeout(3000)});
      if (!response.ok) throw new Error('모니터 수신 실패');
      const data = await response.json();
      if (data.reset || data.session !== session) { trail = []; sequence = 0; }
      const changed = revision !== data.revision;
      session = data.session; revision = data.revision;
      if ('path' in data) path = data.path;
      for (const point of data.trail || []) {
        if (point.seq > sequence) { trail.push(point); sequence = point.seq; }
      }
      if (trail.length > 10000) trail = trail.slice(-10000);
      if (changed && view !== 'follow') view = 'fit';
      state = data; receivedAt = performance.now(); requestAge = (receivedAt - requestedAt) / 1000;
      transportFailed = false; draw();
    } catch (_) { transportFailed = true; draw(); }
    if (!stopped) timer = setTimeout(poll, 200);
  }
  new ResizeObserver(resize).observe(canvas);
  const clock = setInterval(() => { if (!stopped) draw(); }, 200);
  window.addEventListener('pagehide', () => { stopped = true; clearTimeout(timer); });
  window.addEventListener('pageshow', event => { if (event.persisted) { stopped = false; resize(); poll(); } });
  window.addEventListener('beforeunload', () => clearInterval(clock));
  poll();
})();
