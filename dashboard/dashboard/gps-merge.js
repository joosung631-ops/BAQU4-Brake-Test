/* Explicit selection -> mean preview -> confirm. Immutable named stage files. */
(() => {
  const $=id=>document.getElementById(id),canvas=$('gps-merge-canvas');if(!canvas)return;
  const ctx=canvas.getContext('2d'),colors=['#1769c2','#d45a16','#168052','#8b43ad'];
  const contextLayer=document.createElement('canvas'),contextPaint=contextLayer.getContext('2d');
  let source=null,sourceFile='',tracks=[],ti=0,selected=new Set(),history=[],dirty=false,busy=false;
  let curveVersion=0;
  let width=1,height=1,scale=1,cx=0,cy=0,drag=null;
  const active=()=>window.dashboardModes?.current==='map-build'&&window.dashboardModes?.buildStep==='matching';
  const message=s=>$('gps-merge-status').textContent=gpsProject.formatStages(s);
  async function api(url,body){const r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Control':'1'},body:JSON.stringify(body)}:{});if(!r.ok)throw Error(await r.text());return r.json();}
  function project(p){const rad=Math.PI/180,a=source.origin[0]*rad;return {e:(p.lon-source.origin[1])*rad*6378137*Math.cos(a),n:(p.lat-source.origin[0])*rad*6378137};}
  const xy=p=>[width/2+(p.e-cx)*scale,height/2-(p.n-cy)*scale];
  function point(track,group){const map=track.original;const ps=group.map(s=>map.get(s));const p={lat:ps.reduce((a,p)=>a+p.lat,0)/ps.length,lon:ps.reduce((a,p)=>a+p.lon,0)/ps.length,seq:group[0],count:ps.length,segment:ps[0].segment};return {...p,...project(p)};}
  function points(t){return t.groups.map(g=>point(t,g));}
  function preview(){const t=tracks[ti];if(!t||selected.size<2)return null;return point(t,[...selected].sort((a,b)=>a-b).flatMap(i=>t.groups[i]));}
  function valid(){const t=tracks[ti],ids=[...selected].sort((a,b)=>a-b);return ids.length>=2&&ids.at(-1)-ids[0]+1===ids.length&&new Set(ids.map(i=>t.original.get(t.groups[i][0]).segment)).size===1;}
  function update(){
    const p=preview();$('gps-merge-confirm').disabled=busy||!valid();$('gps-merge-undo').disabled=busy||!history.length;
    $('gps-merge-save').disabled=busy||!source;
    $('gps-merge-track').disabled=busy;
    $('gps-merge-selection').textContent=`선택 ${selected.size}점`+(p?` (입력 ${p.count}점) · 평균: ${p.lat.toFixed(9)}, ${p.lon.toFixed(9)}`:'')+(selected.size>=2&&!valid()?' · 같은 기록에서 순서상 이어지는 점을 선택하세요.':'');
    $('gps-merge-dirty').textContent=dirty?'병합 결과 미저장':'확정한 변경 없음 또는 저장 완료';
    canvas.dataset.selectedCount=String(selected.size);canvas.dataset.preview=JSON.stringify(p);canvas.dataset.pointCount=String(tracks.reduce((a,t)=>a+t.groups.length,0));
  }
  async function refreshCurves(){
    const version=++curveVersion;tracks.forEach(t=>t.curves=[]);draw();
    if(!source||!$('gps-merge-smooth').checked)return;
    try{
      const result=await api('/api/gps/projects/merge-preview',{filename:window.gpsProject.current.filename,source_digest:sourceFile,tracks:tracks.map(t=>({id:t.id,groups:t.groups}))});
      if(version!==curveVersion)return;
      tracks.forEach(t=>t.curves=result.tracks.find(r=>r.id===t.id)?.curve_segments||[]);draw();
    }catch(e){if(version===curveVersion)message(`평활곡선 표시 실패: ${e.message}`);}
  }
  function draw(){
    if(!active())return;ctx.clearRect(0,0,width,height);window.drawGpsGrid(ctx,width,height,scale,cx,cy);window.drawGpsReference(ctx,width,height,scale,cx,cy,source?project:null);let linearCount=0,smoothCount=0;
    // Composite the other recordings once so overlapping points cannot accumulate opacity.
    if(contextLayer.width!==canvas.width||contextLayer.height!==canvas.height){contextLayer.width=canvas.width;contextLayer.height=canvas.height;}
    contextPaint.setTransform(1,0,0,1,0,0);contextPaint.clearRect(0,0,contextLayer.width,contextLayer.height);
    contextPaint.setTransform(ctx.getTransform());
    function drawTrack(paint,t,index){
      const ps=points(t);
      paint.strokeStyle=colors[index%colors.length];paint.lineWidth=1;
      if($('gps-merge-linear').checked){
        paint.beginPath();ps.forEach((p,i)=>{const [x,y]=xy(p);if(!i||p.segment!==ps[i-1].segment)paint.moveTo(x,y);else{paint.lineTo(x,y);linearCount++;}});paint.stroke();
      }
      if($('gps-merge-smooth').checked){
        paint.lineWidth=1;
        for(const segment of t.curves||[]){paint.beginPath();segment.forEach((p,i)=>{const [x,y]=xy(p);if(!i)paint.moveTo(x,y);else{paint.lineTo(x,y);smoothCount++;}});paint.stroke();}
      }
      ps.forEach((p,i)=>{const [x,y]=xy(p),chosen=index===ti&&selected.has(i);paint.fillStyle=chosen?'#ed3f83':colors[index%colors.length];paint.beginPath();paint.arc(x,y,chosen?7:5,0,Math.PI*2);paint.fill();
        if(p.count>1){paint.strokeStyle='#172b42';paint.lineWidth=1.5;paint.stroke();}
        if(i===0||i===ps.length-1){paint.fillStyle=colors[index%colors.length];paint.font='12px system-ui';paint.fillText(i===0?'시작':'끝',x+10,y-10);}
      });
    }
    tracks.forEach((t,index)=>{if(index!==ti)drawTrack(contextPaint,t,index);});
    ctx.save();ctx.setTransform(1,0,0,1,0,0);ctx.globalAlpha=.18;ctx.drawImage(contextLayer,0,0);ctx.restore();
    if(tracks[ti])drawTrack(ctx,tracks[ti],ti);
    const p=preview();if(p){const [x,y]=xy(p);ctx.strokeStyle='#841ed0';ctx.lineWidth=2;ctx.setLineDash([4,4]);for(const i of selected){const [px,py]=xy(point(tracks[ti],tracks[ti].groups[i]));ctx.beginPath();ctx.moveTo(px,py);ctx.lineTo(x,y);ctx.stroke();}ctx.setLineDash([]);ctx.fillStyle='#fff';ctx.beginPath();ctx.moveTo(x,y-10);ctx.lineTo(x+10,y);ctx.lineTo(x,y+10);ctx.lineTo(x-10,y);ctx.closePath();ctx.fill();ctx.stroke();ctx.fillStyle='#841ed0';ctx.font='bold 12px system-ui';ctx.fillText('평균 위치 (미리보기)',x+14,y+4);}
    if(drag&&!drag.pan){ctx.fillStyle='rgba(237,63,131,.12)';ctx.strokeStyle='#ed3f83';ctx.fillRect(drag.x,drag.y,drag.lastX-drag.x,drag.lastY-drag.y);ctx.strokeRect(drag.x,drag.y,drag.lastX-drag.x,drag.lastY-drag.y);}
    canvas.dataset.linearSegments=String(linearCount);canvas.dataset.smoothSegments=String(smoothCount);
    window.drawGpsScale(ctx,width,height,scale);
    update();
  }
  function fit(){const ps=tracks.flatMap(points).concat(window.gpsReferencePoints(source?project:null));if(!ps.length){draw();return;}let minE=Infinity,maxE=-Infinity,minN=Infinity,maxN=-Infinity;ps.forEach(p=>{minE=Math.min(minE,p.e);maxE=Math.max(maxE,p.e);minN=Math.min(minN,p.n);maxN=Math.max(maxN,p.n);});cx=(minE+maxE)/2;cy=(minN+maxN)/2;scale=Math.min((width-100)/Math.max(1,maxE-minE),(height-160)/Math.max(1,maxN-minN));draw();}
  function resize(){const r=canvas.getBoundingClientRect(),dpr=devicePixelRatio||1;width=Math.max(1,r.width);height=Math.max(1,r.height);canvas.width=width*dpr;canvas.height=height*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);draw();}
  async function load(){if(busy)return;busy=true;try{
    const project=window.gpsProject.current;if(!project)return;
    const result=await api('/api/gps/projects/merge-source?filename='+encodeURIComponent(project.filename));source=result.source;sourceFile=result.source_digest;
    tracks=source.tracks.map(t=>({id:t.id,name:t.name,original:new Map(t.points.map(p=>[p.seq,p])),groups:result.tracks?result.tracks.find(s=>s.id===t.id).groups.map(g=>[...g]):t.points.map(p=>[p.seq])}));
    ti=0;selected.clear();drag=null;history=[];dirty=false;$('gps-merge-track').replaceChildren(...tracks.map((t,i)=>new Option(t.name,String(i))));
    message('클릭 또는 드래그로 선택한 뒤 평균 위치를 확인하고 병합 확정을 누르세요.');resize();fit();refreshCurves();
  }catch(e){source=null;tracks=[];message(e.message);}finally{busy=false;update();}}
  const pos=e=>{const r=canvas.getBoundingClientRect();return [e.clientX-r.left,e.clientY-r.top];};
  canvas.addEventListener('pointerdown',e=>{if(busy||!source)return;const [x,y]=pos(e);drag={x,y,lastX:x,lastY:y,pan:e.button===1||e.button===2||$('gps-merge-gesture').value==='pan',cx,cy,remove:e.altKey};canvas.setPointerCapture(e.pointerId);e.preventDefault();});
  canvas.addEventListener('pointermove',e=>{if(!drag)return;[drag.lastX,drag.lastY]=pos(e);if(drag.pan){cx=drag.cx-(drag.lastX-drag.x)/scale;cy=drag.cy+(drag.lastY-drag.y)/scale;}draw();});
  canvas.addEventListener('pointerup',e=>{if(!drag)return;const d=drag;drag=null;const [x,y]=pos(e);if(!d.pan){const ps=points(tracks[ti]);if(Math.hypot(x-d.x,y-d.y)<4){let best=-1,dist=12;ps.forEach((p,i)=>{const [px,py]=xy(p),v=Math.hypot(px-x,py-y);if(v<dist){best=i;dist=v;}});if(best>=0){if(selected.has(best))selected.delete(best);else selected.add(best);}}else ps.forEach((p,i)=>{const [px,py]=xy(p);if(px>=Math.min(x,d.x)&&px<=Math.max(x,d.x)&&py>=Math.min(y,d.y)&&py<=Math.max(y,d.y)){if(d.remove)selected.delete(i);else selected.add(i);}});}draw();});
  function cancelDrag(){if(!drag)return;cx=drag.cx;cy=drag.cy;drag=null;draw();}
  canvas.addEventListener('pointercancel',cancelDrag);
  canvas.addEventListener('lostpointercapture',cancelDrag);
  window.addEventListener('keydown',e=>{
    if(e.key!=='Escape'||!active()||busy||drag||document.querySelector('dialog[open]'))return;
    if(selected.size){e.preventDefault();selected.clear();draw();}
  });
  canvas.oncontextmenu=e=>e.preventDefault();
  canvas.addEventListener('wheel',e=>{e.preventDefault();const [x,y]=pos(e),factor=Math.exp(-e.deltaY*.001);const e0=cx+(x-width/2)/scale,n0=cy-(y-height/2)/scale;scale=Math.max(.01,Math.min(1e6,scale*factor));cx=e0-(x-width/2)/scale;cy=n0+(y-height/2)/scale;draw();},{passive:false});
  $('gps-merge-confirm').onclick=()=>{if(!valid()||busy)return;history.push(tracks.map(t=>t.groups.map(g=>[...g])));const t=tracks[ti],ids=[...selected].sort((a,b)=>a-b),group=ids.flatMap(i=>t.groups[i]);t.groups.splice(ids[0],ids.length,group);selected.clear();drag=null;dirty=true;message(`입력 ${group.length}점을 평균 위치 1점으로 병합했습니다.`);refreshCurves();};
  $('gps-merge-undo').onclick=()=>{if(busy||!history.length)return;const last=history.pop();tracks.forEach((t,i)=>t.groups=last[i]);selected.clear();drag=null;dirty=true;refreshCurves();};
  $('gps-merge-linear').onchange=draw;
  $('gps-merge-smooth').onchange=()=>{if($('gps-merge-smooth').checked)refreshCurves();else{curveVersion++;draw();}};
  $('gps-merge-fit').onclick=fit;
  $('gps-merge-track').onchange=()=>{ti=Number($('gps-merge-track').value);selected.clear();drag=null;draw();};
  async function save(){if(busy)throw Error('병합 데이터를 처리 중입니다.');if(!source)return;busy=true;update();try{await window.gpsProject.save(5,{source_digest:sourceFile,tracks:tracks.map(t=>({id:t.id,groups:t.groups}))});dirty=false;message('5단계 결과를 현재 맵 파일에 저장했습니다.');}finally{busy=false;update();}}
  $('gps-merge-save').onclick=()=>save().catch(e=>message(e.message));window.gpsMerger={save,get busy(){return busy;}};
  window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
  window.addEventListener('gps:backgroundchange',draw);
  window.addEventListener('gps:projectchange',()=>{curveVersion++;source=null;tracks=[];dirty=false;selected.clear();drag=null;history=[];});
  window.addEventListener('dashboard:modechange',()=>{if(active())load();});
  new ResizeObserver(resize).observe(canvas);
})();
