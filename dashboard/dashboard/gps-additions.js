/* Add explicit WGS84 samples after noise removal; original samples stay intact. */
(() => {
  const $=id=>document.getElementById(id), canvas=$('gps-add-canvas');if(!canvas)return;
  const ctx=canvas.getContext('2d'),active=()=>dashboardModes.current==='map-build'&&dashboardModes.buildStep==='add-points';
  let tracks=[],origin=null,sourceDigest=null,loadedFile='',dirty=false,busy=false,loading=false,version=0;
  let ti=0,selected=null,anchor='auto',history=[],width=1,height=1,scale=1,cx=0,cy=0,drag=null;
  const say=text=>$('gps-add-status').textContent=gpsProject.formatStages(text), current=()=>tracks[ti];
  const xy=p=>[width/2+(p.e-cx)*scale,height/2-(p.n-cy)*scale];
  function basis(){
    const r=Math.PI/180,a=origin[0]*r,b=origin[1]*r,e2=6.6943799901413165e-3,N=6378137/Math.sqrt(1-e2*Math.sin(a)**2);
    return {base:[N*Math.cos(a)*Math.cos(b),N*Math.cos(a)*Math.sin(b),N*(1-e2)*Math.sin(a)],east:[-Math.sin(b),Math.cos(b),0],north:[-Math.sin(a)*Math.cos(b),-Math.sin(a)*Math.sin(b),Math.cos(a)],up:[Math.cos(a)*Math.cos(b),Math.cos(a)*Math.sin(b),Math.sin(a)]};
  }
  function project(p){
    const r=Math.PI/180,a=p.lat*r,b=p.lon*r,e2=6.6943799901413165e-3,N=6378137/Math.sqrt(1-e2*Math.sin(a)**2),v=basis();
    const d=[N*Math.cos(a)*Math.cos(b),N*Math.cos(a)*Math.sin(b),N*(1-e2)*Math.sin(a)].map((n,i)=>n-v.base[i]);
    return {...p,e:d.reduce((n,x,i)=>n+x*v.east[i],0),n:d.reduce((n,x,i)=>n+x*v.north[i],0)};
  }
  function geographic(e,n){
    const v=basis(),a=6378137,e2=6.6943799901413165e-3,inv=[1/a**2,1/a**2,1/(a*a*(1-e2))],q=v.base.map((x,i)=>x+e*v.east[i]+n*v.north[i]);
    const A=v.up.reduce((s,x,i)=>s+x*x*inv[i],0),B=2*q.reduce((s,x,i)=>s+x*v.up[i]*inv[i],0),C=q.reduce((s,x,i)=>s+x*x*inv[i],0)-1;
    const discriminant=B*B-4*A*C;if(discriminant<0)throw Error('현재 지도 범위 안에서 포인트를 추가하세요.');
    const u=-2*C/(B+Math.sqrt(discriminant)),p=q.map((x,i)=>x+u*v.up[i]);
    return {lat:Math.atan2(p[2],Math.hypot(p[0],p[1])*(1-e2))*180/Math.PI,lon:Math.atan2(p[1],p[0])*180/Math.PI};
  }
  function update(){
    const t=current(),point=t?.points.find(p=>p.key===selected),count=tracks.reduce((n,t)=>n+t.points.filter(p=>p.manual).length,0),blocked=busy||loading;
    $('gps-add-track').disabled=blocked||!tracks.length;
    for(const id of ['gps-add-anchor','gps-add-lat','gps-add-lon','gps-add-coordinate'])$(id).disabled=blocked||!t;
    $('gps-add-save').disabled=blocked||!sourceDigest;$('gps-add-delete').disabled=blocked||!point?.manual;
    $('gps-add-undo').disabled=blocked||!history.length;$('gps-add-reset').disabled=blocked||!count;
    $('gps-add-selection').textContent=point?`${point.manual?'추가한 점':'원본 점 #'+point.source_seq} · ${point.lat.toFixed(9)}, ${point.lon.toFixed(9)}`:'기준점을 클릭하거나 빈 곳을 클릭해 추가하세요.';
    $('gps-add-dirty').textContent=`추가 ${count.toLocaleString()}점 · ${dirty?'저장 전':'저장 완료 또는 변경 없음'}`;
    const options=[new Option('가까운 경로 사이에 자동 삽입','auto'),new Option('맨 앞에 추가','start'),new Option('맨 뒤에 추가','end')];
    if(point)options.push(new Option(`${point.manual?'선택한 추가 점':'선택한 원본 #'+point.source_seq} 뒤에 추가`,point.key));
    if(!options.some(o=>o.value===anchor))anchor='auto';$('gps-add-anchor').replaceChildren(...options);$('gps-add-anchor').value=anchor;
    canvas.dataset.pointCount=String(tracks.reduce((n,t)=>n+t.points.length,0));canvas.dataset.addedCount=String(count);
    canvas.dataset.selectedKey=selected||'';canvas.dataset.dirty=String(dirty);
    canvas.dataset.centerE=String(cx);canvas.dataset.centerN=String(cy);canvas.dataset.pixelsPerMeter=String(scale);
  }
  function draw(){
    if(!active())return;ctx.clearRect(0,0,width,height);drawGpsGrid(ctx,width,height,scale,cx,cy);window.drawGpsReference(ctx,width,height,scale,cx,cy);
    for(const [index,t] of tracks.entries()){
      ctx.globalAlpha=index===ti?1:.2;ctx.strokeStyle='#6892ba';ctx.lineWidth=1;ctx.beginPath();
      t.points.forEach((p,i)=>{const [x,y]=xy(p);if(!i||p.segment!==t.points[i-1].segment)ctx.moveTo(x,y);else ctx.lineTo(x,y);});ctx.stroke();
      for(const p of t.points){const [x,y]=xy(p);ctx.fillStyle=p.manual?'#e0791c':'#1769c2';ctx.beginPath();ctx.arc(x,y,p.manual?5:3,0,Math.PI*2);ctx.fill();if(index===ti&&p.key===selected){ctx.strokeStyle='#172b42';ctx.lineWidth=2;ctx.beginPath();ctx.arc(x,y,9,0,Math.PI*2);ctx.stroke();}}
    }
    ctx.globalAlpha=1;drawGpsScale(ctx,width,height,scale);update();
  }
  function resize(){const r=canvas.getBoundingClientRect(),dpr=devicePixelRatio||1;width=Math.max(1,r.width);height=Math.max(1,r.height);canvas.width=width*dpr;canvas.height=height*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);draw();}
  function fit(){let minE=Infinity,maxE=-Infinity,minN=Infinity,maxN=-Infinity;for(const t of tracks)for(const p of t.points){minE=Math.min(minE,p.e);maxE=Math.max(maxE,p.e);minN=Math.min(minN,p.n);maxN=Math.max(maxN,p.n);}for(const p of window.gpsReferencePoints()){minE=Math.min(minE,p.e);maxE=Math.max(maxE,p.e);minN=Math.min(minN,p.n);maxN=Math.max(maxN,p.n);}if(Number.isFinite(minE)){cx=(minE+maxE)/2;cy=(minN+maxN)/2;scale=Math.max(.01,Math.min(Math.max(20,width-100)/Math.max(2,maxE-minE),Math.max(20,height-150)/Math.max(2,maxN-minN)));}draw();}
  function nearest(p){
    const ps=current().points;if(!ps.length)return -1;
    let best=Infinity,index=0;
    for(let i=0;i<ps.length;i++){
      const a=ps[i],b=ps[i+1];let fraction=0,distance=(p.e-a.e)**2+(p.n-a.n)**2;
      if(b&&a.segment===b.segment){const dx=b.e-a.e,dy=b.n-a.n;fraction=((p.e-a.e)*dx+(p.n-a.n)*dy)/(dx*dx+dy*dy||1);const f=Math.max(0,Math.min(1,fraction));distance=(p.e-a.e-f*dx)**2+(p.n-a.n-f*dy)**2;}
      if(distance<best){best=distance;index=i===0&&fraction<0?-1:i;}
    }return index;
  }
  function changed(action){history.push(action);if(history.length>100)history.shift();dirty=true;draw();}
  function add(lat,lon){
    if(busy||loading||!current())return;
    if(!Number.isFinite(lat)||!Number.isFinite(lon)||Math.abs(lat)>90||Math.abs(lon)>180)throw Error('올바른 위도(-90~90)와 경도(-180~180)를 입력하세요.');
    if(tracks.reduce((n,t)=>n+t.points.filter(p=>p.manual).length,0)>=10000)throw Error('최대 10,000점까지 추가할 수 있습니다.');
    const ps=current().points,p=project({lat,lon,key:'manual-'+(crypto.randomUUID?.()||Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,'0')).join('')),manual:true,source_seq:null});
    const index=anchor==='start'?-1:anchor==='end'?ps.length-1:anchor==='auto'?nearest(p):ps.findIndex(p=>p.key===anchor);
    p.segment=index>=0?ps[index].segment:ps[0]?.segment||0;ps.splice(index+1,0,p);selected=p.key;
    if(anchor!=='auto')anchor=p.key;$('gps-add-lat').value=lat.toFixed(10);$('gps-add-lon').value=lon.toFixed(10);
    changed({type:'add',track:ti,key:p.key});say('포인트를 추가했습니다. 4단계 저장 후 다음 단계에 반영됩니다.');
  }
  const position=e=>{const r=canvas.getBoundingClientRect();return [e.clientX-r.left,e.clientY-r.top];};
  canvas.addEventListener('pointerdown',e=>{if(busy||loading||!current()||e.button>2)return;const [x,y]=position(e);drag={x,y,cx,cy,pan:e.button!==0};canvas.setPointerCapture(e.pointerId);e.preventDefault();});
  canvas.addEventListener('pointermove',e=>{if(!drag)return;const [x,y]=position(e);if(Math.hypot(x-drag.x,y-drag.y)>4)drag.pan=true;if(drag.pan){cx=drag.cx-(x-drag.x)/scale;cy=drag.cy+(y-drag.y)/scale;draw();}});
  canvas.addEventListener('pointerup',e=>{if(!drag)return;const d=drag;drag=null;if(d.pan)return;const [x,y]=position(e);let found=null,distance=12;for(const p of current().points){const [px,py]=xy(p),v=Math.hypot(px-x,py-y);if(v<distance){found=p;distance=v;}}if(found){selected=found.key;anchor=found.key;$('gps-add-lat').value=found.lat.toFixed(10);$('gps-add-lon').value=found.lon.toFixed(10);draw();}else try{const p=geographic(cx+(x-width/2)/scale,cy-(y-height/2)/scale);add(p.lat,p.lon);}catch(error){say(error.message);}});
  for(const event of ['pointercancel','lostpointercapture'])canvas.addEventListener(event,()=>{drag=null;});canvas.oncontextmenu=e=>e.preventDefault();
  canvas.addEventListener('wheel',e=>{e.preventDefault();const [x,y]=position(e),beforeE=cx+(x-width/2)/scale,beforeN=cy-(y-height/2)/scale;scale=Math.max(.0001,Math.min(1e6,scale*Math.exp(-e.deltaY*.001)));cx=beforeE-(x-width/2)/scale;cy=beforeN+(y-height/2)/scale;draw();},{passive:false});
  $('gps-add-coordinate').onclick=()=>{try{if(!$('gps-add-lat').value.trim()||!$('gps-add-lon').value.trim())throw Error('위도와 경도를 모두 입력하세요.');add(Number($('gps-add-lat').value),Number($('gps-add-lon').value));}catch(error){say(error.message);}};
  $('gps-add-track').onchange=()=>{ti=Number($('gps-add-track').value);selected=null;anchor='auto';draw();};$('gps-add-anchor').onchange=()=>{anchor=$('gps-add-anchor').value;};$('gps-add-fit').onclick=fit;
  $('gps-add-delete').onclick=()=>{const ps=current()?.points,index=ps?.findIndex(p=>p.key===selected);if(index==null||index<0||!ps[index].manual)return;const point=ps.splice(index,1)[0];selected=null;anchor='auto';changed({type:'delete',track:ti,index,point});};
  $('gps-add-reset').onclick=()=>{const removed=[];tracks.forEach((t,track)=>{t.points.forEach((point,index)=>{if(point.manual)removed.push({track,index,point});});t.points=t.points.filter(p=>!p.manual);});selected=null;anchor='auto';changed({type:'reset',removed});};
  $('gps-add-undo').onclick=()=>{const action=history.pop();if(!action)return;if(action.type==='add'){const t=tracks[action.track];t.points=t.points.filter(p=>p.key!==action.key);}else if(action.type==='delete')tracks[action.track].points.splice(action.index,0,action.point);else for(const p of action.removed)tracks[p.track].points.splice(p.index,0,p.point);selected=null;anchor='auto';dirty=true;draw();};
  async function load(){const request=++version;loading=true;sourceDigest=null;tracks=[];history=[];dirty=false;selected=null;anchor='auto';say('GPS 포인트를 불러오는 중…');update();try{const file=gpsProject.current?.filename;if(!file)return;const data=await gpsProject.api('/api/gps/projects/additions-source?filename='+encodeURIComponent(file));if(request!==version||!active())return;origin=data.origin;sourceDigest=data.source_digest;loadedFile=file;tracks=data.tracks.map(t=>({...t,points:t.points.map(project)}));ti=0;$('gps-add-track').replaceChildren(...tracks.map((t,i)=>new Option(t.name,String(i))));say('빈 곳을 클릭해 GPS 포인트를 추가하세요.');resize();fit();}catch(error){if(request===version)say(error.message);}finally{if(request===version){loading=false;update();}}}
  async function save(){if(busy||loading)throw Error('GPS 포인트를 처리 중입니다.');if(!sourceDigest||(!dirty&&gpsProject.current?.project.stages['4']))return;if(gpsProject.current?.filename!==loadedFile)throw Error('맵 파일이 변경되었습니다. 포인트 추가 화면을 다시 여세요.');busy=true;update();try{const additions=[];for(const t of tracks){let after=null;for(const p of t.points){if(p.manual)additions.push({id:p.key,track_id:t.id,after,lat:p.lat,lon:p.lon});after=p.key;}}const result=await gpsProject.save(4,{source_digest:sourceDigest,additions});loadedFile=result.filename;dirty=false;say('4단계 GPS 포인트 추가 결과를 저장했습니다.');}finally{busy=false;update();}}
  $('gps-add-save').onclick=()=>save().catch(error=>say(error.message));window.gpsAdditions={save,get busy(){return busy||loading;}};
  window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
  window.addEventListener('gps:backgroundchange',draw);
  window.addEventListener('gps:projectchange',()=>{version++;loading=false;tracks=[];sourceDigest=null;dirty=false;history=[];selected=null;drag=null;});
  window.addEventListener('dashboard:modechange',()=>{if(active())load();else{version++;loading=false;drag=null;}});
  new ResizeObserver(resize).observe(canvas);
})();
