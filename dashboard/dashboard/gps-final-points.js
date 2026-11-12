/* Explicit insertions into final samples; base samples retain their relative order. */
(() => {
 const $=id=>document.getElementById(id),canvas=$('gps-final-canvas');if(!canvas)return;
 const ctx=canvas.getContext('2d');let source=null,points=[],selected=null,pending=null,history=[],dirty=false,busy=false,generation=0;
 let width=1,height=1,scale=1,cx=0,cy=0,drag=null;
 const active=()=>dashboardModes.current==='map-build'&&dashboardModes.buildStep==='final-points';
 const message=s=>$('gps-final-status').textContent=s;
 const xy=p=>[width/2+(p.e-cx)*scale,height/2-(p.n-cy)*scale];
 const rad=Math.PI/180,e2=6.6943799901413165e-3;
 function xyz(lat,lon){lat*=rad;lon*=rad;const n=6378137/Math.sqrt(1-e2*Math.sin(lat)**2);return [n*Math.cos(lat)*Math.cos(lon),n*Math.cos(lat)*Math.sin(lon),n*(1-e2)*Math.sin(lat)];}
 function project(lat,lon){const [a,b]=source.origin.map(v=>v*rad),base=xyz(...source.origin),d=xyz(lat,lon).map((v,i)=>v-base[i]);return {lat,lon,e:-Math.sin(b)*d[0]+Math.cos(b)*d[1],n:-Math.sin(a)*Math.cos(b)*d[0]-Math.sin(a)*Math.sin(b)*d[1]+Math.cos(a)*d[2]};}
 function geographic(p){const [lat,lon]=source.origin,delta=1e-5,o=project(lat,lon),a=project(lat+delta,lon),b=project(lat,lon+delta),det=(a.e-o.e)*(b.n-o.n)-(b.e-o.e)*(a.n-o.n);let la=lat+delta*((p.e-o.e)*(b.n-o.n)-(b.e-o.e)*(p.n-o.n))/det,lo=lon+delta*((a.e-o.e)*(p.n-o.n)-(p.e-o.e)*(a.n-o.n))/det;
  for(let i=0;i<4;i++){const q=project(la,lo),u=project(la+delta,lo),v=project(la,lo+delta),d=(u.e-q.e)*(v.n-q.n)-(v.e-q.e)*(u.n-q.n);la+=delta*((p.e-q.e)*(v.n-q.n)-(v.e-q.e)*(p.n-q.n))/d;lo+=delta*((u.e-q.e)*(p.n-q.n)-(p.e-q.e)*(u.n-q.n))/d;}return {lat:la,lon:lo};}
 const remember=()=>{history.push(points.slice());if(history.length>30)history.shift();};
 function choose(index){selected=points[index]?.id??null;const p=points[index];if(!p)return;$('gps-final-index').value=index+1;if(p.manual){$('gps-final-lat').value=p.lat;$('gps-final-lon').value=p.lon;}update();draw();}
 function update(){const i=points.findIndex(p=>p.id===selected),p=points[i],manual=p?.manual;
  for(const id of ['gps-final-add','gps-final-save','gps-final-tool','gps-final-lat','gps-final-lon','gps-final-index'])$(id).disabled=busy||!source;
  $('gps-final-move').disabled=$('gps-final-remove').disabled=busy||!manual;
  $('gps-final-undo').disabled=busy||!history.length;
  $('gps-final-index').max=points.length+1;
  $('gps-final-selection').textContent=p?`선택 #${i+1} · ${manual?'추가점':'기존 점'} · ${p.lat.toFixed(8)}, ${p.lon.toFixed(8)}`:'선택한 웨이포인트 없음';
  $('gps-final-summary').textContent=`전체 ${points.length}점 · 추가 ${points.filter(p=>p.manual).length}점 · ${dirty?'변경 내용 미저장':'저장된 상태'}`;
  const list=$('gps-final-list');list.replaceChildren();points.forEach((p,i)=>{if(!p.manual)return;const button=document.createElement('button');button.textContent=`#${i+1} · ${p.lat.toFixed(7)}, ${p.lon.toFixed(7)}`;button.style.cssText='display:block;margin:4px 0';button.disabled=busy;button.onclick=()=>choose(i);list.append(button);});
 }
 function draw(){if(!active())return;ctx.clearRect(0,0,width,height);window.drawGpsGrid(ctx,width,height,scale,cx,cy);window.drawGpsReference(ctx,width,height,scale,cx,cy);
  ctx.strokeStyle='#4e83ba';ctx.lineWidth=1.2;ctx.beginPath();points.forEach((p,i)=>{const [x,y]=xy(p);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();
  const labelStride=Math.max(1,Math.ceil(28/(scale*.1)));
  for(const [i,p] of points.entries()){const [x,y]=xy(p);if(x<0||x>width||y<0||y>height)continue;const chosen=p.id===selected;ctx.fillStyle=chosen?'#d04d45':p.manual?'#d48a1e':'#4e83ba';ctx.beginPath();ctx.arc(x,y,chosen?6:p.manual?5:2,0,Math.PI*2);ctx.fill();if(p.manual||chosen||i%labelStride===0||i===points.length-1){ctx.font='11px system-ui';ctx.fillText(`#${i+1}`,x+6,y-6);}}
  if(pending){const [x,y]=xy(pending);ctx.strokeStyle='#d48a1e';ctx.beginPath();ctx.moveTo(x-7,y);ctx.lineTo(x+7,y);ctx.moveTo(x,y-7);ctx.lineTo(x,y+7);ctx.stroke();}
  window.drawGpsScale(ctx,width,height,scale);canvas.dataset.pointCount=String(points.length);canvas.dataset.addedCount=String(points.filter(p=>p.manual).length);canvas.dataset.selectedIndex=String(points.findIndex(p=>p.id===selected)+1);
 }
 function resize(){if(!active())return;const r=canvas.getBoundingClientRect(),dpr=devicePixelRatio||1;width=Math.max(1,r.width);height=Math.max(1,r.height);canvas.width=width*dpr;canvas.height=height*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);draw();}
 function fit(){if(!points.length)return;let a=Infinity,b=-Infinity,c=Infinity,d=-Infinity;for(const p of points.concat(window.gpsReferencePoints())){a=Math.min(a,p.e);b=Math.max(b,p.e);c=Math.min(c,p.n);d=Math.max(d,p.n);}cx=(a+b)/2;cy=(c+d)/2;scale=Math.max(.0001,Math.min(Math.max(20,width-120)/Math.max(1,b-a),Math.max(20,height-100)/Math.max(1,d-c)));draw();}
 async function load(){if(busy||!gpsProject.current)return;busy=true;source=null;points=[];selected=pending=null;dirty=false;history=[];update();const version=++generation;try{const data=await gpsProject.api('/api/gps/projects/final-waypoint-source?filename='+encodeURIComponent(gpsProject.current.filename));if(version!==generation)return;source=data;const additions=new Map((data.saved?.additions||[]).map(p=>[p.index,p]));points=data.final_points.map((p,i)=>({...p,id:additions.get(i+1)?.id??`base-${i}`,manual:additions.has(i+1)}));$('gps-final-index').value=points.length+1;message('위치와 최종 순번을 지정해 추가하세요.');resize();fit();}catch(e){message(e.message);}finally{busy=false;update();}}
 async function save(){if(busy)throw Error('최종 웨이포인트 처리 중입니다.');if(!source)return;busy=true;update();try{const additions=points.flatMap((p,i)=>p.manual?[{id:p.id,index:i+1,lat:p.lat,lon:p.lon}]:[]);await gpsProject.save(10.5,{source_digest:source.source_digest,additions});dirty=false;message('최종 웨이포인트 저장 완료');}finally{busy=false;update();}}
 const position=max=>{const n=Number($('gps-final-index').value);if(!Number.isInteger(n)||n<1||n>max)throw Error(`순번은 1~${max} 사이 정수로 입력하세요.`);return n-1;};
 const action=fn=>()=>{if(busy||!source)return;try{fn();update();draw();}catch(e){message(e.message);}};
 $('gps-final-add').onclick=action(()=>{const la=$('gps-final-lat').value.trim(),lo=$('gps-final-lon').value.trim(),lat=Number(la),lon=Number(lo),i=position(points.length+1);if(!la||!lo||!Number.isFinite(lat)||!Number.isFinite(lon)||Math.abs(lat)>90||Math.abs(lon)>180)throw Error('올바른 위도와 경도를 입력하세요.');if(points.filter(p=>p.manual).length>=10000)throw Error('추가점은 최대 10,000개입니다.');remember();const p={...project(lat,lon),id:'final-'+crypto.randomUUID(),manual:true};points.splice(i,0,p);selected=p.id;pending=null;dirty=true;$('gps-final-index').value=i+2;message(`#${i+1}에 추가했습니다. 최종 Map에 반영할 위치와 순서를 확인하세요.`);});
 $('gps-final-move').onclick=action(()=>{const i=points.findIndex(p=>p.id===selected);if(!points[i]?.manual)return;const target=position(points.length);remember();const [p]=points.splice(i,1);points.splice(target,0,p);dirty=true;message(`#${target+1}로 옮기고 전체 순번을 정리했습니다.`);});
 $('gps-final-remove').onclick=action(()=>{const i=points.findIndex(p=>p.id===selected);if(!points[i]?.manual)return;remember();points.splice(i,1);selected=null;dirty=true;});
 $('gps-final-undo').onclick=action(()=>{if(!history.length)return;points=history.pop();selected=null;dirty=true;});
 $('gps-final-save').onclick=()=>save().catch(e=>message(e.message));$('gps-final-fit').onclick=fit;
 const pos=e=>{const r=canvas.getBoundingClientRect();return [e.clientX-r.left,e.clientY-r.top];},world=e=>{const [x,y]=pos(e);return {e:cx+(x-width/2)/scale,n:cy-(y-height/2)/scale};};
 canvas.onpointerdown=e=>{if(busy||!source)return;if(e.button===1||e.button===2){const [x,y]=pos(e);drag={x,y,cx,cy};canvas.setPointerCapture(e.pointerId);}};
 canvas.onpointermove=e=>{if(!drag)return;const [x,y]=pos(e);cx=drag.cx-(x-drag.x)/scale;cy=drag.cy+(y-drag.y)/scale;draw();};
 canvas.onpointerup=canvas.onpointercancel=canvas.onlostpointercapture=()=>{drag=null;};canvas.oncontextmenu=e=>e.preventDefault();
 canvas.onclick=e=>{if(busy||!source||drag)return;if($('gps-final-tool').value==='select'){const [x,y]=pos(e);let best=-1,d=12;points.forEach((p,i)=>{const [a,b]=xy(p),distance=Math.hypot(x-a,y-b);if(distance<d){best=i;d=distance;}});if(best>=0)choose(best);return;}pending=world(e);const ll=geographic(pending);$('gps-final-lat').value=ll.lat.toFixed(10);$('gps-final-lon').value=ll.lon.toFixed(10);message('순번을 입력하고 지정 순번에 추가를 누르세요.');draw();};
 canvas.addEventListener('wheel',e=>{e.preventDefault();const p=world(e),[x,y]=pos(e);scale=Math.max(.0001,Math.min(1e6,scale*Math.exp(-e.deltaY*.001)));cx=p.e-(x-width/2)/scale;cy=p.n+(y-height/2)/scale;draw();},{passive:false});
 window.gpsFinalPoints={save,get busy(){return busy;}};
 window.addEventListener('gps:projectchange',()=>{generation++;source=null;points=[];history=[];dirty=false;selected=pending=drag=null;update();});
 window.addEventListener('dashboard:modechange',()=>{drag=null;if(active())load();});window.addEventListener('gps:backgroundchange',draw);
 window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});new ResizeObserver(resize).observe(canvas);
})();
