/* Cross-recording selection and explicit fusion of stage 4 points. */
(() => {
 const $=id=>document.getElementById(id),canvas=$('gps-fusion-canvas');if(!canvas)return;
 const ctx=canvas.getContext('2d'),palette=['#1769c2','#d45a16','#168052','#8b43ad','#ac3970','#65710c'];
 let source=[],known=new Map(),groups=[],origin=[0,0],sourceDigest='',selected=new Set(),history=[],dirty=false,busy=false,generation=0;
 let curves=[],curveVersion=0;
 let width=1,height=1,scale=1,cx=0,cy=0,drag=null;
 const active=()=>window.dashboardModes?.current==='map-build'&&window.dashboardModes?.buildStep==='fusion';
 const message=s=>$('gps-fusion-status').textContent=gpsProject.formatStages(s);
 function project(lat,lon){const rad=Math.PI/180,a=origin[0]*rad,b=origin[1]*rad;
   const xyz=(lt,ln)=>{lt*=rad;ln*=rad;const e2=6.6943799901413165e-3,n=6378137/Math.sqrt(1-e2*Math.sin(lt)**2);return [n*Math.cos(lt)*Math.cos(ln),n*Math.cos(lt)*Math.sin(ln),n*(1-e2)*Math.sin(lt)];};
   const base=xyz(...origin),d=xyz(lat,lon).map((v,i)=>v-base[i]);return {e:-Math.sin(b)*d[0]+Math.cos(b)*d[1],n:-Math.sin(a)*Math.cos(b)*d[0]-Math.sin(a)*Math.sin(b)*d[1]+Math.cos(a)*d[2]};
 }
 function point(group){const ps=group.map(id=>known.get(id)),lat=ps.reduce((v,p)=>v+p.lat,0)/ps.length,lon=ps.reduce((v,p)=>v+p.lon,0)/ps.length;
   const ids=new Set(ps.map(p=>p.track_id));return {lat,lon,...project(lat,lon),count:ps.length,color:ids.size>1?'#8b43ad':palette[ps[0].color_index%palette.length],tracks:ids.size};}
 const xy=p=>[width/2+(p.e-cx)*scale,height/2-(p.n-cy)*scale];
 function preview(){return selected.size>=2?point([...selected].sort((a,b)=>a-b).flatMap(i=>groups[i])):null;}
 function update(){
   $('gps-fusion-manual').disabled=busy||selected.size<2;$('gps-fusion-auto').disabled=busy||selected.size<2;
   $('gps-fusion-undo').disabled=busy||!history.length;$('gps-fusion-save').disabled=busy||!sourceDigest;$('gps-fusion-radius').disabled=busy;
   const p=preview();$('gps-fusion-selection').textContent=`전체 ${groups.length}점 · 선택 ${selected.size}점`+(p?` · ${p.tracks}개 기록 · 평균 ${p.lat.toFixed(9)}, ${p.lon.toFixed(9)}`:'');
   $('gps-fusion-dirty').textContent=dirty?'변경 내용 미저장':'저장된 상태';canvas.dataset.pointCount=String(groups.length);canvas.dataset.selectedCount=String(selected.size);canvas.dataset.preview=JSON.stringify(p);
 }
 async function refreshCurves(){
   const version=++curveVersion;curves=[];draw();if(!sourceDigest||!$('gps-fusion-smooth').checked)return;
   try{const result=await window.gpsProject.api('/api/gps/projects/fusion-preview',{filename:window.gpsProject.current.filename,source_digest:sourceDigest,groups});if(version!==curveVersion)return;curves=result.tracks;draw();}
   catch(e){if(version===curveVersion)message(`평활곡선 표시 실패: ${e.message}`);}
 }
 function draw(){if(!active())return;ctx.clearRect(0,0,width,height);window.drawGpsGrid(ctx,width,height,scale,cx,cy);window.drawGpsReference(ctx,width,height,scale,cx,cy);
   let linearCount=0;
   if($('gps-fusion-linear').checked){
     // Follow each recording's own original order through the current merged positions.
     const positions=groups.map(point),membership=new Map();groups.forEach((g,i)=>g.forEach(id=>membership.set(id,i)));
     ctx.save();ctx.globalAlpha=.45;ctx.lineWidth=1;let previous=null,previousGroup=null;
     for(const original of source){
       const index=membership.get(original.id),p=positions[index],[x,y]=xy(p);
       if(!previous||original.track_id!==previous.track_id){if(previous)ctx.stroke();ctx.beginPath();ctx.strokeStyle=palette[original.color_index%palette.length];ctx.moveTo(x,y);}
       else if(original.segment!==previous.segment)ctx.moveTo(x,y);
       else if(index!==previousGroup){ctx.lineTo(x,y);linearCount++;}
       previous=original;previousGroup=index;
     }
     if(previous)ctx.stroke();ctx.restore();
   }
   let smoothCount=0;
   if($('gps-fusion-smooth').checked){
     ctx.save();ctx.globalAlpha=.45;ctx.lineWidth=1;
     for(const t of curves){ctx.strokeStyle=palette[t.color_index%palette.length];for(const segment of t.curve_segments){ctx.beginPath();segment.forEach((p,i)=>{const [x,y]=xy(p);if(!i)ctx.moveTo(x,y);else{ctx.lineTo(x,y);smoothCount++;}});ctx.stroke();}}
     ctx.restore();
   }
   canvas.dataset.smoothSegments=String(smoothCount);
   canvas.dataset.linearSegments=String(linearCount);
   groups.forEach((g,i)=>{const p=point(g),[x,y]=xy(p);ctx.fillStyle=selected.has(i)?'#ed3f83':p.color;ctx.beginPath();ctx.arc(x,y,selected.has(i)?7:5,0,Math.PI*2);ctx.fill();if(g.length>1){ctx.strokeStyle='#253b52';ctx.lineWidth=1.5;ctx.stroke();}});
   const p=preview();if(p){const [x,y]=xy(p);ctx.strokeStyle='#841ed0';ctx.lineWidth=2;ctx.setLineDash([4,4]);for(const i of selected){const [px,py]=xy(point(groups[i]));ctx.beginPath();ctx.moveTo(px,py);ctx.lineTo(x,y);ctx.stroke();}ctx.setLineDash([]);ctx.beginPath();ctx.moveTo(x,y-10);ctx.lineTo(x+10,y);ctx.lineTo(x,y+10);ctx.lineTo(x-10,y);ctx.closePath();ctx.stroke();}
   if(drag&&!drag.pan){ctx.fillStyle='rgba(237,63,131,.12)';ctx.strokeStyle='#ed3f83';ctx.fillRect(drag.x,drag.y,drag.lastX-drag.x,drag.lastY-drag.y);ctx.strokeRect(drag.x,drag.y,drag.lastX-drag.x,drag.lastY-drag.y);}
   window.drawGpsScale(ctx,width,height,scale);update();
 }
 function fit(){if(!groups.length){draw();return;}const ps=groups.map(point).concat(window.gpsReferencePoints());let a=Infinity,b=-Infinity,c=Infinity,d=-Infinity;for(const p of ps){a=Math.min(a,p.e);b=Math.max(b,p.e);c=Math.min(c,p.n);d=Math.max(d,p.n);}cx=(a+b)/2;cy=(c+d)/2;scale=Math.max(.0001,Math.min(Math.max(20,width-100)/Math.max(1,b-a),Math.max(20,height-150)/Math.max(1,d-c)));draw();}
 function resize(){if(!active())return;const r=canvas.getBoundingClientRect(),dpr=devicePixelRatio||1;width=Math.max(1,r.width);height=Math.max(1,r.height);canvas.width=width*dpr;canvas.height=height*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);draw();}
 async function load(){if(busy)return;busy=true;const version=++generation;update();try{
   const result=await window.gpsProject.api('/api/gps/projects/fusion-source?filename='+encodeURIComponent(window.gpsProject.current.filename));if(version!==generation)return;
   source=result.points;known=new Map(source.map(p=>[p.id,p]));origin=result.origin;sourceDigest=result.source_digest;
   groups=result.saved?result.saved.groups.map(g=>[...g]):source.map(p=>[p.id]);$('gps-fusion-radius').value=result.saved?.radius_m??.5;
   selected.clear();history=[];dirty=false;drag=null;
   const names=new Map(source.map(p=>[p.track_id,p]));$('gps-fusion-legend').replaceChildren(...[...names.values()].map(p=>{const el=document.createElement('div');el.style.color=palette[p.color_index%palette.length];el.textContent=`● ${p.track_name}`;return el;}));
   message('모든 로스백에서 점을 선택해 수동 또는 자동 병합하세요.');resize();fit();refreshCurves();
 }catch(e){message(e.message);}finally{busy=false;update();}}
 const pos=e=>{const r=canvas.getBoundingClientRect();return [e.clientX-r.left,e.clientY-r.top];};
 canvas.addEventListener('pointerdown',e=>{if(busy||!sourceDigest)return;const [x,y]=pos(e);drag={x,y,lastX:x,lastY:y,cx,cy,pan:e.button===1||e.button===2,add:e.shiftKey};canvas.setPointerCapture(e.pointerId);e.preventDefault();});
 canvas.addEventListener('pointermove',e=>{if(!drag)return;[drag.lastX,drag.lastY]=pos(e);if(drag.pan){cx=drag.cx-(drag.lastX-drag.x)/scale;cy=drag.cy+(drag.lastY-drag.y)/scale;}draw();});
 canvas.addEventListener('pointerup',e=>{if(!drag)return;const d=drag;drag=null;const [x,y]=pos(e);if(!d.pan){
   if(Math.hypot(x-d.x,y-d.y)<4){let best=-1,dist=12;groups.forEach((g,i)=>{const [px,py]=xy(point(g)),v=Math.hypot(x-px,y-py);if(v<dist){best=i;dist=v;}});if(best>=0){if(selected.has(best))selected.delete(best);else selected.add(best);}}
   else{if(!d.add&&!e.shiftKey)selected.clear();groups.forEach((g,i)=>{const [px,py]=xy(point(g));if(px>=Math.min(x,d.x)&&px<=Math.max(x,d.x)&&py>=Math.min(y,d.y)&&py<=Math.max(y,d.y))selected.add(i);});}
 }draw();});
 canvas.oncontextmenu=e=>e.preventDefault();for(const event of ['pointercancel','lostpointercapture'])canvas.addEventListener(event,()=>{drag=null;draw();});
 canvas.addEventListener('wheel',e=>{e.preventDefault();const [x,y]=pos(e),pe=cx+(x-width/2)/scale,pn=cy-(y-height/2)/scale;scale=Math.max(.0001,Math.min(1e6,scale*Math.exp(-e.deltaY*.001)));cx=pe-(x-width/2)/scale;cy=pn+(y-height/2)/scale;draw();},{passive:false});
 window.addEventListener('keydown',e=>{if(e.key==='Escape'&&active()&&!busy&&!drag&&!document.querySelector('dialog[open]')){e.preventDefault();selected.clear();draw();}});
 function remember(){history.push(groups.map(g=>[...g]));}
 function commit(next){remember();groups=next;selected.clear();dirty=true;refreshCurves();}
 $('gps-fusion-manual').onclick=()=>{if(busy||selected.size<2)return;const ids=[...selected].sort((a,b)=>a-b),merged=ids.flatMap(i=>groups[i]),next=[];groups.forEach((g,i)=>{if(i===ids[0])next.push(merged);else if(!selected.has(i))next.push(g);});commit(next);message(`${ids.length}점을 평균 위치 1점으로 수동 병합했습니다.`);};
 $('gps-fusion-auto').onclick=async()=>{if(busy||selected.size<2)return;const radius=Number($('gps-fusion-radius').value);if(!Number.isFinite(radius)||radius<.000001){message('자동 병합 거리를 0.000001m 이상으로 입력하세요.');return;}
   busy=true;update();const count=groups.length;try{const result=await window.gpsProject.api('/api/gps/projects/fusion-auto',{filename:window.gpsProject.current.filename,source_digest:sourceDigest,groups,selected:[...selected],radius_m:radius});if(result.groups.length<count){commit(result.groups);message(`자동 병합 완료 · ${count}점 → ${groups.length}점`);}else message('선택한 점 중 입력 거리 안에서 병합할 점이 없습니다.');}catch(e){message(e.message);}finally{busy=false;update();}};
 $('gps-fusion-undo').onclick=()=>{if(busy||!history.length)return;groups=history.pop();selected.clear();dirty=true;message('이전 병합 상태로 되돌렸습니다.');refreshCurves();};
 $('gps-fusion-linear').onchange=draw;
 $('gps-fusion-smooth').onchange=()=>{if($('gps-fusion-smooth').checked)refreshCurves();else{curveVersion++;draw();}};
 $('gps-fusion-radius').onchange=()=>{if(sourceDigest){dirty=true;update();}};$('gps-fusion-fit').onclick=fit;
 async function save(){if(busy)throw Error('6단계 처리 중입니다. 잠시 기다려주세요.');if(!sourceDigest)return;busy=true;update();try{await window.gpsProject.save(6,{source_digest:sourceDigest,groups,radius_m:Number($('gps-fusion-radius').value)});dirty=false;message('6단계 결과를 저장했습니다.');}finally{busy=false;update();}}
 $('gps-fusion-save').onclick=()=>save().catch(e=>message(e.message));window.gpsFusion={save,get busy(){return busy;}};
 window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
 window.addEventListener('gps:backgroundchange',draw);
 window.addEventListener('gps:projectchange',()=>{generation++;curveVersion++;curves=[];source=[];known.clear();groups=[];sourceDigest='';dirty=false;selected.clear();history=[];drag=null;});
 window.addEventListener('dashboard:modechange',()=>{if(active())load();});new ResizeObserver(resize).observe(canvas);
})();
