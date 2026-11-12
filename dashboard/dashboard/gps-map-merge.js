/* Copy GPS intervals, rotate and translate them onto the saved step-2 map. */
(() => {
  const $=id=>document.getElementById(id),root=$('gps-map-merge-view');if(!root)return;
  const active=()=>dashboardModes.current==='map-build'&&dashboardModes.buildStep==='map-merge';
  const palette=['#1769c2','#d45a16','#168052','#8b43ad','#ac3970','#65710c'];
  let entries=[],selected=new Set(),loadedBags=[],loading=false,catalogLoading=false,version=0,controller=null;
  let origin=null,clips=[],clipboard=null,range=null,selectedClip=null,history=[],dirty=false,saving=false,initialized=false,editSerial=0,rotationSession=null,rotationError=false;
  const copy=value=>JSON.parse(JSON.stringify(value));
  const panes=['left','right'].map(side=>({side,canvas:$('gps-map-merge-'+side),info:$('gps-map-merge-'+side+'-info'),tracks:[],width:1,height:1,scale:1,e:0,n:0,drag:null}));
  const status=text=>$('gps-map-merge-status').textContent=text;
  const hasVisiblePoints=pane=>pane.tracks.some(t=>t.visible&&t.points.length);
  function update(){
    const selectedPlacement=clips.find(c=>c.id===selectedClip);
    for(const id of ['rotation','rotation-slider','rotate-clockwise','rotate-counterclockwise','rotation-reset'])$('gps-map-merge-'+id).disabled=loading||saving||!selectedPlacement;
    if(!selectedPlacement){rotationError=false;$('gps-map-merge-rotation').setCustomValidity('');}
    const degrees=selectedPlacement?.rotation_deg||0;
    if(!rotationError)$('gps-map-merge-rotation').value=degrees;
    $('gps-map-merge-rotation-slider').value=degrees;
    $('gps-map-merge-same-scale').disabled=loading||saving||!panes.every(hasVisiblePoints);
    $('gps-map-merge-copy').disabled=loading||saving||!selectedRange();
    $('gps-map-merge-paste').disabled=loading||saving||!clipboard;
    $('gps-map-merge-save').disabled=loading||saving||rotationError||!dirty;
    $('gps-map-merge-next').disabled=loading||saving||rotationError;
    $('gps-map-merge-delete').disabled=loading||saving||!clips.some(c=>c.id===selectedClip);
    $('gps-map-merge-undo').disabled=loading||saving||!history.length;
    $('gps-map-merge-selection-clear').disabled=loading||saving;
    $('gps-map-merge-placement').textContent=`배치 ${clips.length}개 · ${clips.reduce((n,c)=>n+c.points.length,0).toLocaleString()}점${dirty?' · 미저장':' · 저장됨'}`+(selectedClip?(()=>{const c=clips.find(c=>c.id===selectedClip);return c?` · 선택 구간 이동: 동 ${c.offset_e.toFixed(2)} m / 북 ${c.offset_n.toFixed(2)} m · 회전 ${(c.rotation_deg||0).toFixed(1)}°`:'';})():'');
    const chosen=selectedRange();$('gps-map-merge-selection').textContent=chosen?`${chosen.track.name} · #${chosen.start+1}~#${chosen.end+1} · 양 끝점 포함 ${chosen.end-chosen.start+1}점`:range?`${range.track} · #${range.indices[0]+1} 선택 · 같은 기록의 다른 끝점을 클릭하세요.`:'오른쪽 지도에서 같은 기록의 두 끝점을 클릭하세요.';
    $('gps-map-merge-load').disabled=loading||saving||catalogLoading||!selected.size;
    for(const id of ['filter','refresh','all','clear'])$('gps-map-merge-'+id).disabled=loading||saving||catalogLoading;
    $('gps-map-merge-list').inert=loading||saving||catalogLoading;
    const changed=JSON.stringify([...selected].sort())!==JSON.stringify([...loadedBags].sort());
    $('gps-map-merge-count').textContent=`선택 ${selected.size}개 · 오른쪽에 불러온 기록 ${loadedBags.length}개${changed?' · 선택한 로스백 불러오기를 누르세요.':''}`;
  }
  function project(p){
    const rad=Math.PI/180,[lat,lon]=origin.map(v=>v*rad),a=p.lat*rad,b=p.lon*rad,e2=6.6943799901413165e-3;
    const N=x=>6378137/Math.sqrt(1-e2*Math.sin(x)**2),n=N(a),base=N(lat);
    const dx=n*Math.cos(a)*Math.cos(b)-base*Math.cos(lat)*Math.cos(lon),dy=n*Math.cos(a)*Math.sin(b)-base*Math.cos(lat)*Math.sin(lon),dz=n*(1-e2)*Math.sin(a)-base*(1-e2)*Math.sin(lat);
    return {...p,e:-Math.sin(lon)*dx+Math.cos(lon)*dy,n:-Math.sin(lat)*Math.cos(lon)*dx-Math.sin(lat)*Math.sin(lon)*dy+Math.cos(lat)*dz};
  }
  function selectedRange(){
    if(!range||range.indices.length!==2)return null;
    const track=panes[1].tracks.find(t=>t.visible&&t.name===range.track);
    if(!track)return null;const [start,end]=[...range.indices].sort((a,b)=>a-b);
    return start!==end&&track.points[end]?{track,start,end}:null;
  }
  function remember(){history.push({clips:copy(clips),selectedClip});if(history.length>20)history.shift();}
  function placedPoints(clip){
    const points=clip.points.map(project);let a=Infinity,b=-Infinity,c=Infinity,d=-Infinity;
    for(const p of points){a=Math.min(a,p.e);b=Math.max(b,p.e);c=Math.min(c,p.n);d=Math.max(d,p.n);}
    if(!clip.rotation_deg)return points.map(p=>({...p,e:p.e+clip.offset_e,n:p.n+clip.offset_n}));
    const ce=(a+b)/2,cn=(c+d)/2,angle=(clip.rotation_deg||0)*Math.PI/180,cos=Math.cos(angle),sin=Math.sin(angle);
    return points.map(p=>{const e=p.e-ce,n=p.n-cn;return {...p,e:ce+cos*e-sin*n+clip.offset_e,n:cn+sin*e+cos*n+clip.offset_n};});
  }
  function rotate(value,continuous=false){
    const clip=clips.find(c=>c.id===selectedClip);if(!clip||loading||saving)return;
    const input=$('gps-map-merge-rotation');
    if(String(value).trim()===''||!Number.isFinite(Number(value))){rotationError=true;input.setCustomValidity('회전 각도를 숫자로 입력하세요.');status('회전 각도를 숫자로 입력하세요.');update();return;}
    rotationError=false;input.setCustomValidity('');let angle=Number(value)%360;if(angle>180)angle-=360;if(angle< -180)angle+=360;
    if(angle===(clip.rotation_deg||0)){update();return;}
    if(!continuous||rotationSession!==clip.id)remember();rotationSession=continuous?clip.id:null;
    clip.rotation_deg=angle;input.value=angle;dirty=true;editSerial++;refreshClips(false,false);
    status(`선택 구간을 중심 기준 ${angle.toFixed(1)}°로 회전했습니다. 배치 확정·저장을 누르거나 다음 단계로 진행하세요.`);
  }
  function refreshClips(fitView=false,renderLegend=true){
    const pane=panes[0],existing=new Map(pane.tracks.filter(t=>t.clipId).map(t=>[t.clipId,t]));
    pane.tracks=pane.tracks.filter(t=>!t.clipId);
    for(const clip of clips){const track=existing.get(clip.id)||{visible:true};Object.assign(track,{name:`${clip.bag} · 복사 ${clip.start_seq}~${clip.end_seq}`,clipId:clip.id,color:'#8b43ad',points:placedPoints(clip)});pane.tracks.push(track);}
    if(renderLegend)legend(pane);if(fitView)fit(pane);else draw(pane);update();
  }
  function hitPoint(pane,x,y){
    let nearest=null,distance=12**2;
    for(const t of pane.tracks)if(t.visible)for(const [index,p] of t.points.entries()){const [px,py]=xy(pane,p),d=(x-px)**2+(y-py)**2;if(d<distance){distance=d;nearest={t,p,index};}}
    return nearest;
  }
  function hitClip(pane,x,y){
    for(const t of [...pane.tracks].reverse()){
      if(!t.clipId||!t.visible)continue;
      for(const [i,p] of t.points.entries()){
        const [px,py]=xy(pane,p);if(Math.hypot(x-px,y-py)<=12)return clips.find(c=>c.id===t.clipId);
        if(i&&!p.break_before){const [ax,ay]=xy(pane,t.points[i-1]),dx=px-ax,dy=py-ay,l=dx*dx+dy*dy,f=l?Math.max(0,Math.min(1,((x-ax)*dx+(y-ay)*dy)/l)):0;if(Math.hypot(x-ax-f*dx,y-ay-f*dy)<=9)return clips.find(c=>c.id===t.clipId);}
      }
    }
    return null;
  }
  function selectEndpoint({t,index}){
    if(!range||range.track!==t.name||range.indices.length===2)range={track:t.name,indices:[index]};
    else if(range.indices[0]!==index)range.indices.push(index);
    else status('서로 다른 두 끝점을 선택하세요.');
    draw(panes[1]);update();
  }
  function copyRange(){
    const selected=selectedRange();if(!selected||loading||saving)return;
    const {track,start,end}=selected;
    clipboard={bag:track.name,start_seq:track.points[start].seq,end_seq:track.points[end].seq,points:track.points.slice(start,end+1).map(p=>({seq:p.seq,lat:p.lat,lon:p.lon,break_before:!!p.break_before}))};
    status(`양 끝점을 포함한 ${clipboard.points.length}점을 복사했습니다. 왼쪽에 붙여넣기를 누르세요.`);update();
  }
  function paste(){
    if(!clipboard||loading||saving)return;if(clips.length>=100){status('배치 구간은 최대 100개입니다.');return;}
    if(clips.reduce((n,c)=>n+c.points.length,0)+clipboard.points.length>100000){status('배치 GPS는 최대 100,000점입니다.');return;}
    remember();const points=clipboard.points.map(project);let a=Infinity,b=-Infinity,c=Infinity,d=-Infinity;
    for(const p of points){a=Math.min(a,p.e);b=Math.max(b,p.e);c=Math.min(c,p.n);d=Math.max(d,p.n);}
    const id='clip-'+(crypto.randomUUID?.()||`${Date.now()}-${Math.random().toString(36).slice(2)}`);
    clips.push({...copy(clipboard),id,rotation_deg:0,offset_e:panes[0].e-(a+b)/2,offset_n:panes[0].n-(c+d)/2});selectedClip=id;rotationSession=null;rotationError=false;dirty=true;editSerial++;refreshClips();
    status('왼쪽에 구간을 붙여넣었습니다. 보라색 구간을 드래그해 원하는 위치에 배치하세요.');
  }
  async function save(){
    if(loading)throw Error('오른쪽 로스백을 불러오는 중입니다. 완료 후 이동하세요.');
    if(saving)throw Error('배치를 저장하는 중입니다. 완료 후 이동하세요.');
    if(rotationError)throw Error('회전 각도를 숫자로 입력하세요.');
    if(!dirty)return;saving=true;const serial=editSerial;update();
    try{
      const result=await gpsProject.save('map-merge',{source_dataset_id:gpsProject.current.project.stages['2'].dataset_id,clips:copy(clips)});
      if(editSerial===serial){clips=copy(result.project.map_merge_result.clips);dirty=false;}
      status('배치를 저장했습니다. 배치한 구간을 다음 단계에서 사용합니다. 기준 GPS는 배경으로만 표시합니다.');
    }catch(error){status(error.message);throw error;}finally{saving=false;update();}
  }
  function setTracks(pane,tracks){
    pane.tracks=tracks.map((t,i)=>({...t,color:palette[i%palette.length],visible:true,points:t.points.filter(p=>Number.isFinite(p.lat)&&Number.isFinite(p.lon)&&Math.abs(p.lat)<=90&&Math.abs(p.lon)<=180).map(project)}));
    legend(pane);fit(pane);update();
  }
  function legend(pane){
    const parent=$('gps-map-merge-'+pane.side+'-tracks');parent.replaceChildren();
    for(const t of pane.tracks){
      const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.checked=t.visible;check.setAttribute('aria-label',t.name+' 표시');
      check.onchange=()=>{t.visible=check.checked;if(pane.side==='right'&&!t.visible&&range?.track===t.name)range=null;draw(pane);update();};
      const text=document.createElement('span');text.style.color=t.color;text.textContent=` ${t.name} · ${t.points.length.toLocaleString()}점`;
      label.append(check,text);parent.append(label);
    }
    if(!pane.tracks.length)parent.textContent=pane.side==='left'?'2단계 GPS 기록 없음':'불러온 기록 없음';
  }
  const xy=(pane,p)=>[pane.width/2+(p.e-pane.e)*pane.scale,pane.height/2-(p.n-pane.n)*pane.scale];
  function summary(pane){
    const tracks=pane.tracks.filter(t=>t.visible),count=tracks.reduce((sum,t)=>sum+t.points.length,0);
    pane.info.textContent=tracks.length?`${tracks.length}개 기록 · ${count.toLocaleString()}점 · 북 ↑ / 동 →`:pane.tracks.length?'표시할 기록을 선택하세요.':pane.side==='left'?'2단계 GPS 기록 없음':'오른쪽 로스백을 선택하고 불러오세요.';
  }
  function draw(pane){
    if(!active())return;
    const ctx=pane.canvas.getContext('2d'),{width,height,scale}=pane;
    ctx.clearRect(0,0,width,height);drawGpsGrid(ctx,width,height,scale,pane.e,pane.n);
    let count=0;
    for(const t of pane.tracks){
      if(!t.visible)continue;count+=t.points.length;ctx.strokeStyle=t.color;ctx.fillStyle=t.color;ctx.lineWidth=1.3;ctx.beginPath();
      for(const [i,p] of t.points.entries()){const [x,y]=xy(pane,p);if(!i||p.break_before)ctx.moveTo(x,y);else ctx.lineTo(x,y);}ctx.stroke();
      for(const p of t.points){const [x,y]=xy(pane,p);if(x<0||x>width||y<0||y>height)continue;ctx.beginPath();ctx.arc(x,y,2.5,0,2*Math.PI);ctx.fill();}
      if(t.points.length){const [x,y]=xy(pane,t.points[0]),[ex,ey]=xy(pane,t.points.at(-1));ctx.lineWidth=2;ctx.beginPath();ctx.arc(x,y,5,0,2*Math.PI);ctx.stroke();ctx.strokeRect(ex-4,ey-4,8,8);}
    }
    if(pane.side==='right'&&range){
      const t=pane.tracks.find(t=>t.name===range.track&&t.visible),r=selectedRange();
      if(t){
        if(r){ctx.strokeStyle='#b94600';ctx.lineWidth=4;ctx.beginPath();for(let i=r.start;i<=r.end;i++){const [x,y]=xy(pane,t.points[i]);if(i===r.start||t.points[i].break_before)ctx.moveTo(x,y);else ctx.lineTo(x,y);}ctx.stroke();}
        for(const index of range.indices){const point=t.points[index];if(!point)continue;const [x,y]=xy(pane,point);ctx.strokeStyle='#b94600';ctx.lineWidth=3;ctx.beginPath();ctx.arc(x,y,8,0,Math.PI*2);ctx.stroke();ctx.font='12px system-ui';ctx.fillStyle='#b94600';ctx.fillText('#'+point.seq,x+10,y-10);}
      }
    }
    if(pane.side==='left'&&selectedClip){
      const t=pane.tracks.find(t=>t.clipId===selectedClip);if(t?.visible){ctx.strokeStyle='#ad2dba';ctx.lineWidth=4;ctx.beginPath();for(const [i,p] of t.points.entries()){const [x,y]=xy(pane,p);if(!i||p.break_before)ctx.moveTo(x,y);else ctx.lineTo(x,y);}ctx.stroke();}
    }
    drawGpsScale(ctx,width,height,scale);pane.canvas.dataset.pointCount=String(count);pane.canvas.dataset.trackCount=String(pane.tracks.length);summary(pane);
  }
  function resize(pane){
    const rect=pane.canvas.parentElement.getBoundingClientRect();if(rect.width<1||rect.height<1)return;
    const ratio=window.devicePixelRatio||1;pane.width=rect.width;pane.height=rect.height;
    pane.canvas.width=Math.round(rect.width*ratio);pane.canvas.height=Math.round(rect.height*ratio);pane.canvas.getContext('2d').setTransform(ratio,0,0,ratio,0,0);draw(pane);
  }
  function fit(pane){
    resize(pane);let minE=Infinity,maxE=-Infinity,minN=Infinity,maxN=-Infinity;
    for(const t of pane.tracks)if(t.visible)for(const p of t.points){minE=Math.min(minE,p.e);maxE=Math.max(maxE,p.e);minN=Math.min(minN,p.n);maxN=Math.max(maxN,p.n);}
    if(Number.isFinite(minE)){pane.e=(minE+maxE)/2;pane.n=(minN+maxN)/2;pane.scale=Math.max(.0001,Math.min(100000,Math.min(Math.max(20,pane.width-80)/Math.max(2,maxE-minE),Math.max(20,pane.height-140)/Math.max(2,maxN-minN))));}
    draw(pane);
  }
  function sameScale(){
    if(loading||!panes.every(hasVisiblePoints))return;
    // Fit both recordings, then use the wider view so neither is cropped.
    for(const pane of panes)fit(pane);
    const scale=Math.min(...panes.map(pane=>pane.scale));
    for(const pane of panes){pane.scale=scale;draw(pane);}
    status('양쪽 지도를 같은 스케일로 맞췄습니다.');
  }
  function showLeft(){
    if(initialized)return;
    const source=gpsProject.current?.project.stages['2'];origin=source?.raw.origin||null;
    clips=copy(gpsProject.current?.project.map_merge_result?.clips||[]);selectedClip=clips.at(-1)?.id||null;
    setTracks(panes[0],source?.raw.tracks.map((t,i)=>({...t,name:t.bag_path||source.bags?.[i]||t.name}))||[]);
    refreshClips(true);initialized=true;
  }
  function renderList(){
    const parent=$('gps-map-merge-list'),query=$('gps-map-merge-filter').value.trim().toLowerCase();parent.replaceChildren();
    for(const entry of entries.filter(e=>e.id.toLowerCase().includes(query))){
      const label=document.createElement('label');label.style.cssText='display:block;padding:5px 0;font-size:.75rem;overflow-wrap:anywhere';
      const check=document.createElement('input');check.type='checkbox';check.checked=selected.has(entry.id);check.disabled=!entry.supported;check.dataset.bagId=entry.id;check.setAttribute('aria-label',entry.id);
      check.onchange=()=>{check.checked?selected.add(entry.id):selected.delete(entry.id);update();};
      const detail=document.createElement('small');detail.style.cssText='display:block;margin-left:20px;color:#697b8e';detail.textContent=`GPS ${entry.gps_count??'?'}점 · ${entry.camera_count?'카메라 '+entry.camera_count.toLocaleString()+'프레임':'카메라 기록 없음'}`;
      label.append(check,' '+entry.id,detail);parent.append(label);
    }
    if(!parent.children.length)parent.textContent='표시할 로스백이 없습니다.';update();
  }
  async function request(action,body,signal){
    const response=await fetch('/api/gps/source/'+action,body?{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Control':'1'},body:JSON.stringify(body),signal}:{cache:'no-store',signal});
    const data=await response.json();if(!response.ok)throw Error(data.error||'로스백 서비스 요청 실패');return data;
  }
  async function catalog(){
    const v=version;catalogLoading=true;update();
    try{const data=await request('bags');if(v!==version)return;entries=data.bags;selected=new Set([...selected].filter(id=>entries.some(e=>e.id===id&&e.supported)));renderList();}
    catch(e){if(v===version)status(e.message);}
    finally{if(v===version){catalogLoading=false;update();}}
  }
  async function load(){
    if(loading||saving||!selected.size||!origin)return;
    const v=version,chosen=[...selected],tracks=[],warnings=[];loading=true;controller=new AbortController();update();
    try{
      for(const [index,bag] of chosen.entries()){
        if(v!==version)return;status(`오른쪽 로스백 불러오는 중 ${index+1}/${chosen.length} · ${bag}`);
        try{
          // Playback GPS is read separately from the step-2 raw export.
          const job=await request('replay-prepare',{bag},controller.signal);let result;
          do{
            await new Promise(resolve=>setTimeout(resolve,400));if(v!==version)return;
            result=await request('replay-status',null,controller.signal);if(v!==version)return;
            if(result.token!==job.token)throw Error('다른 재생 요청으로 변경되었습니다. 로스백을 다시 불러오세요.');
          }while(result.phase==='running');
          if(result.phase!=='done')throw Error(result.error||'로스백 읽기 실패');
          if(result.bag!==bag||!Array.isArray(result.gps)||!result.gps.length)throw Error('유효한 GPS 기록이 없습니다.');
          tracks.push({name:bag,points:result.gps.map((p,i)=>({...p,seq:i+1}))});
        }catch(e){if(v!==version)return;if(e.name==='AbortError')throw e;warnings.push(`${bag}: ${e.message}`);}
      }
      if(v!==version)return;
      if(tracks.length){range=null;setTracks(panes[1],tracks);loadedBags=tracks.map(t=>t.name);status(`불러오기 완료 · ${tracks.length}개 기록 · ${tracks.reduce((sum,t)=>sum+t.points.length,0).toLocaleString()}점${warnings.length?' · 제외 '+warnings.join(' / '):''}`);}
      else status('불러오기 실패 · '+warnings.join(' / '));
    }catch(e){if(v===version&&e.name!=='AbortError')status(e.message);}
    finally{if(v===version){loading=false;controller=null;update();}}
  }
  function reset(){
    version++;controller?.abort();controller=null;loading=false;saving=false;clips=[];clipboard=null;range=null;selectedClip=null;history=[];dirty=false;initialized=false;editSerial=0;rotationSession=null;rotationError=false;$('gps-map-merge-rotation').setCustomValidity('');catalogLoading=false;entries=[];selected.clear();loadedBags=[];origin=null;
    $('gps-map-merge-filter').value='';$('gps-map-merge-list').replaceChildren();status('오른쪽 로스백을 선택하세요.');
    for(const pane of panes){pane.tracks=[];pane.drag=null;legend(pane);draw(pane);}update();
  }
  for(const pane of panes){
    const canvas=pane.canvas,position=event=>{const r=canvas.getBoundingClientRect();return [event.clientX-r.left,event.clientY-r.top];};
    $('gps-map-merge-'+pane.side+'-fit').onclick=()=>fit(pane);
    canvas.addEventListener('contextmenu',e=>e.preventDefault());
    canvas.addEventListener('wheel',e=>{e.preventDefault();if(saving||pane.drag)return;const [x,y]=position(e),next=Math.max(.0001,Math.min(100000,pane.scale*Math.exp(-e.deltaY*.001)));pane.e+=(x-pane.width/2)/pane.scale-(x-pane.width/2)/next;pane.n-=(y-pane.height/2)/pane.scale-(y-pane.height/2)/next;pane.scale=next;draw(pane);},{passive:false});
    canvas.addEventListener('pointerdown',e=>{
      if(e.button>2||saving)return;const [x,y]=position(e),clip=e.button===0&&pane.side==='left'?hitClip(pane,x,y):null;
      rotationSession=null;rotationError=false;$('gps-map-merge-rotation').setCustomValidity('');if(clip)selectedClip=clip.id;
      pane.drag={x,y,lastX:x,lastY:y,e:pane.e,n:pane.n,moved:false,clip,offsetE:clip?.offset_e,offsetN:clip?.offset_n,button:e.button};canvas.setPointerCapture(e.pointerId);update();draw(pane);
    });
    canvas.addEventListener('pointermove',e=>{
      const [x,y]=position(e),d=pane.drag;
      if(d){
        const moved=Math.hypot(x-d.x,y-d.y)>4;
        if(moved&&!d.moved&&d.clip)remember();d.moved||=moved;
        if(d.moved){
          if(d.clip){d.clip.offset_e=d.offsetE+(x-d.x)/pane.scale;d.clip.offset_n=d.offsetN-(y-d.y)/pane.scale;dirty=true;editSerial++;refreshClips(false,false);}
          else{pane.e=d.e-(x-d.x)/pane.scale;pane.n=d.n+(y-d.y)/pane.scale;draw(pane);}
        }
        return;
      }
      const nearest=hitPoint(pane,x,y);
      if(nearest){const {t,p}=nearest;pane.info.textContent=t.clipId?`${t.name} · 원본 #${p.seq} · 배치 구간`: `${t.name} #${p.seq} · ${p.lat.toFixed(7)}, ${p.lon.toFixed(7)}`;}else summary(pane);
    });
    canvas.addEventListener('pointerup',e=>{
      const d=pane.drag;if(!d)return;pane.drag=null;
      if(d.moved){if(d.clip)status('구간을 이동했습니다. 배치 확정·저장을 누르거나 다음 단계로 진행하세요.');return;}
      if(d.button!==0)return;const [x,y]=position(e);
      if(pane.side==='right'){const hit=hitPoint(pane,x,y);if(hit)selectEndpoint(hit);}
      else if(!d.clip){selectedClip=null;draw(pane);update();}
    });
    for(const type of ['pointercancel','lostpointercapture'])canvas.addEventListener(type,()=>{pane.drag=null;});
    canvas.addEventListener('pointerleave',()=>summary(pane));
    new ResizeObserver(()=>resize(pane)).observe(canvas.parentElement);
  }
  $('gps-map-merge-rotation').oninput=e=>rotate(e.target.value,true);
  $('gps-map-merge-rotation-slider').oninput=e=>rotate(e.target.value,true);
  for(const id of ['rotation','rotation-slider']){$('gps-map-merge-'+id).onchange=()=>{rotationSession=null;};$('gps-map-merge-'+id).onblur=()=>{rotationSession=null;};}
  $('gps-map-merge-rotate-clockwise').onclick=()=>rotate((clips.find(c=>c.id===selectedClip)?.rotation_deg||0)-1);
  $('gps-map-merge-rotate-counterclockwise').onclick=()=>rotate((clips.find(c=>c.id===selectedClip)?.rotation_deg||0)+1);
  $('gps-map-merge-rotation-reset').onclick=()=>rotate(0);
  $('gps-map-merge-copy').onclick=copyRange;$('gps-map-merge-paste').onclick=paste;
  $('gps-map-merge-save').onclick=()=>save().catch(()=>{});
  $('gps-map-merge-next').onclick=()=>dashboardModes.setBuildStep('points');
  $('gps-map-merge-selection-clear').onclick=()=>{range=null;draw(panes[1]);update();};
  $('gps-map-merge-delete').onclick=()=>{if(loading||saving||!selectedClip)return;remember();clips=clips.filter(c=>c.id!==selectedClip);selectedClip=null;dirty=true;editSerial++;refreshClips();status('선택한 배치 구간을 삭제했습니다.');};
  $('gps-map-merge-undo').onclick=()=>{if(loading||saving||!history.length)return;const state=history.pop();clips=state.clips;selectedClip=state.selectedClip;rotationSession=null;rotationError=false;$('gps-map-merge-rotation').setCustomValidity('');dirty=true;editSerial++;refreshClips();status('직전 배치 변경을 되돌렸습니다.');};
  $('gps-map-merge-same-scale').onclick=sameScale;
  $('gps-map-merge-filter').oninput=renderList;$('gps-map-merge-refresh').onclick=catalog;
  $('gps-map-merge-all').onclick=()=>{const query=$('gps-map-merge-filter').value.trim().toLowerCase();for(const entry of entries)if(entry.supported&&entry.id.toLowerCase().includes(query))selected.add(entry.id);renderList();};
  $('gps-map-merge-clear').onclick=()=>{selected.clear();renderList();};$('gps-map-merge-load').onclick=load;
  window.addEventListener('dashboard:modechange',()=>{if(active()){showLeft();for(const pane of panes)resize(pane);catalog();}});
  window.addEventListener('gps:projectchange',reset);window.addEventListener('pagehide',reset);
  window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
  window.gpsMapMerge={get busy(){return loading||saving;},save};
})();
