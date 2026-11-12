/* Shared vehicle overlay, anchored at recorded GPS coordinates. */
window.drawGpsReplayPosition=(ctx,canvas,source,currentPosition,scale,xy)=>{
 const points=source?.points||[];
  if(currentPosition&&source?.origin){
   const origin=source.origin,rad=Math.PI/180,a=origin[0]*rad,b=origin[1]*rad;
   const ecef=(lat,lon)=>{lat*=rad;lon*=rad;const n=6378137/Math.sqrt(1-6.6943799901413165e-3*Math.sin(lat)**2);return [n*Math.cos(lat)*Math.cos(lon),n*Math.cos(lat)*Math.sin(lon),n*(1-6.6943799901413165e-3)*Math.sin(lat)];};
   const base=ecef(...origin),d=ecef(currentPosition.lat,currentPosition.lon).map((v,i)=>v-base[i]);
   const p={e:-Math.sin(b)*d[0]+Math.cos(b)*d[1],n:-Math.sin(a)*Math.cos(b)*d[0]-Math.sin(a)*Math.sin(b)*d[1]+Math.cos(a)*d[2]},[x,y]=xy(p);
   canvas.dataset.currentEast=String(p.e);canvas.dataset.currentNorth=String(p.n);
   const vehicle=source.vehicle;
   let heading=currentPosition.heading_rad,headingSource=currentPosition.heading_source==='reference_path_tangent'?'중앙선 접선 방향':'GPS 이동 방향';
   if(!Number.isFinite(heading)){
    let best=Infinity,nearest=null;for(const point of points){const distance=(point.e-p.e)**2+(point.n-p.n)**2;if(distance<best){best=distance;nearest=point;}}
    heading=nearest?.heading_rad??0;headingSource='경로 접선 추정';
   }
   canvas.dataset.currentHeading=String(heading);canvas.dataset.headingSource=headingSource;
   if(vehicle){
    const length=vehicle.vehicle_length_m,w=vehicle.vehicle_width_m;
    // GPS coordinates anchor the antenna, not the rectangle center or rear axle.
    const rear=vehicle.rear_axle_distance_from_rear_m+vehicle.gps_antenna_offset_x_m;
    const left=vehicle.gps_antenna_offset_y_m-w/2;
    ctx.save();ctx.translate(x,y);ctx.rotate(-heading);ctx.fillStyle='#159a80';
    ctx.fillRect(-rear*scale,left*scale,length*scale,w*scale);
    ctx.strokeStyle='#0b6956';ctx.lineWidth=1;ctx.strokeRect(-rear*scale,left*scale,length*scale,w*scale);
    ctx.strokeStyle='#eafff7';ctx.lineWidth=1.5;ctx.beginPath();const front=(length-rear)*scale;
    ctx.moveTo(front,(left+w*.2)*scale);ctx.lineTo(front,(left+w*.8)*scale);ctx.stroke();ctx.restore();
    canvas.dataset.vehicleLength=String(length);canvas.dataset.vehicleWidth=String(w);canvas.dataset.gpsFromRear=String(rear);
   }
   ctx.fillStyle='#127b68';ctx.font='bold 11px system-ui';ctx.fillText(vehicle?`현위치 · ${headingSource}`:'차량 설정 확인 필요',x+12,y-10);
  }else{delete canvas.dataset.currentEast;delete canvas.dataset.currentNorth;delete canvas.dataset.currentHeading;delete canvas.dataset.headingSource;}
};
/* Estimated lane edges from the saved center path and road configuration. */
(() => {
 const $=id=>document.getElementById(id),canvas=$('gps-lane-canvas');if(!canvas)return;
 const ctx=canvas.getContext('2d');let source=null,settings=null,edges=null,busy=false,dirty=false,generation=0;
 let currentPosition=null,projectionView={enabled:true,time_offset_s:0};
 const notifyProjection=()=>window.dispatchEvent(new Event('gps:lanechange'));
 let width=1,height=1,scale=1,cx=0,cy=0,drag=null;
 const active=()=>window.dashboardModes?.current==='map-build'&&['lane','validation','export'].includes(window.dashboardModes?.buildStep);
 const message=s=>$('gps-lane-status').textContent=gpsProject.formatStages(s);
 const xy=p=>[width/2+(p.e-cx)*scale,height/2-(p.n-cy)*scale];
 const selectedWidth=()=>Number($('gps-lane-width-input').value);
 const validWidth=()=>Number.isFinite(selectedWidth())&&selectedWidth()>0;
 function update(){
  $('gps-lane-width-input').disabled=busy||!source;$('gps-lane-apply').disabled=busy||!source||!validWidth();$('gps-lane-cancel').disabled=busy||!edges;$('gps-lane-save').disabled=busy||!settings||(settings.enabled!==false&&!validWidth());
  const w=source?.road_config?.lane_width_m;
  $('gps-lane-width').textContent=typeof w==='number'?`설정 차선 폭: ${w} m · 좌우 각각 ${w/2} m`:'설정 기본값 없음 · 차선 폭을 입력하세요.';
  $('gps-lane-summary').textContent=settings?.enabled===false?'차선 미적용':settings?`적용 차선 폭: ${settings.lane_width_m} m · 좌우 각각 ${settings.lane_width_m/2} m`:'';
  $('gps-lane-dirty').textContent=dirty?'변경 내용 미저장':settings?'저장된 상태 · 직선 보간선 기준':source?'직선 보간선 기준 · 9단계 다시 적용 필요':'';
  canvas.dataset.pointCount=String(source?.points.length||0);canvas.dataset.edgeCount=String(edges?.left.length||0);
  canvas.dataset.appliedWidth=edges?String(settings.lane_width_m):'';
 }
 function line(points,color,lineWidth){ctx.strokeStyle=color;ctx.lineWidth=lineWidth;ctx.beginPath();points.forEach((p,i)=>{const [x,y]=xy(p);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();}
 function draw(){if(!active())return;ctx.clearRect(0,0,width,height);window.drawGpsGrid(ctx,width,height,scale,cx,cy);window.drawGpsReference(ctx,width,height,scale,cx,cy);
  if(edges){line(edges.left,'#df8585',1.7);line(edges.right,'#df8585',1.7);}
  const points=source?.points||[];line(points,'#4e83ba',1.2);
  if(['validation','export'].includes(window.dashboardModes.buildStep))for(const [i,section] of (source?.task_sections||[]).entries()){
   line([section.start.left,section.start.right],'#17836f',2);
   line([section.end.left,section.end.right],'#8863ac',2);
   const [x,y]=xy(section.start.left);ctx.fillStyle='#17836f';ctx.font='11px system-ui';ctx.fillText(`${i+1}. ${section.name} 시작`,x+5,y-5);
  }
  if(points.length){ctx.font='11px system-ui';ctx.fillStyle='#4e83ba';for(const [p,label] of [[points[0],'시작'],[points.at(-1),'끝']]){const [x,y]=xy(p);ctx.beginPath();ctx.arc(x,y,4,0,Math.PI*2);ctx.fill();ctx.fillText(label,x+7,y-8);}}
  window.drawGpsReplayPosition(ctx,canvas,source,currentPosition,scale,xy);
  window.drawGpsScale(ctx,width,height,scale);update();
 }
 function resize(){if(!active())return;const r=canvas.getBoundingClientRect(),dpr=devicePixelRatio||1;width=Math.max(1,r.width);height=Math.max(1,r.height);canvas.width=width*dpr;canvas.height=height*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);draw();}
 function fit(){const all=[...(source?.points||[]),...(edges?.left||[]),...(edges?.right||[])].concat(window.gpsReferencePoints());if(!all.length){draw();return;}let a=Infinity,b=-Infinity,c=Infinity,d=-Infinity;for(const p of all){a=Math.min(a,p.e);b=Math.max(b,p.e);c=Math.min(c,p.n);d=Math.max(d,p.n);}cx=(a+b)/2;cy=(c+d)/2;scale=Math.max(.0001,Math.min(Math.max(20,width-120)/Math.max(1,b-a),Math.max(20,height-150)/Math.max(1,d-c)));draw();}
 async function load(){if(busy)return;busy=true;source=null;settings=null;edges=null;dirty=false;drag=null;update();draw();const version=++generation;try{
  const data=await gpsProject.api('/api/gps/projects/lane-source?filename='+encodeURIComponent(gpsProject.current.filename)+(['validation','export'].includes(dashboardModes.buildStep)?'&final=1':''));if(version!==generation)return;
  source=data;settings=data.saved;edges=data.edges;$('gps-lane-width-input').value=settings?.lane_width_m??data.road_config?.lane_width_m??'';projectionView={enabled:true,time_offset_s:0,...settings?.projection};notifyProjection();
  message(data.vehicle_error||(['validation','export'].includes(window.dashboardModes.buildStep)?'직선 보간 경로와 예상 차선으로 로스백을 검증합니다.':data.road_error)||(settings?.enabled===false?'저장된 Map을 불러왔습니다. 차선 미적용 상태입니다.':settings?'저장된 예상 차선을 불러왔습니다.':'직선 보간선 기준입니다. 차선 폭 설정 후 차선 적용을 누르세요.'));resize();fit();
 }catch(e){message(e.message);}finally{busy=false;update();}}
 $('gps-lane-apply').onclick=async()=>{if(busy||!source)return;if(!validWidth()){message('차선 폭은 0보다 큰 m 값으로 입력하세요.');return;}busy=true;update();try{
  const data=await gpsProject.api('/api/gps/projects/lane-preview',{filename:gpsProject.current.filename,source_digest:source.source_digest,lane_width_m:selectedWidth()});
  settings=data.settings;edges=data.edges;source.road_config=settings.road_config;dirty=true;notifyProjection();message('예상 차선을 적용했습니다. 9단계 저장을 누르세요.');fit();
 }catch(e){message(e.message);}finally{busy=false;update();}};
 async function save(force=false){if(busy)throw Error('9단계 처리 중입니다.');if(settings?.enabled!==false&&settings&&!validWidth())throw Error('차선 폭은 0보다 큰 m 값으로 입력하세요.');if(!dirty){if(force){busy=true;update();try{await gpsProject.save(9,{retain:true});message('9단계 저장 완료');}finally{busy=false;update();}}return;}if(!settings)throw Error('예상 차선을 먼저 적용하세요.');busy=true;update();try{
  const data=await gpsProject.save(9,{source_digest:source.source_digest,road_digest:settings.road_digest,lane_width_m:settings.lane_width_m,enabled:settings.enabled!==false,projection:projectionView});settings=data.project.stages['9'];dirty=false;message('9단계 예상 차선 적용 결과를 저장했습니다.');
 }finally{busy=false;update();}}
 $('gps-lane-cancel').onclick=()=>{if(busy||!edges)return;settings={...settings,enabled:false};edges=null;dirty=true;notifyProjection();message('예상 차선 적용을 취소했습니다.');draw();};
 $('gps-lane-width-input').oninput=()=>{if(busy||!source)return;if(!validWidth()){message('차선 폭은 0보다 큰 m 값으로 입력하세요.');update();return;}const value=selectedWidth();
  if(settings&&value!==settings.lane_width_m){settings={...settings,lane_width_m:value};if(settings.enabled!==false){const half=value/2;edges={left:[],right:[]};for(const p of source.points){const dx=-Math.sin(p.heading_rad)*half,dy=Math.cos(p.heading_rad)*half;edges.left.push({e:p.e+dx,n:p.n+dy});edges.right.push({e:p.e-dx,n:p.n-dy});}}dirty=true;notifyProjection();draw();message('조정한 차선 폭을 적용했습니다. 9단계 저장을 누르세요.');}update();};
 $('gps-lane-save').onclick=()=>save(true).catch(e=>message(e.message));$('gps-lane-fit').onclick=fit;
 const pos=e=>{const r=canvas.getBoundingClientRect();return [e.clientX-r.left,e.clientY-r.top];};
 canvas.onpointerdown=e=>{const [x,y]=pos(e);drag={x,y,cx,cy};canvas.setPointerCapture(e.pointerId);};
 canvas.onpointermove=e=>{if(!drag)return;const [x,y]=pos(e);cx=drag.cx-(x-drag.x)/scale;cy=drag.cy+(y-drag.y)/scale;draw();};
 canvas.onpointerup=canvas.onpointercancel=canvas.onlostpointercapture=()=>{drag=null;};canvas.oncontextmenu=e=>e.preventDefault();
 canvas.addEventListener('wheel',e=>{e.preventDefault();const [x,y]=pos(e),pe=cx+(x-width/2)/scale,pn=cy-(y-height/2)/scale;scale=Math.max(.0001,Math.min(1e6,scale*Math.exp(-e.deltaY*.001)));cx=pe-(x-width/2)/scale;cy=pn+(y-height/2)/scale;draw();},{passive:false});
 window.gpsLane={get projectionSource(){return source?{...source,edges,view:projectionView}:null;},setProjectionView(view){projectionView={...view};if(settings)dirty=true;update();},setCurrentPosition(p){currentPosition=p;draw();},save,get busy(){return busy;}};
 window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
 window.addEventListener('gps:backgroundchange',draw);
 window.addEventListener('gps:projectchange',()=>{generation++;source=null;settings=null;edges=null;dirty=false;drag=null;notifyProjection();});
 window.addEventListener('dashboard:modechange',()=>{if(active())load();});new ResizeObserver(resize).observe(canvas);
})();
