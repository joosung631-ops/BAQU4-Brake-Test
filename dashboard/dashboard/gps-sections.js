/* Task boundaries interpolate corresponding samples of the two saved lane edges. */
(() => {
 const $=id=>document.getElementById(id),canvas=$('gps-section-canvas');if(!canvas)return;
 const ctx=canvas.getContext('2d');let source=null,sections=[],start=null,end=null,hover=null,dirty=false,busy=false,generation=0;
 let width=1,height=1,scale=1,cx=0,cy=0,drag=null,insertAfter=null,currentPosition=null;
 const inserting=()=>$('gps-section-insert').checked;
 const selectingAnchor=()=>inserting()&&insertAfter===null;
 const active=()=>dashboardModes.current==='map-build'&&dashboardModes.buildStep==='sections';
 const message=text=>$('gps-section-status').textContent=gpsProject.formatStages(text);
 const mix=(a,b,t)=>({e:a.e+(b.e-a.e)*t,n:a.n+(b.n-a.n)*t});
 const sub=(a,b)=>({e:a.e-b.e,n:a.n-b.n});
 const cross=(a,b)=>a.e*b.n-a.n*b.e;
 function prepare(data){
  let station=0;data.stations=data.points.map((p,i)=>{if(i)station+=Math.hypot(p.e-data.points[i-1].e,p.n-data.points[i-1].n);return p.s_m??station;});
  data.strips=data.points.slice(1).map((_,i)=>{const ps=[data.edges.left[i],data.edges.left[i+1],data.edges.right[i],data.edges.right[i+1]];return {minE:Math.min(...ps.map(p=>p.e)),maxE:Math.max(...ps.map(p=>p.e)),minN:Math.min(...ps.map(p=>p.n)),maxN:Math.max(...ps.map(p=>p.n))};});return data;
 }
 function boundary(data,index,t){return {segment_index:index,fraction:t,s_m:data.stations[index]+(data.stations[index+1]-data.stations[index])*t,center:mix(data.points[index],data.points[index+1],t),left:mix(data.edges.left[index],data.edges.left[index+1],t),right:mix(data.edges.right[index],data.edges.right[index+1],t)};}
 function hit(data,p){
  if(!data)return null;let best=null,distance=Infinity;
  // Invert each lane-strip quadrilateral. This keeps the cursor on the preview
  // and both endpoints on the rendered boundaries, including between samples.
  data.strips.forEach((box,i)=>{
   if(p.e<box.minE-1e-8||p.e>box.maxE+1e-8||p.n<box.minN-1e-8||p.n>box.maxN+1e-8)return;
   const a=data.edges.left[i],b=data.edges.left[i+1],r=data.edges.right[i],s=data.edges.right[i+1];
   const v=sub(b,a),d=sub(r,a),w=sub(sub(s,b),d),q=sub(p,a);
   const A=-cross(v,w),B=cross(q,w)-cross(v,d),C=cross(q,d);let roots=[];
   if(Math.abs(A)<1e-12){if(Math.abs(B)>1e-12)roots=[-C/B];}
   else{const disc=B*B-4*A*C;if(disc>=-1e-12){const z=Math.sqrt(Math.max(0,disc));roots=[(-B-z)/(2*A),(-B+z)/(2*A)];}}
   for(let t of roots){if(t< -1e-8||t>1+1e-8)continue;t=Math.max(0,Math.min(1,t));const line=boundary(data,i,t),span=sub(line.right,line.left),offset=sub(p,line.left),length=span.e**2+span.n**2;if(length<1e-12)continue;const u=(offset.e*span.e+offset.n*span.n)/length;if(u< -1e-8||u>1+1e-8)continue;
    const error=(p.e-line.center.e)**2+(p.n-line.center.n)**2;
    if(error<distance){distance=error;best=line;}
   }
  });return best;
 }
 const xy=p=>[width/2+(p.e-cx)*scale,height/2-(p.n-cy)*scale];
 function line(points,color,weight=1.4){ctx.strokeStyle=color;ctx.lineWidth=weight;ctx.beginPath();points.forEach((p,i)=>{const [x,y]=xy(p);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();}
 function marker(mark,color,label,right=false){if(!mark)return;line([mark.left,mark.right],color,2);if(label){const [x,y]=xy(right?mark.right:mark.left);ctx.fillStyle=color;ctx.font='11px system-ui';ctx.fillText(label,x+5,y+(right?14:-5));}}
 function draw(){if(!active())return;ctx.clearRect(0,0,width,height);window.drawGpsGrid(ctx,width,height,scale,cx,cy);window.drawGpsReference(ctx,width,height,scale,cx,cy);
  if(source){line(source.edges.left,'#df8585');line(source.edges.right,'#df8585');line(source.points,'#4e83ba',1.2);
   for(const [p,label] of [[source.points[0],'경로 시작'],[source.points.at(-1),'경로 끝']]){const [x,y]=xy(p);ctx.fillStyle='#4e83ba';ctx.font='11px system-ui';ctx.fillText(label,x+5,y-7);}
  }
  window.drawGpsReplayPosition(ctx,canvas,source,currentPosition,scale,xy);
  sections.forEach((s,i)=>{marker(s.start,'#17836f',`${i+1}. ${s.name} 시작`);marker(s.end,'#8863ac',`${i+1}. 종료`,true);});
  marker(start,'#17836f','선택 시작');marker(end,'#8863ac','선택 종료',true);marker(hover,'#d39935',selectingAnchor()?'종료 지점 선택':end?'미리보기':start?'종료 선택':'시작 선택');
  window.drawGpsScale(ctx,width,height,scale);canvas.dataset.hoverVisible=String(!!hover);canvas.dataset.sectionCount=String(sections.length);
 }
 function update(){
  $('gps-section-selection').textContent=selectingAnchor()?'지도에서 기존 구간의 종료 선분을 선택하세요.':!start?'구간 시작 선분을 선택하세요.':!end?`${inserting()?`${insertAfter+1}번 구간 종료에서 삽입`:sections.length?'이전 구간 종료에서 시작':'시작'} ${start.s_m.toFixed(2)} m · 종료 선분을 선택하세요.`:`시작 ${start.s_m.toFixed(2)} m → 종료 ${end.s_m.toFixed(2)} m · 길이 ${(end.s_m-start.s_m).toFixed(2)} m`;
  $('gps-section-insert').disabled=busy||!sections.length;
  $('gps-section-confirm').disabled=busy||!start||!end||!$('gps-section-name').value.trim()||!$('gps-section-description').value.trim();
  $('gps-section-save').disabled=busy||!source;$('gps-section-reset').disabled=busy;
  $('gps-section-dirty').textContent=dirty?'변경 내용 미저장':source?.saved?'저장된 상태':'';
  canvas.style.cursor=hover?'crosshair':'grab';
  window.dispatchEvent(new CustomEvent('gps:sectionschange'));
 }
 function reconnect(){let changed=false;for(let i=1;i<sections.length;i++){const previous=sections[i-1].end;if(sections[i].end.s_m<=previous.s_m+1e-6)throw Error('구간 종료 순서를 확인하세요. 뒤 구간의 종료점은 앞 구간보다 뒤에 있어야 합니다.');if(JSON.stringify(sections[i].start)!==JSON.stringify(previous)){sections[i].start=previous;changed=true;}}return changed;}
 function renderList(){const list=$('gps-section-list');list.replaceChildren();sections.forEach((section,i)=>{
  const li=document.createElement('li'),title=document.createElement('strong'),description=document.createElement('p'),remove=document.createElement('button');
  title.textContent=section.name;description.textContent=`${section.description}\n${section.start.s_m.toFixed(2)}–${section.end.s_m.toFixed(2)} m`;description.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;margin:4px 0';title.style.overflowWrap='anywhere';remove.textContent='삭제';remove.disabled=busy;remove.onclick=()=>{sections.splice(i,1);reconnect();dirty=true;reset();renderList();};li.append(title,description,remove);li.style.marginBottom='12px';list.append(li);
 });}
 function reset(){if(!sections.length)$('gps-section-insert').checked=false;insertAfter=null;start=inserting()?null:sections.at(-1)?.end??null;end=hover=null;$('gps-section-name').value='';$('gps-section-description').value='';update();draw();}
 function resize(){if(!active())return;const r=canvas.getBoundingClientRect(),dpr=devicePixelRatio||1;width=Math.max(1,r.width);height=Math.max(1,r.height);canvas.width=width*dpr;canvas.height=height*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);draw();}
 function fit(){if(!source)return;const all=[...source.edges.left,...source.edges.right].concat(window.gpsReferencePoints());let a=Infinity,b=-Infinity,c=Infinity,d=-Infinity;for(const p of all){a=Math.min(a,p.e);b=Math.max(b,p.e);c=Math.min(c,p.n);d=Math.max(d,p.n);}cx=(a+b)/2;cy=(c+d)/2;scale=Math.max(.0001,Math.min(Math.max(20,width-120)/Math.max(1,b-a),Math.max(20,height-150)/Math.max(1,d-c)));hover=null;draw();}
 async function load(){if(busy||!gpsProject.current)return;busy=true;source=null;sections=[];dirty=false;reset();renderList();const version=++generation;try{
  const data=await gpsProject.api('/api/gps/projects/section-source?filename='+encodeURIComponent(gpsProject.current.filename));if(version!==generation)return;source=prepare(data);sections=data.saved?.sections||[];dirty=reconnect();reset();message(dirty?'이전 구간 종료점에 맞춰 시작점을 보정했습니다. 10단계 저장을 누르세요.':sections.length?'이전 구간 종료가 시작점입니다. 다음 종료 지점을 클릭하세요.':'차선 안에서 구간 시작과 종료를 차례로 클릭하세요.');resize();fit();
 }catch(e){message(e.message);}finally{busy=false;renderList();update();}}
 async function save(){if(busy)throw Error('과제 구간을 처리 중입니다.');if(!source)throw Error('9단계에서 예상 차선을 적용하고 저장하세요.');busy=true;update();renderList();try{
  const result=await gpsProject.save(10,{source_digest:source.source_digest,sections});source.saved=result.project.stages['10'];sections=source.saved.sections;dirty=false;message('10단계 과제 구간 저장 완료');
 }finally{busy=false;update();renderList();draw();}}
 $('gps-section-confirm').onclick=()=>{if($('gps-section-confirm').disabled)return;const section={name:$('gps-section-name').value.trim(),description:$('gps-section-description').value.trim(),start,end};if(inserting())sections.splice(insertAfter+1,0,section);else sections.push(section);reconnect();$('gps-section-insert').checked=false;dirty=true;reset();renderList();message(`구간 ${sections.length}개 · 10단계 저장을 누르세요.`);};
 $('gps-section-insert').onchange=()=>{reset();message(inserting()?'삽입할 시작점으로 사용할 기존 종료 선분을 클릭하세요.':'다음 구간의 종료 지점을 클릭하세요.');};
 $('gps-section-name').oninput=$('gps-section-description').oninput=update;
 $('gps-section-reset').onclick=reset;$('gps-section-fit').onclick=fit;$('gps-section-save').onclick=()=>save().catch(e=>message(e.message));
 const pos=e=>{const r=canvas.getBoundingClientRect();return [e.clientX-r.left,e.clientY-r.top];};
 const world=e=>{const [x,y]=pos(e);return {e:cx+(x-width/2)/scale,n:cy-(y-height/2)/scale};};
 function anchorAt(e){const [x,y]=pos(e);let best=null,distance=9;sections.forEach((section,index)=>{const [ax,ay]=xy(section.end.left),[bx,by]=xy(section.end.right),dx=bx-ax,dy=by-ay,t=Math.max(0,Math.min(1,((x-ax)*dx+(y-ay)*dy)/(dx*dx+dy*dy||1))),d=Math.hypot(x-ax-t*dx,y-ay-t*dy);if(d<distance){distance=d;best={index,mark:section.end};}});return best;}
 const preview=e=>selectingAnchor()?anchorAt(e)?.mark??null:hit(source,world(e));
 canvas.onpointerdown=e=>{if(busy||!source)return;if(e.button===2||e.button===1){const [x,y]=pos(e);drag={x,y,cx,cy};hover=null;canvas.setPointerCapture(e.pointerId);draw();}};
 canvas.onpointermove=e=>{if(busy)return;if(drag){const [x,y]=pos(e);cx=drag.cx-(x-drag.x)/scale;cy=drag.cy+(y-drag.y)/scale;}else hover=preview(e);update();draw();};
 canvas.onclick=e=>{if(busy||drag||end)return;if(selectingAnchor()){const anchor=anchorAt(e);if(!anchor){message('기존 구간의 종료 선분을 클릭하세요.');return;}insertAfter=anchor.index;start=anchor.mark;hover=null;message('새 구간의 종료 지점을 클릭하세요.');update();draw();return;}const found=hit(source,world(e));if(!found)return;if(!start){start=found;message('경로 진행 순서상 시작 뒤의 종료 선분을 선택하세요.');}else if(found.s_m<=start.s_m+1e-6){message('종료는 경로 진행 순서상 시작보다 뒤에 선택하세요.');return;}else if(inserting()&&sections[insertAfter+1]&&found.s_m>=sections[insertAfter+1].end.s_m-1e-6){message('삽입 구간의 종료는 다음 구간 종료점보다 앞에 선택하세요.');return;}else{end=found;hover=null;message('구간 이름과 설명을 입력하고 구간 결정을 누르세요.');}update();draw();};
 canvas.onpointerup=canvas.onpointercancel=canvas.onlostpointercapture=()=>{drag=null;};canvas.onpointerleave=()=>{hover=null;update();draw();};canvas.oncontextmenu=e=>e.preventDefault();
 canvas.addEventListener('wheel',e=>{e.preventDefault();const p=world(e),[x,y]=pos(e);scale=Math.max(.0001,Math.min(1e6,scale*Math.exp(-e.deltaY*.001)));cx=p.e-(x-width/2)/scale;cy=p.n+(y-height/2)/scale;hover=preview(e);update();draw();},{passive:false});
 window.gpsSections={get projectionSource(){return source?{...source,task_sections:sections,preview_boundaries:[start,end].filter(Boolean),view:gpsProject.current?.project.stages['9']?.projection}:null;},setCurrentPosition(p){currentPosition=p;draw();},save,get busy(){return busy;}};
 window.gpsSectionGeometry={prepare,boundary,hit};
 window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
 window.addEventListener('gps:backgroundchange',draw);
 window.addEventListener('gps:projectchange',()=>{generation++;currentPosition=null;source=null;sections=[];dirty=false;drag=null;reset();renderList();});
 window.addEventListener('dashboard:modechange',()=>{hover=null;drag=null;if(active())load();});new ResizeObserver(resize).observe(canvas);
})();
