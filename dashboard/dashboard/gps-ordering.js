/* Reference-curve ordering with explicit manual insertion. */
(() => {
 const $=id=>document.getElementById(id),canvas=$('gps-order-canvas');if(!canvas)return;
 const ctx=canvas.getContext('2d');let points=[],references=[],sourceDigest='',result=null,order=[],selected=null,selection=new Set(),history=[],busy=false,dirty=false,generation=0;
 let width=1,height=1,scale=1,cx=0,cy=0,drag=null;
 const active=()=>window.dashboardModes?.current==='map-build'&&window.dashboardModes?.buildStep==='ordering';
 const message=s=>$('gps-order-status').textContent=gpsProject.formatStages(s);
 const xy=p=>[width/2+(p.e-cx)*scale,height/2-(p.n-cy)*scale];
 const reference=()=>references.find(t=>t.id===$('gps-order-reference').value);
 const ready=()=>result&&result.reference_id===$('gps-order-reference').value&&result.max_distance_m===Number($('gps-order-distance').value);
 function update(){
   const valid=!!ready(),rank=selected===null?-1:order.indexOf(selected),maximum=order.length+(rank<0?1:0);
   $('gps-order-auto').disabled=busy||!references.length||!sourceDigest;
   $('gps-order-reference').disabled=busy;$('gps-order-distance').disabled=busy;
   $('gps-order-insert').disabled=busy||!valid||selected===null;$('gps-order-index').disabled=busy||!valid||selected===null;$('gps-order-index').max=String(maximum);
   $('gps-order-remove').disabled=busy||!valid||!order.some(i=>selection.has(i));$('gps-order-undo').disabled=busy||!history.length;$('gps-order-save').disabled=busy||!valid;
   $('gps-order-summary').textContent=valid?`전체 ${points.length}점 · 순서 지정 ${order.length}점 · 미매칭 ${points.length-order.length}점`:`전체 ${points.length}점 · 자동 순서 매칭을 실행하세요.`;
   const match=valid&&selected!==null?result.matches[selected]:null;
   $('gps-order-selection').textContent=selection.size>1?`선택 ${selection.size}점 · 매칭 ${valid?order.filter(i=>selection.has(i)).length:0}점`:selected===null?'GPS 점을 선택하세요.':`선택 점 #${selected+1} · ${valid&&rank>=0?`현재 순서 ${rank+1}`:'미매칭'}${match?` · 기준선 최단 거리 ${match.distance_m.toFixed(3)} m`:''}`;
   $('gps-order-dirty').textContent=dirty?'변경 내용 미저장':'저장된 상태';
   canvas.dataset.pointCount=String(points.length);canvas.dataset.order=JSON.stringify(valid?order:[]);canvas.dataset.selectedPoint=selected===null?'':String(selected);canvas.dataset.selectedPoints=JSON.stringify([...selection]);
 }
 function draw(){if(!active())return;ctx.clearRect(0,0,width,height);window.drawGpsGrid(ctx,width,height,scale,cx,cy);window.drawGpsReference(ctx,width,height,scale,cx,cy);const valid=!!ready();
   if($('gps-order-reference-line').checked){ctx.strokeStyle='#527faa';ctx.lineWidth=1;for(const segment of reference()?.curve_segments||[]){ctx.beginPath();segment.forEach((p,i)=>{const [x,y]=xy(p);if(!i)ctx.moveTo(x,y);else ctx.lineTo(x,y);});ctx.stroke();}}
   if(valid&&$('gps-order-result-line').checked){ctx.strokeStyle='#26926b';ctx.lineWidth=1;for(let i=1;i<order.length;i++){
     const ai=order[i-1],bi=order[i];if(result.matches[ai].segment_index!==result.matches[bi].segment_index)continue;
     const [x,y]=xy(points[ai]),[u,v]=xy(points[bi]);ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(u,v);ctx.stroke();
     if(Math.hypot(u-x,v-y)>25){const a=Math.atan2(v-y,u-x),mx=(x+u)/2,my=(y+v)/2;ctx.beginPath();ctx.moveTo(mx-6*Math.cos(a-.5),my-6*Math.sin(a-.5));ctx.lineTo(mx,my);ctx.lineTo(mx-6*Math.cos(a+.5),my-6*Math.sin(a+.5));ctx.stroke();}
   }}
   const ranks=new Map((valid?order:[]).map((p,i)=>[p,i]));ctx.font='10px system-ui';ctx.textBaseline='alphabetic';
   points.forEach((p,i)=>{const [x,y]=xy(p),rank=ranks.get(i);ctx.fillStyle=rank===undefined?'#a1a9b2':`hsl(${220-220*rank/Math.max(1,order.length-1)},70%,43%)`;ctx.beginPath();ctx.arc(x,y,5,0,Math.PI*2);ctx.fill();if(rank!==undefined){ctx.fillStyle='#243d56';ctx.fillText(String(rank+1),x+7,y-7);}});
   for(const i of selection){const [x,y]=xy(points[i]);ctx.strokeStyle='#cf387e';ctx.lineWidth=2;ctx.beginPath();ctx.arc(x,y,10,0,Math.PI*2);ctx.stroke();if(valid&&selection.size===1){const [u,v]=xy(result.matches[i]);ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(u,v);ctx.stroke();ctx.setLineDash([]);}}
   if(drag?.mode==='select'&&drag.moved){ctx.fillStyle='rgba(207,56,126,.12)';ctx.strokeStyle='#cf387e';ctx.lineWidth=1;ctx.fillRect(drag.x,drag.y,drag.endX-drag.x,drag.endY-drag.y);ctx.strokeRect(drag.x,drag.y,drag.endX-drag.x,drag.endY-drag.y);}
   canvas.dataset.labelCount=String(ranks.size);window.drawGpsScale(ctx,width,height,scale);update();
 }
 function fit(){const all=[...points,...(reference()?.curve_segments||[]).flat()].concat(window.gpsReferencePoints());if(!all.length){draw();return;}let a=Infinity,b=-Infinity,c=Infinity,d=-Infinity;for(const p of all){a=Math.min(a,p.e);b=Math.max(b,p.e);c=Math.min(c,p.n);d=Math.max(d,p.n);}cx=(a+b)/2;cy=(c+d)/2;scale=Math.max(.0001,Math.min(Math.max(20,width-120)/Math.max(1,b-a),Math.max(20,height-150)/Math.max(1,d-c)));draw();}
 function resize(){if(!active())return;const r=canvas.getBoundingClientRect(),dpr=devicePixelRatio||1;width=Math.max(1,r.width);height=Math.max(1,r.height);canvas.width=width*dpr;canvas.height=height*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);draw();}
 async function load(){if(busy)return;busy=true;update();const version=++generation;try{
   const data=await window.gpsProject.api('/api/gps/projects/order-source?filename='+encodeURIComponent(window.gpsProject.current.filename));if(version!==generation)return;
   points=data.points;references=data.references;sourceDigest=data.source_digest;
   $('gps-order-reference').replaceChildren(...references.map(t=>{const option=new Option(t.name,t.id);option.disabled=!t.curve_segments.some(s=>s.length);return option;}));
   result=data.saved;order=result?[...result.order]:[];selected=null;selection.clear();history=[];dirty=false;drag=null;
   if(result){$('gps-order-reference').value=result.reference_id;$('gps-order-distance').value=result.max_distance_m;}else{$('gps-order-reference').value=references.find(t=>t.curve_segments.some(s=>s.length))?.id||'';$('gps-order-distance').value=1;}
   message(result?'저장된 순서 매칭을 불러왔습니다.':'기준 로스백과 거리를 선택한 뒤 자동 순서 매칭을 누르세요.');resize();fit();
 }catch(e){message(e.message);}finally{busy=false;update();}}
 function remember(){history.push({result,order:[...order],reference:$('gps-order-reference').value,distance:$('gps-order-distance').value});}
 $('gps-order-auto').onclick=async()=>{if(busy||!sourceDigest)return;const radius=Number($('gps-order-distance').value);if(!Number.isFinite(radius)||radius<=0){message('매칭 거리는 0보다 큰 값으로 입력하세요.');return;}busy=true;update();message('기준 평활선과 최단 거리를 계산 중입니다…');
   try{const data=await window.gpsProject.api('/api/gps/projects/order-auto',{filename:window.gpsProject.current.filename,source_digest:sourceDigest,reference_id:$('gps-order-reference').value,max_distance_m:radius});remember();result=data;order=[...data.auto_order];dirty=true;message(`자동 순서 매칭 완료 · ${order.length}점에 1번부터 순서를 부여했습니다.`);draw();}catch(e){message(e.message);}finally{busy=false;update();}};
 function select(indices){selection=new Set(indices);selected=selection.size===1?[...selection][0]:null;if(selected!==null){const rank=order.indexOf(selected);$('gps-order-index').value=rank>=0?rank+1:order.length+1;}draw();}
 function choose(i){selection=new Set([i]);selected=i;const rank=order.indexOf(i);$('gps-order-index').value=rank>=0?rank+1:order.length+1;draw();}
 $('gps-order-insert').onclick=()=>{if(busy||!ready()||selected===null)return;const number=Number($('gps-order-index').value),remaining=order.filter(i=>i!==selected);if(!Number.isInteger(number)||number<1||number>remaining.length+1){message(`순서는 1~${remaining.length+1} 사이 정수로 입력하세요.`);return;}remember();remaining.splice(number-1,0,selected);order=remaining;dirty=true;message(`${number}번 위치에 삽입하고 전체 순번을 정리했습니다.`);draw();};
 $('gps-order-remove').onclick=()=>{if(busy||!ready())return;const count=order.filter(i=>selection.has(i)).length;if(!count)return;remember();order=order.filter(i=>!selection.has(i));dirty=true;message(`선택한 ${count}점을 미매칭으로 옮기고 전체 순번을 정리했습니다.`);draw();};
 $('gps-order-undo').onclick=()=>{if(busy||!history.length)return;const s=history.pop();result=s.result;order=s.order;$('gps-order-reference').value=s.reference;$('gps-order-distance').value=s.distance;dirty=true;if(selected!==null)choose(selected);message('이전 순서 매칭 상태로 되돌렸습니다.');draw();};
 const changed=()=>{if(result)dirty=true;message('설정을 확인한 뒤 자동 순서 매칭을 실행하세요.');draw();};$('gps-order-reference').onchange=()=>{changed();fit();};$('gps-order-distance').onchange=changed;
 $('gps-order-reference-line').onchange=draw;$('gps-order-result-line').onchange=draw;$('gps-order-fit').onclick=fit;
 const pos=e=>{const r=canvas.getBoundingClientRect();return [e.clientX-r.left,e.clientY-r.top];};
 canvas.addEventListener('pointerdown',e=>{if(busy||drag||![0,1,2].includes(e.button))return;const [x,y]=pos(e);drag={x,y,endX:x,endY:y,cx,cy,mode:e.button===0?'select':'pan',moved:false};canvas.setPointerCapture(e.pointerId);});
 canvas.addEventListener('pointermove',e=>{if(!drag)return;const [x,y]=pos(e);drag.endX=x;drag.endY=y;drag.moved||=Math.hypot(x-drag.x,y-drag.y)>4;if(drag.moved){if(drag.mode==='pan'){cx=drag.cx-(x-drag.x)/scale;cy=drag.cy+(y-drag.y)/scale;}draw();}});
 canvas.addEventListener('pointerup',e=>{if(!drag)return;const d=drag;drag=null;if(d.mode==='pan'){draw();return;}const [x,y]=pos(e);if(d.moved){const indices=new Set(selection),left=Math.min(d.x,x),right=Math.max(d.x,x),top=Math.min(d.y,y),bottom=Math.max(d.y,y);points.forEach((p,i)=>{const [px,py]=xy(p);if(px>=left&&px<=right&&py>=top&&py<=bottom)indices.add(i);});select(indices);return;}let best=null,distance=12;points.forEach((p,i)=>{const [px,py]=xy(p),v=Math.hypot(x-px,y-py);if(v<distance){best=i;distance=v;}});if(best!==null)choose(best);else select([]);});
 for(const event of ['pointercancel','lostpointercapture'])canvas.addEventListener(event,()=>{drag=null;draw();});canvas.oncontextmenu=e=>e.preventDefault();
 window.addEventListener('keydown',e=>{if(active()&&e.key==='Escape'){drag=null;select([]);}});
 canvas.addEventListener('wheel',e=>{e.preventDefault();const [x,y]=pos(e),pe=cx+(x-width/2)/scale,pn=cy-(y-height/2)/scale;scale=Math.max(.0001,Math.min(1e6,scale*Math.exp(-e.deltaY*.001)));cx=pe-(x-width/2)/scale;cy=pn+(y-height/2)/scale;draw();},{passive:false});
 async function save(){if(busy)throw Error('7단계 처리 중입니다.');if(!sourceDigest||!result)return;if(!ready())throw Error('변경한 설정으로 자동 순서 매칭을 먼저 실행하세요.');busy=true;update();try{const r=await window.gpsProject.save(7,{source_digest:sourceDigest,reference_id:result.reference_id,max_distance_m:result.max_distance_m,order});result=r.project.stages['7'];dirty=false;message('7단계 순서 매칭을 저장했습니다.');}finally{busy=false;update();}}
 $('gps-order-save').onclick=()=>save().catch(e=>message(e.message));window.gpsOrdering={save,get busy(){return busy;}};
 window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
 window.addEventListener('gps:backgroundchange',draw);
 window.addEventListener('gps:projectchange',()=>{generation++;points=[];references=[];sourceDigest='';result=null;order=[];selected=null;selection.clear();dirty=false;history=[];drag=null;});
 window.addEventListener('dashboard:modechange',()=>{if(active())load();});new ResizeObserver(resize).observe(canvas);
})();
