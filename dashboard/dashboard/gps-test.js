/* Per-recording GPS review, smooth curve previews and explicit local saving. */
(() => {
  const get=id=>document.getElementById(id), canvas=get('gps-test-canvas');
  if (!canvas) return;
  const ctx=canvas.getContext('2d'), status=get('gps-test-status'), info=get('gps-test-info');
  const palette=['#1769c2','#d45a16','#168052','#8b43ad','#ac3970','#65710c'];
  let tracks=[], width=1,height=1,scale=1,cx=0,cy=0,follow=true,selection=null,drag=null,loading=false,loaded=false;
  const selected=new Map(), selectionKey=hit=>`${hit.track}:${hit.index}`;
  let datasetId=null, revision=0, dirty=false, saving=false,editVersion=0,history=[];
  let sourceEntries=[],sourceSelection=new Set(),sourceReady=false,sourceBusy=false,sourceTimer=null;
  const reviewStatus=get('gps-review-status');
  let sourceRaw=null,useSaved=false,loadedBags=[],loadStep=null,mapMergeDirty=false;
  const active=()=>window.dashboardModes?.current==='map-build'&&['bags','points'].includes(window.dashboardModes?.buildStep);
  const xy=p=>[width/2+(p.e-cx)*scale,height/2-(p.n-cy)*scale];
  function project(data) {
    const rad=Math.PI/180, [a,b]=data.origin.map(v=>v*rad);
    const ecef=(lat,lon)=>{
      lat*=rad;lon*=rad;
      const e2=6.6943799901413165e-3,n=6378137/Math.sqrt(1-e2*Math.sin(lat)**2);
      return [n*Math.cos(lat)*Math.cos(lon),n*Math.cos(lat)*Math.sin(lon),n*(1-e2)*Math.sin(lat)];
    };
    const base=ecef(...data.origin);
    return data.tracks.map((t,i)=>({...t,color:palette[i%palette.length],visible:true,limit:t.points.length-1,
      points:t.points.map(p=>{
        const d=ecef(p.lat,p.lon).map((v,j)=>v-base[j]);
        return {...p,e:-Math.sin(b)*d[0]+Math.cos(b)*d[1],
          n:-Math.sin(a)*Math.cos(b)*d[0]-Math.sin(a)*Math.sin(b)*d[1]+Math.cos(a)*d[2]};
      })}));
  }
  const outsideRange=(t,seq)=>(t.startSeq!==null&&seq<t.startSeq)||(t.endSeq!==null&&seq>t.endSeq);
  const isExcluded=(t,seq)=>t.excluded.has(seq)||outsideRange(t,seq);
  function draw() {
    if(!active())return;
    ctx.clearRect(0,0,width,height);window.drawGpsGrid(ctx,width,height,scale,cx,cy);window.drawGpsReference(ctx,width,height,scale,cx,cy);
    const nearest=updateDistance();
    const labels=[];let pointCount=0,segments=0,curveCount=0;
    for (const [ti,t] of tracks.entries()) {
      if(!t.visible || !t.points.length)continue;
      ctx.strokeStyle=t.color;ctx.fillStyle=t.color;ctx.lineWidth=1.7;
      if(get('gps-review-curves').checked) {
        ctx.lineWidth=1;
        for(const segment of t.curves||[]) {
          let started=false;ctx.beginPath();
          for(const p of segment) {
            if(p.seq>t.points[t.limit]?.seq)break;
            const [x,y]=xy(p);if(!started){ctx.moveTo(x,y);started=true;}else{ctx.lineTo(x,y);curveCount++;}
          }
          ctx.stroke();
        }
      }
      ctx.lineWidth=1;
      let arrowDistance=0;
      for(let i=0;i<=t.limit;i++) {
        const p=t.points[i],[x,y]=xy(p);pointCount++;
        if(i && !p.break_before && get('gps-review-raw').checked) {
          ctx.globalAlpha=.25;
          const [px,py]=xy(t.points[i-1]),length=Math.hypot(x-px,y-py);
          ctx.beginPath();ctx.moveTo(px,py);ctx.lineTo(x,y);ctx.stroke();segments++;
          arrowDistance+=length;
          if(length>2 && arrowDistance>=55) {
            const angle=Math.atan2(y-py,x-px),ax=(x+px)/2,ay=(y+py)/2;
            ctx.beginPath();ctx.moveTo(ax,ay);
            ctx.lineTo(ax-8*Math.cos(angle-.5),ay-8*Math.sin(angle-.5));
            ctx.moveTo(ax,ay);ctx.lineTo(ax-8*Math.cos(angle+.5),ay-8*Math.sin(angle+.5));ctx.stroke();
            arrowDistance=0;
          }
        }
        ctx.globalAlpha=1;
        if(isExcluded(t,p.seq)){
          ctx.strokeStyle='#a0a8b1';ctx.beginPath();ctx.lineWidth=2;ctx.moveTo(x-5,y-5);ctx.lineTo(x+5,y+5);ctx.moveTo(x-5,y+5);ctx.lineTo(x+5,y-5);ctx.stroke();ctx.strokeStyle=t.color;
        }else {ctx.fillStyle=t.color;ctx.beginPath();ctx.arc(x,y,4,0,Math.PI*2);ctx.fill();}
        if(selected.has(selectionKey({track:ti,index:i}))){
          ctx.strokeStyle='#ed3f83';ctx.lineWidth=2;ctx.beginPath();ctx.arc(x,y,9,0,Math.PI*2);ctx.stroke();ctx.strokeStyle=t.color;
        }
        ctx.lineWidth=1;
      }
      if(t.limit>=0) {
        const [x,y]=xy(t.points[t.limit]);ctx.beginPath();ctx.arc(x,y,5,0,Math.PI*2);ctx.stroke();
      }
      for(const end of [false,true]) {
        const bound=end?t.endSeq:t.startSeq;
        const p=bound===null?(end?t.points[t.points.length-1]:t.points[0]):t.points.find(p=>p.seq===bound), [x,y]=xy(p);
        ctx.fillStyle='white';ctx.strokeStyle=t.color;ctx.lineWidth=2.5;ctx.beginPath();
        if(end)ctx.rect(x-6,y-6,12,12);else ctx.arc(x,y,7,0,Math.PI*2);
        ctx.fill();ctx.stroke();
        labels.push({x,y,color:t.color,text:`${t.name} ${end?'끝':'시작'} #${p.seq}`,end});
      }
      if(selection?.track===ti && selection.index<=t.limit) {
        const [x,y]=xy(t.points[selection.index]);ctx.strokeStyle='#172b42';ctx.lineWidth=2;
        ctx.beginPath();ctx.arc(x,y,11,0,Math.PI*2);ctx.stroke();
        if(nearest && get('gps-review-curves').checked) {
          const [qx,qy]=xy(nearest);ctx.save();ctx.strokeStyle='#963dac';ctx.lineWidth=2;ctx.setLineDash([5,4]);
          ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(qx,qy);ctx.stroke();ctx.setLineDash([]);
          ctx.fillStyle='#fff';ctx.beginPath();ctx.arc(qx,qy,5,0,Math.PI*2);ctx.fill();ctx.stroke();ctx.restore();
        }
      }
    }
    // Label placement is separate so coincident start/end labels remain readable.
    ctx.font='bold 12px system-ui';const boxes=[];
    for(const label of labels) {
      const {x,y,text,color,end}=label;
      if(x<0||x>width||y<0||y>height)continue;
      const w=ctx.measureText(text).width+12,h=23;
      const lx=Math.max(4,Math.min(width-w-4,x+14));
      let ly=Math.max(52,Math.min(height-h-55,y+(end?14:-32)));
      for(let attempt=0;attempt<100;attempt++) {
        if(!boxes.some(b=>lx<b.x+b.w&&lx+w>b.x&&ly<b.y+b.h&&ly+h>b.y))break;
        ly+=h+4;if(ly>height-h-45)ly=52;
      }
      boxes.push({x:lx,y:ly,w,h});ctx.strokeStyle=color;ctx.lineWidth=1;
      ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(lx,ly+h/2);ctx.stroke();
      ctx.fillStyle='rgba(255,255,255,.95)';ctx.fillRect(lx,ly,w,h);ctx.strokeRect(lx,ly,w,h);
      ctx.fillStyle=color;ctx.fillText(text,lx+6,ly+16);
    }
    window.drawGpsScale(ctx,width,height,scale);
    if(drag&&!drag.pan&&drag.moved){
      ctx.save();ctx.fillStyle='rgba(237,63,131,.12)';ctx.strokeStyle='#ed3f83';ctx.lineWidth=1.5;ctx.setLineDash([5,3]);
      ctx.fillRect(drag.startX,drag.startY,drag.x-drag.startX,drag.y-drag.startY);
      ctx.strokeRect(drag.startX,drag.startY,drag.x-drag.startX,drag.y-drag.startY);ctx.restore();
    }
    canvas.dataset.selectedCount=String(selected.size);
    canvas.dataset.pointCount=String(pointCount);canvas.dataset.segmentCount=String(segments);
    canvas.dataset.endpointCount=String(labels.length);canvas.dataset.curveSegmentCount=String(curveCount);
  }
  function fit() {
    let minE=Infinity,maxE=-Infinity,minN=Infinity,maxN=-Infinity;
    for(const t of tracks)if(t.visible)for(const p of t.points){minE=Math.min(minE,p.e);maxE=Math.max(maxE,p.e);minN=Math.min(minN,p.n);maxN=Math.max(maxN,p.n);}
    for(const p of window.gpsReferencePoints()){minE=Math.min(minE,p.e);maxE=Math.max(maxE,p.e);minN=Math.min(minN,p.n);maxN=Math.max(maxN,p.n);}
    if(Number.isFinite(minE)) {
      cx=(minE+maxE)/2;cy=(minN+maxN)/2;
      scale=Math.max(.0001,Math.min(Math.max(20,width-240)/Math.max(2,maxE-minE),Math.max(20,height-180)/Math.max(2,maxN-minN)));
    }
    draw();
  }
  function resize(){
    if(!active())return;
    const r=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;
    width=Math.max(1,r.width);height=Math.max(1,r.height);canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
    ctx.setTransform(dpr,0,0,dpr,0,0);if(follow)fit();else draw();
  }
  function controls(){
    const parent=get('gps-test-tracks');parent.replaceChildren();
    tracks.forEach((t,ti)=>{
      const row=document.createElement('div');row.style.cssText='margin:12px 0;padding-bottom:10px;border-bottom:1px solid #dce2ea';
      const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.checked=t.visible;
      check.setAttribute('aria-label',`${t.name} 표시`);label.style.color=t.color;label.append(check,` ${t.name}`);
      check.onchange=()=>{
        t.visible=check.checked;
        if(!t.visible){
          for(const [key,hit] of selected)if(hit.track===ti)selected.delete(key);
          if(selection?.track===ti)clearFocus();
          if(selected.size===1){const hit=selected.values().next().value;setCandidates([hit]);choose(hit);}
          else if(selected.size>1)clearFocus();
          selectionUI();
        }
        if(follow)fit();else draw();
      };
      const slider=document.createElement('input');slider.type='range';slider.min=0;slider.max=Math.max(0,t.points.length-1);slider.value=String(Math.max(0,t.limit));
      slider.disabled=!t.points.length;slider.style.width='100%';slider.setAttribute('aria-label',`${t.name} 원본 순번`);
      const output=document.createElement('output');output.style.fontSize='.75rem';
      const update=()=>{output.textContent=t.points.length?`#${t.points[t.limit].seq} / #${t.points.at(-1).seq} · ${t.points.length}점`:'유효 GPS 없음';};
      slider.oninput=()=>{t.limit=Number(slider.value);selection={track:ti,index:t.limit};update();setCandidates([selection]);choose(selection);};
      const summary=document.createElement('p');summary.style.fontSize='.75rem';summary.hidden=window.dashboardModes.buildStep==='bags';t.summary=summary;
      const smoothLabel=document.createElement('label');smoothLabel.hidden=true;smoothLabel.style.fontSize='.75rem';smoothLabel.textContent='매끄러움 (m) ';
      const smoothInput=document.createElement('input');smoothInput.type='number';smoothInput.min=0;smoothInput.max=10;smoothInput.step=.1;smoothInput.value=t.smoothing;
      smoothInput.style.width='65px';smoothInput.setAttribute('aria-label',`${t.name} 매끄러움`);t.smoothInput=smoothInput;
      smoothInput.onchange=()=>{
        if(!smoothInput.checkValidity()||smoothInput.value===''){smoothInput.value=t.smoothing;return;}
        remember(t);t.smoothing=Number(smoothInput.value);t.complete=false;changed(t);
      };smoothLabel.append(smoothInput);
      const restore=document.createElement('button');restore.type='button';restore.textContent='이 기록 전체 복원';restore.hidden=window.dashboardModes.buildStep==='bags';restore.style.fontSize='.75rem';
      restore.onclick=()=>{if(!t.excluded.size&&t.startSeq===null&&t.endSeq===null)return;remember(t);t.excluded.clear();t.startSeq=null;t.endSeq=null;t.complete=false;changed(t);};
      update();row.append(label,slider,output,summary,smoothLabel,restore);parent.append(row);updateSummary(t);
    });
  }
  function nearestOnCurve(point,segments){
    let best=null;
    // Project onto every rendered line segment, not just the sampled vertices.
    // Separate segments represent GPS gaps and must never be joined here.
    for(const segment of segments||[])for(let i=1;i<segment.length;i++) {
      const a=segment[i-1],b=segment[i],de=b.e-a.e,dn=b.n-a.n,denom=de*de+dn*dn;
      const u=denom?Math.max(0,Math.min(1,((point.e-a.e)*de+(point.n-a.n)*dn)/denom)):0;
      const e=a.e+u*de,n=a.n+u*dn,distance=Math.hypot(point.e-e,point.n-n);
      if(!best||distance<best.distance)best={e,n,distance};
    }
    return best;
  }
  function updateDistance(){
    const output=get('gps-review-distance');
    if(!selection){output.textContent='평활선 거리: 점을 선택하세요.';delete output.dataset.distanceM;return null;}
    const t=tracks[selection.track],point=t.points[selection.index];
    const nearest=t.pending||t.curveError?null:nearestOnCurve(point,t.curves);
    output.textContent=t.pending?'평활선 거리: 곡선 계산 중…':t.curveError?'평활선 거리: 곡선 계산 실패':
      nearest?`평활선 최단 거리: 약 ${nearest.distance.toFixed(3)} m (${(nearest.distance*100).toFixed(1)} cm)`:'평활선 거리: 계산할 곡선이 없습니다.';
    if(nearest)output.dataset.distanceM=String(nearest.distance);else delete output.dataset.distanceM;
    return nearest;
  }
  function describe(t,p){if(p)info.textContent=`${t.name} · 원본 #${p.seq} · 위도 ${p.lat.toFixed(9)} · 경도 ${p.lon.toFixed(9)}`;}
  let cameraVersion=0;
  const cameraImage=get('gps-test-camera-image'), cameraInfo=get('gps-test-camera-info');
  const cameraMessage=get('gps-test-camera-message'), candidates=get('gps-test-candidates');
  function showCamera(t,p){
    const version=++cameraVersion;
    cameraImage.hidden=true;cameraImage.removeAttribute('src');
    cameraInfo.textContent=`${t.name} · 원본 #${p.seq}`;
    if(!p.camera){cameraMessage.textContent='이 GPS 시각의 0.5초 이내에 카메라 프레임이 없습니다.';return;}
    cameraMessage.textContent='프레임 불러오는 중…';
    const pending=new Image();
    pending.onload=()=>{
      if(version!==cameraVersion)return;
      cameraImage.src=pending.src;cameraImage.alt=`${t.name} GPS #${p.seq} 시각의 카메라`;
      cameraImage.hidden=false;cameraMessage.textContent='';
      cameraInfo.textContent=`${t.name} · 원본 #${p.seq} · GPS 대비 ${p.camera.offset_ms>=0?'+':''}${p.camera.offset_ms.toFixed(1)} ms`;
    };
    pending.onerror=()=>{if(version===cameraVersion)cameraMessage.textContent='카메라 프레임을 불러오지 못했습니다.';};
    pending.src=`/api/gps/test/frames/${encodeURIComponent(p.camera.file)}`;
  }
  function choose(hit){
    selected.clear();selected.set(selectionKey(hit),hit);
    selection=hit;const t=tracks[hit.track],p=t.points[hit.index];
    describe(t,p);showCamera(t,p);selectionUI();draw();
  }
  function clearFocus(){
    selection=null;++cameraVersion;cameraImage.hidden=true;cameraImage.removeAttribute('src');
    cameraInfo.textContent=selected.size?`${selected.size}점 선택됨 · 한 점을 클릭하면 카메라를 확인할 수 있습니다.`:'GPS 점을 선택하세요.';
    cameraMessage.textContent='지도의 점을 선택하세요.';setCandidates([]);
  }
  function setCandidates(hits){
    candidates.replaceChildren(...hits.map((h,i)=>new Option(`${tracks[h.track].name} · #${tracks[h.track].points[h.index].seq}`,String(i))));
    candidates.disabled=!hits.length;
    candidates.onchange=()=>{const hit=hits[Number(candidates.value)];if(hit)choose(hit);};
  }
  function updateSummary(t){
    const count=t.points.filter(p=>isExcluded(t,p.seq)).length;
    if(t.summary)t.summary.textContent=`남음 ${t.points.length-count} / 제외 ${count}점 · 범위 #${t.startSeq??t.points[0]?.seq??"-"}~#${t.endSeq??t.points.at(-1)?.seq??"-"}${t.pending?' · 곡선 계산 중…':''}${t.curveError?' · 계산 실패':''}`;
  }
  function selectionUI(){
    if(selected.size>1){
      const editable=[...selected.values()].filter(h=>!outsideRange(tracks[h.track],tracks[h.track].points[h.index].seq));
      const restore=editable.length>0&&editable.every(h=>tracks[h.track].excluded.has(tracks[h.track].points[h.index].seq));
      const button=get('gps-review-toggle');button.disabled=sourceBusy||!editable.length;
      button.textContent=restore?'선택 점 일괄 복원':'선택 점 일괄 제외';
      for(const id of ['gps-review-start','gps-review-end','gps-review-range-reset'])get(id).disabled=true;
      get('gps-review-selection').textContent=`선택 ${selected.size}점 · ${new Set([...selected.values()].map(h=>h.track)).size}개 기록`+
        (editable.length<selected.size?` · 범위 밖 ${selected.size-editable.length}점은 자동 제외 상태 유지`:'');
      return;
    }
    const button=get('gps-review-toggle');button.disabled=!selection||sourceBusy;
    button.textContent='선택 점 제외';
    for(const id of ['gps-review-start','gps-review-end','gps-review-range-reset'])get(id).disabled=!selection||sourceBusy;
    if(!selection||sourceBusy){get('gps-review-selection').textContent='점을 선택한 뒤 제외 또는 복원하세요.';return;}
    const t=tracks[selection.track],p=t.points[selection.index],excluded=isExcluded(t,p.seq);
    const outside=outsideRange(t,p.seq);button.disabled=outside;
    get('gps-review-start').disabled=t.endSeq!==null&&p.seq>t.endSeq;
    get('gps-review-end').disabled=t.startSeq!==null&&p.seq<t.startSeq;
    get('gps-review-range-reset').disabled=t.startSeq===null&&t.endSeq===null;
    button.textContent=excluded?'선택 점 복원':'선택 점 제외';
    get('gps-review-selection').textContent=`${t.name} #${p.seq} · ${outside?'범위 밖 자동 제외 · 범위를 넓히거나 초기화하면 복원됩니다':excluded?'제외됨':'계산에 포함'}`;
  }
  function remember(...items){history.push(items.map(t=>({id:t.id,excluded:[...t.excluded],startSeq:t.startSeq,endSeq:t.endSeq,smoothing:t.smoothing,complete:t.complete})));}
  function stateUI(message){
    get('gps-review-save').disabled=!loaded||saving||sourceBusy;get('gps-review-undo').disabled=!history.length||sourceBusy;
    get('gps-test-reload').disabled=dirty||saving||sourceBusy;
    sourceUI();
    if(message)reviewStatus.textContent=gpsProject.formatStages(message);
    selectionUI();
  }
  function spec(t){return {id:t.id,excluded_seq:[...t.excluded].sort((a,b)=>a-b),start_seq:t.startSeq,end_seq:t.endSeq,smoothing_m:t.smoothing,complete:t.complete};}
  async function request(url,body){
    const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Control':'1'},body:JSON.stringify(body)});
    if(!response.ok)throw Error(await response.text());return response.json();
  }
  function changed(t,preview=true){
    dirty=true;editVersion++;stateUI('저장되지 않은 변경이 있습니다. 로컬 저장을 눌러주세요.');
    if(preview){
      clearTimeout(t.previewTimer);t.previewController?.abort();
      const version=(t.previewVersion||0)+1;t.previewVersion=version;t.curves=[];t.pending=true;t.curveError=false;
      t.previewTimer=setTimeout(async()=>{
        const controller=new AbortController();t.previewController=controller;
        try{
          const projectPreview=useSaved;
          const response=await fetch(projectPreview?'/api/gps/projects/preview':'/api/gps/review/preview',{method:'POST',signal:controller.signal,
            headers:{'Content-Type':'application/json','X-Dashboard-Control':'1'},body:JSON.stringify(projectPreview?{filename:window.gpsProject.current.filename,step:window.dashboardModes.buildStep,dataset_id:datasetId,tracks:tracks.map(spec)}:{dataset_id:datasetId,tracks:[spec(t)]})});
          if(!response.ok)throw Error(await response.text());
          const data=await response.json();if(t.previewVersion!==version)return;
          t.curves=data.tracks.find(r=>r.id===t.id).curve_segments;
        }catch(error){if(t.previewVersion!==version||error.name==='AbortError')return;t.curveError=true;stateUI(`곡선 계산 실패: ${error.message}`);}
        finally{if(t.previewVersion===version){t.pending=false;updateSummary(t);draw();}}
      },160);
    }
    updateSummary(t);draw();
  }
  function setBoundary(which){
    if(!selection)return;const t=tracks[selection.track],seq=t.points[selection.index].seq;
    if((which==='startSeq'&&t.endSeq!==null&&seq>t.endSeq)||(which==='endSeq'&&t.startSeq!==null&&seq<t.startSeq))return;
    remember(t);t[which]=seq;t.excluded.delete(seq);t.complete=false;changed(t);
  }
  get('gps-review-start').onclick=()=>setBoundary('startSeq');
  get('gps-review-end').onclick=()=>setBoundary('endSeq');
  get('gps-review-range-reset').onclick=()=>{
    if(!selection)return;const t=tracks[selection.track];remember(t);t.startSeq=null;t.endSeq=null;t.complete=false;changed(t);
  };
  get('gps-review-toggle').onclick=()=>{
    if(sourceBusy||!selected.size)return;
    const editable=[...selected.values()].filter(h=>!outsideRange(tracks[h.track],tracks[h.track].points[h.index].seq));
    if(!editable.length)return;
    const restore=editable.every(h=>tracks[h.track].excluded.has(tracks[h.track].points[h.index].seq));
    const affected=[...new Set(editable.filter(h=>restore||!tracks[h.track].excluded.has(tracks[h.track].points[h.index].seq)).map(h=>tracks[h.track]))];
    remember(...affected);
    for(const h of editable){const t=tracks[h.track],seq=t.points[h.index].seq;if(restore)t.excluded.delete(seq);else t.excluded.add(seq);}
    for(const t of affected){t.complete=false;changed(t);}
  };
  get('gps-review-undo').onclick=()=>{
    const previous=history.pop();if(!previous)return;
    for(const saved of previous){const t=tracks.find(t=>t.id===saved.id);
      t.excluded=new Set(saved.excluded);t.startSeq=saved.startSeq;t.endSeq=saved.endSeq;t.smoothing=saved.smoothing;t.complete=saved.complete;t.smoothInput.value=t.smoothing;changed(t);
    }
  };
  async function save(){
    if(saving||loading||sourceBusy)throw Error('GPS를 불러오거나 저장하는 중입니다. 잠시 기다려주세요.');
    if(!loaded||!sourceRaw)return;
    saving=true;const version=editVersion;stateUI('현재 맵 파일에 저장 중…');
    try{
      if(window.dashboardModes.buildStep==='bags'){
        if(JSON.stringify([...sourceSelection].sort())!==JSON.stringify([...loadedBags].sort()))throw Error('선택한 로스백 불러오기를 눌러 GPS를 먼저 확인하세요.');
        await window.gpsProject.save(2,{dataset_id:datasetId,use_saved:useSaved,bags:loadedBags,map_merge:get('gps-source-map-merge').checked,display:{linear:get('gps-review-raw').checked,smooth:get('gps-review-curves').checked}});
        useSaved=true;
      }else await window.gpsProject.save(3,{dataset_id:datasetId,tracks:tracks.map(spec)});
      if(version===editVersion){dirty=false;mapMergeDirty=false;}
      stateUI('현재 맵 파일에 저장했습니다.');
    }finally{saving=false;stateUI();}
  }
  get('gps-source-save').onclick=()=>save().then(()=>{get('gps-source-status').textContent='2단계 저장 완료 · '+gpsProject.current.filename;}).catch(e=>{get('gps-source-status').textContent=e.message;});
  get('gps-review-save').onclick=()=>save().catch(e=>stateUI(e.message));
  window.gpsEditor={save,get busy(){return loading||saving||sourceBusy;}};
  window.addEventListener('gps:projectchange',()=>{get('gps-source-map-merge').checked=gpsProject.mapMergeEnabled;mapMergeDirty=false;});
  get('gps-source-map-merge').onchange=()=>{mapMergeDirty=true;editVersion++;stateUI('MAP 병합 설정 변경 · 2단계 저장을 누르세요.');};
  get('gps-review-raw').onchange=draw;get('gps-review-curves').onchange=draw;
  window.addEventListener('beforeunload',event=>{if(dirty||mapMergeDirty){event.preventDefault();event.returnValue='';}});
  function sourceUI(){
    get('gps-source-used').textContent=loaded&&loadedBags.length?`GPS 추출에 사용한 로스백 (${useSaved?'저장됨':'저장 전'})\n${loadedBags.join('\n')}`:'';
    get('gps-source-map-merge').disabled=saving||loading||sourceBusy;
    get('gps-source-save').disabled=!loaded||!sourceRaw||saving||loading||sourceBusy;
    get('gps-source-load').disabled=dirty||saving||loading||sourceBusy||!sourceSelection.size;
    get('gps-source-load').title=dirty?'먼저 현재 검토를 로컬 저장하세요.':'';
    get('gps-source-count').textContent=`선택 ${sourceSelection.size}개 · 현재 작업 ${tracks.length}개${dirty?' · 변경 내용을 저장한 후 기록을 바꿀 수 있습니다.':''}`;
    for(const id of ['gps-source-refresh','gps-source-all','gps-source-clear'])get(id).disabled=sourceBusy;
    get('gps-source-list').inert=sourceBusy;get('gps-test-tracks').inert=sourceBusy;
  }
  function renderSources(){
    const query=get('gps-source-filter').value.trim().toLowerCase(),list=get('gps-source-list');list.replaceChildren();
    for(const entry of sourceEntries.filter(e=>e.id.toLowerCase().includes(query))){
      const label=document.createElement('label');label.style.cssText='display:block;padding:5px 0;font-size:.75rem;overflow-wrap:anywhere';
      const check=document.createElement('input');check.type='checkbox';check.checked=sourceSelection.has(entry.id);check.disabled=!entry.supported;
      check.dataset.bagId=entry.id;check.setAttribute('aria-label',entry.id);
      check.onchange=()=>{if(check.checked)sourceSelection.add(entry.id);else sourceSelection.delete(entry.id);sourceUI();};
      const note=`GPS ${entry.gps_count??'?'}점 · ${entry.camera_count ? `카메라 ${entry.camera_count.toLocaleString()}프레임` : '카메라 기록 없음'}`;
      label.append(check,` ${entry.id}`);const detail=document.createElement('small');detail.style.cssText='display:block;margin-left:20px;color:#697b8e';detail.textContent=note;
      label.append(detail);list.append(label);
    }
    if(!list.children.length)list.textContent='표시할 로스백이 없습니다.';sourceUI();
  }
  async function sourceRequest(action,body){
    const options=body?{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Control':'1'},body:JSON.stringify(body)}:{cache:'no-store'};
    const response=await fetch('/api/gps/source/'+action,options),data=await response.json();
    if(!response.ok)throw Error(data.error||'로스백 서비스 요청 실패');return data;
  }
  async function refreshSources(reset=false){
    try{
      const data=await sourceRequest('bags');sourceEntries=data.bags;
      // Only restore selections from this project's loaded GPS, never the global last-used bags.
      if(reset)sourceSelection=new Set(loadedBags);
      sourceSelection=new Set([...sourceSelection].filter(id=>sourceEntries.some(entry=>entry.id===id)));
      sourceReady=true;renderSources();get('gps-source-status').textContent=`main/bags/ · ${sourceEntries.length}개 기록`;
      if(!sourceBusy){const state=await sourceRequest('status');if(state.phase==='running'){sourceBusy=true;sourceUI();pollSource(state.job_id);}}
    }catch(error){get('gps-source-status').textContent=error.message;}
  }
  async function pollSource(job){
    clearTimeout(sourceTimer);
    try{
      const state=await sourceRequest('status');
      if(state.job_id!==job)throw Error('다른 불러오기 작업이 시작되었습니다. 목록을 새로고침하세요.');
      if(state.phase==='running'){
        get('gps-source-status').textContent=`준비 중 ${state.completed}/${state.total} · ${state.current||'대기'} · 압축 bag은 시간이 걸릴 수 있습니다.`;
        sourceTimer=setTimeout(()=>pollSource(job),1000);return;
      }
      if(state.phase==='error')throw Error(state.error);
      sourceBusy=false;sourceUI();await load(true);await refreshSources(true);
      const warnings=state.warnings||[];
      get('gps-source-status').textContent=`불러오기 완료 · ${state.loaded_count??state.total}개 기록 · ${state.point_count}점`+
        (warnings.length?` · 제외 ${warnings.length}개: `+warnings.map(w=>`${w.bag}: ${w.error}`).join(' / '):'');
    }catch(error){sourceBusy=false;sourceUI();selectionUI();get('gps-source-status').textContent=`불러오기 실패: ${error.message}`;}
  }
  get('gps-source-filter').oninput=renderSources;
  get('gps-source-refresh').onclick=()=>refreshSources();
  get('gps-source-all').onclick=()=>{const q=get('gps-source-filter').value.trim().toLowerCase();for(const e of sourceEntries)if(e.supported&&e.id.toLowerCase().includes(q))sourceSelection.add(e.id);renderSources();};
  get('gps-source-clear').onclick=()=>{sourceSelection.clear();renderSources();};
  get('gps-source-load').onclick=async()=>{
    if(dirty||saving||loading||sourceBusy||!sourceSelection.size)return;
    sourceBusy=true;sourceUI();selectionUI();get('gps-source-status').textContent='로스백 준비 요청 중…';
    try{const state=await sourceRequest('prepare',{bags:[...sourceSelection]});pollSource(state.job_id);}
    catch(error){sourceBusy=false;sourceUI();selectionUI();get('gps-source-status').textContent=error.message;}
  };
  async function load(live=false){
    if(loading||dirty)return;loading=true;sourceUI();status.textContent='원본 GPS 불러오는 중…';
    try{
      let data,review;
      if(live){
        const response=await fetch('/api/gps/test',{cache:'no-store'});if(!response.ok)throw Error('원본 GPS를 불러오지 못했습니다.');data=await response.json();
        const responseReview=await fetch('/api/gps/review',{cache:'no-store'});if(!responseReview.ok)throw Error('GPS 정보를 확인하지 못했습니다.');const ids=await responseReview.json();
        if(ids.dataset_id!==data.review_dataset_id)throw Error('GPS가 변경됐습니다. 다시 불러오세요.');
        review=await request('/api/gps/review/preview',{dataset_id:ids.dataset_id,tracks:ids.tracks.map(t=>({id:t.id,excluded_seq:[],smoothing_m:.5}))});review.dataset_id=ids.dataset_id;
        useSaved=false;loadedBags=data.selected_bags||[...sourceSelection];
      }else{
        const project=window.gpsProject.current;if(!project)return;
        const result=await window.gpsProject.api('/api/gps/projects/editor?filename='+encodeURIComponent(project.filename)+'&step='+window.dashboardModes.buildStep);
        if(!result.raw){loaded=false;sourceRaw=null;tracks=[];selected.clear();drag=null;clearFocus();stateUI();controls();draw();status.textContent='ROS bag을 선택하고 불러오세요.';return;}
        data=result.raw;review=result.review;useSaved=true;loadedBags=project.project.stages['2'].bags;sourceSelection=new Set(loadedBags);
        const display=project.project.stages['2'].display;get('gps-review-raw').checked=display.linear;get('gps-review-curves').checked=display.smooth;
      }
      sourceRaw=data;loadStep=window.dashboardModes.buildStep;
      datasetId=review.dataset_id;revision=review.revision;history=[];
      tracks=project(data).map((t,i)=>({...t,id:review.tracks[i].id,excluded:new Set(review.tracks[i].manual_excluded_seq??review.tracks[i].excluded_seq),
        startSeq:review.tracks[i].start_seq??null,endSeq:review.tracks[i].end_seq??null,
        smoothing:review.tracks[i].smoothing_m,complete:review.tracks[i].complete,curves:review.tracks[i].curve_segments}));
      selected.clear();drag=null;selection=null;stateUI(review.saved_at?'저장된 검토 기록을 불러왔습니다.':'아직 저장된 검토가 없습니다.');
      selection=null;++cameraVersion;cameraImage.hidden=true;cameraImage.removeAttribute('src');cameraInfo.textContent='GPS 점을 선택하세요.';cameraMessage.textContent='지도의 점을 선택하세요.';setCandidates([]);loaded=true;controls();stateUI();follow=true;resize();
      status.textContent=`원본 ${tracks.length}개 기록 · ${tracks.reduce((n,t)=>n+t.points.length,0)}점 · 북 ↑ / 동 →`;
      info.textContent=window.dashboardModes.buildStep==='points'?'클릭: 한 점 선택 · 왼쪽 드래그: 누적 선택 · 오른쪽/가운데 드래그: 이동 · 휠: 확대 · Esc: 선택 해제':'점을 클릭해 기록과 순번을 확인하세요. 드래그 이동 · 휠 확대';
    }catch(error){status.textContent=`불러오기 실패: ${error.message}`;reviewStatus.textContent='검토 기록을 불러오지 못했습니다.';}finally{loading=false;sourceUI();}
  }
  canvas.addEventListener('wheel',event=>{
    event.preventDefault();follow=false;const r=canvas.getBoundingClientRect(),x=event.clientX-r.left-width/2,y=event.clientY-r.top-height/2;
    const next=Math.max(.0001,Math.min(100000,scale*Math.exp(-event.deltaY*.001)));
    cx+=x/scale-x/next;cy-=y/scale-y/next;scale=next;draw();
  },{passive:false});
  const pos=e=>{const r=canvas.getBoundingClientRect();return [e.clientX-r.left,e.clientY-r.top];};
  canvas.addEventListener('contextmenu',e=>e.preventDefault());
  canvas.addEventListener('pointerdown',e=>{
    if(sourceBusy||loading||!loaded||e.button>2)return;
    const [x,y]=pos(e);drag={x,y,startX:x,startY:y,pan:e.button!==0||window.dashboardModes.buildStep!=='points',moved:false};
    canvas.setPointerCapture(e.pointerId);e.preventDefault();
  });
  canvas.addEventListener('pointermove',e=>{
    if(!drag)return;
    const [x,y]=pos(e);drag.moved ||= Math.hypot(x-drag.startX,y-drag.startY)>4;
    if(drag.moved&&drag.pan){follow=false;cx-=(x-drag.x)/scale;cy+=(y-drag.y)/scale;}
    drag.x=x;drag.y=y;draw();
  });
  canvas.addEventListener('pointerup',e=>{
    if(!drag)return;const d=drag;drag=null;const [x,y]=pos(e);
    d.moved ||= Math.hypot(x-d.startX,y-d.startY)>4;
    if(!d.pan&&d.moved){
      tracks.forEach((t,ti)=>{if(t.visible)for(let i=0;i<=t.limit;i++){
        const [px,py]=xy(t.points[i]);
        if(px>=Math.min(x,d.startX)&&px<=Math.max(x,d.startX)&&py>=Math.min(y,d.startY)&&py<=Math.max(y,d.startY)){
          const hit={track:ti,index:i};selected.set(selectionKey(hit),hit);
        }
      }});
      if(selected.size===1){const hit=selected.values().next().value;setCandidates([hit]);choose(hit);}
      else{clearFocus();selectionUI();info.textContent=`선택 ${selected.size}점 · 드래그로 선택을 추가할 수 있습니다. Esc: 선택 해제`;}
    }else if(!d.moved&&e.button===0){
      const hits=[];
      tracks.forEach((t,ti)=>{if(t.visible)for(let i=0;i<=t.limit;i++){
        const [px,py]=xy(t.points[i]),distance=Math.hypot(px-x,py-y);
        if(distance<=12)hits.push({track:ti,index:i,distance});
      }});
      hits.sort((a,b)=>a.distance-b.distance);
      setCandidates(hits);
      if(hits.length){choose(hits[0]);}
      else{selected.clear();clearFocus();selectionUI();info.textContent='점 가까이를 클릭하세요.';}
    }draw();
  });
  for(const name of ['pointercancel','lostpointercapture'])canvas.addEventListener(name,()=>{drag=null;draw();});
  window.addEventListener('keydown',e=>{
    if(e.key!=='Escape'||!active()||sourceBusy||drag||document.querySelector('dialog[open]'))return;
    selected.clear();clearFocus();selectionUI();draw();
  });
  get('gps-test-fit').onclick=()=>{follow=true;fit();};canvas.ondblclick=()=>{follow=true;fit();};
  get('gps-test-reload').onclick=()=>load(false);
  window.addEventListener('gps:projectchange',()=>{loaded=false;sourceRaw=null;tracks=[];dirty=false;history=[];selection=null;selected.clear();drag=null;sourceSelection=new Set();sourceReady=false;loadStep=null;get('gps-review-raw').checked=true;get('gps-review-curves').checked=true;controls();});
  window.addEventListener('dashboard:modechange',()=>{if(active()){if(!loaded||loadStep!==window.dashboardModes.buildStep){load().then(()=>{if(window.dashboardModes.buildStep==='bags')refreshSources();});}else{controls();resize();}}});
  new ResizeObserver(resize).observe(canvas);
})();
