/* Raw-image lane projection: flat ground, path tangent, measured GPS/camera offsets. */
(() => {
 const $=id=>document.getElementById(id),canvas=$('gps-camera-projection');if(!canvas)return;
 const ctx=canvas.getContext('2d'),image=$('gps-map-camera-image');
 let config=null,configError='',generation=0,frame=null,cache=null,laterView=null;
 const active=()=>dashboardModes.current==='map-build'&&['lane','sections','validation','export'].includes(dashboardModes.buildStep);
 const sourceFor=()=>dashboardModes.buildStep==='sections'?window.gpsSections?.projectionSource:window.gpsLane?.projectionSource;
 const normalize=view=>({enabled:true,time_offset_s:0,...view,show_lanes:view?.show_lanes??view?.enabled??true,show_center:view?.show_center??view?.enabled??true,show_sections:view?.show_sections??true});
 const viewFor=()=>dashboardModes.buildStep==='lane'?normalize(sourceFor()?.view):(laterView??normalize(gpsProject.current?.project.stages['9']?.projection));
 const angle=(a,b,t)=>a+Math.atan2(Math.sin(b-a),Math.cos(b-a))*t;
 const mix=(a,b,t)=>a+(b-a)*t;
 function indexAt(rows,t,get=x=>x){let a=0,b=rows.length;while(a<b){const m=(a+b)>>1;if(get(rows[m])<=t)a=m+1;else b=m;}return a-1;}
 function toENU(lat,lon,origin){const r=Math.PI/180,a=origin[0]*r,b=origin[1]*r;
  const ecef=(x,y)=>{x*=r;y*=r;const n=6378137/Math.sqrt(1-6.6943799901413165e-3*Math.sin(x)**2);return [n*Math.cos(x)*Math.cos(y),n*Math.cos(x)*Math.sin(y),n*(1-6.6943799901413165e-3)*Math.sin(x)];};
  const base=ecef(...origin),d=ecef(lat,lon).map((v,i)=>v-base[i]);return {e:-Math.sin(b)*d[0]+Math.cos(b)*d[1],n:-Math.sin(a)*Math.cos(b)*d[0]-Math.sin(a)*Math.sin(b)*d[1]+Math.cos(a)*d[2]};
 }
 function preparePath(source,vehicle){let distance=0;const points=source.points.map((p,i)=>{if(i)distance+=Math.hypot(p.e-source.points[i-1].e,p.n-source.points[i-1].n);const h=p.heading_rad,c=Math.cos(h),s=Math.sin(h);return {...p,s_m:p.s_m??distance,linear_segment:source.interpolation==='piecewise_linear',ge:source.reference_point==='gps_antenna'?p.e:p.e+c*vehicle.gps_antenna_offset_x_m-s*vehicle.gps_antenna_offset_y_m,gn:source.reference_point==='gps_antenna'?p.n:p.n+s*vehicle.gps_antenna_offset_x_m+c*vehicle.gps_antenna_offset_y_m};});return points;}
 function matchTrack(gps,path,origin){let previous=null;return gps.map(g=>{const q={...g,...toENU(g.lat,g.lon,origin)};let best=null,nearest=null,score=Infinity,nearestDistance=Infinity;
  const continuous=previous&&previous.distance_m<5&&g.t-previous.t<=3,allowed=continuous?Math.hypot(q.e-previous.e,q.n-previous.n)+2:Infinity;
  for(let i=0;i<path.length-1;i++){const a=path[i],b=path[i+1],dx=b.ge-a.ge,dy=b.gn-a.gn,len=dx*dx+dy*dy,t=Math.max(0,Math.min(1,((q.e-a.ge)*dx+(q.n-a.gn)*dy)/(len||1))),s=mix(a.s_m,b.s_m,t),d2=(q.e-a.ge-t*dx)**2+(q.n-a.gn-t*dy)**2;
   const excess=continuous?Math.max(0,Math.abs(s-previous.s_m)-allowed):0,cost=d2+4*excess*excess;
   if(d2<nearestDistance){nearestDistance=d2;nearest={s_m:s,distance_m:Math.sqrt(d2)};}
   if(cost<score){score=cost;best={s_m:s,distance_m:Math.sqrt(d2)};}
  }if(best.distance_m>Math.max(5,nearest.distance_m+3))best=nearest;previous={...q,...best};return previous;
 });}
 function poseAtTrack(track,path,t){const i=indexAt(track,t,p=>p.t);if(i<0)return null;const a=track[i],b=track[i+1];let pose;
  if(Math.abs(t-a.t)<1e-6)pose={...a};
  else{if(!b||b.t-a.t>3||b.t<=a.t)return null;const k=(t-a.t)/(b.t-a.t);pose={t};for(const key of ['lat','lon','e','n','s_m','distance_m'])pose[key]=mix(a[key],b[key],k);}
  const j=Math.max(0,Math.min(path.length-2,indexAt(path,pose.s_m,p=>p.s_m))),p=path[j],q=path[j+1],k=Math.max(0,Math.min(1,(pose.s_m-p.s_m)/(q.s_m-p.s_m||1)));
  return {...pose,heading_rad:p.linear_segment?p.heading_rad:angle(p.heading_rad,q.heading_rad,k),heading_source:'reference_path_tangent'};
 }
 function optical(point,pose,cfg){const h=pose.heading_rad,c=Math.cos(h),s=Math.sin(h),mount=cfg.camera,vehicle=cfg.vehicle;
  const dx=mount.distance_from_rear_m-vehicle.rear_axle_distance_from_rear_m-vehicle.gps_antenna_offset_x_m,dy=mount.lateral_offset_m-vehicle.gps_antenna_offset_y_m;
  const de=point.e-pose.e,dn=point.n-pose.n,x=c*de+s*dn-dx,y=-s*de+c*dn-dy,z=-mount.height_above_ground_m,pitch=mount.pitch_deg*Math.PI/180;
  return {x:-y,y:Math.sin(pitch)*x-Math.cos(pitch)*z,z:Math.cos(pitch)*x+Math.sin(pitch)*z};
 }
 function pixel(p,calibration,width,height){if(p.z<.1)return null;const x=p.x/p.z,y=p.y/p.z,r2=x*x+y*y;if(r2>100)return null;
  const [k1,k2,p1,p2,k3=0]=calibration.distortion_coefficients.data,k=calibration.camera_matrix.data,radial=1+k1*r2+k2*r2*r2+k3*r2*r2*r2;
  const xd=x*radial+2*p1*x*y+p2*(r2+2*x*x),yd=y*radial+p1*(r2+2*y*y)+2*p2*x*y;
  const u=(k[0]*xd+k[2])*width/calibration.image_width,v=(k[4]*yd+k[5])*height/calibration.image_height;
  return Number.isFinite(u)&&Number.isFinite(v)?{x:u,y:v}:null;
 }
 function projectedSegment(a,b,pose,cfg,width,height){let p=optical(a,pose,cfg),q=optical(b,pose,cfg);if(p.z<.1&&q.z<.1)return null;
  if(p.z<.1||q.z<.1){const t=(.100001-p.z)/(q.z-p.z),cut={x:mix(p.x,q.x,t),y:mix(p.y,q.y,t),z:.100001};if(p.z<.1)p=cut;else q=cut;}
  p=pixel(p,cfg.calibration,width,height);q=pixel(q,cfg.calibration,width,height);if(!p||!q)return null;
  // Liang–Barsky clips to the image; off-screen/behind segments never join.
  let lo=0,hi=1;const dx=q.x-p.x,dy=q.y-p.y;
  for(const [d,v] of [[-dx,p.x],[dx,width-p.x],[-dy,p.y],[dy,height-p.y]]){if(Math.abs(d)<1e-12){if(v<0)return null;continue;}const t=v/d;if(d<0)lo=Math.max(lo,t);else hi=Math.min(hi,t);if(lo>hi)return null;}
  return [{x:p.x+lo*dx,y:p.y+lo*dy},{x:p.x+hi*dx,y:p.y+hi*dy}];
 }
 function trackFor(data){const source=sourceFor();if(!config||!source?.origin||source.points.length<2||!data?.gps?.length)return null;
  if(!cache||cache.token!==data.token||cache.points!==source.points||cache.config!==config){const path=preparePath(source,config.vehicle);cache={token:data.token,points:source.points,config,path,track:matchTrack(data.gps,path,source.origin)};}return cache;
 }
 function poseAt(data,t){const c=trackFor(data);return c?poseAtTrack(c.track,c.path,t):null;}
 const clear=()=>{ctx.clearRect(0,0,canvas.width,canvas.height);canvas.hidden=true;for(const key of ['segmentCount','laneSegmentCount','centerSegmentCount','sectionSegmentCount'])canvas.dataset[key]='0';delete canvas.dataset.gpsTime;};
 function draw(){clear();if(!active())return;const status=$('gps-projection-status'),source=sourceFor(),view=viewFor();
  if(!view.show_lanes&&!view.show_center&&(!view.show_sections||dashboardModes.buildStep==='lane')){status.textContent='영상 투영 꺼짐';return;}if(configError){status.textContent=configError;return;}if(!config){status.textContent='카메라 설정을 읽는 중…';return;}
  if(!source?.points?.length){status.textContent='경로를 불러오는 중…';return;}if(!frame||image.hidden){status.textContent='로스백 카메라 프레임 대기';return;}
  const w=frame.width,h=frame.height,cal=config.calibration;
  if(Math.abs((w/h)/(cal.image_width/cal.image_height)-1)>.005){status.textContent=`영상 ${w}×${h}와 보정 ${cal.image_width}×${cal.image_height}의 가로세로 비율이 달라 투영을 중지했습니다.`;return;}
  const t=frame.time+view.time_offset_s,pose=poseAt(frame.data,t);if(!pose){status.textContent='해당 시각의 GPS 보간 불가: 기록 범위 또는 3초 초과 공백을 확인하세요.';return;}
  if(pose.distance_m>20){status.textContent='GPS가 기준 경로에서 20 m 이상 떨어져 투영을 중지했습니다.';return;}
  if(dashboardModes.buildStep==='lane')gpsLane.setCurrentPosition(pose);
  const rect=canvas.parentElement.getBoundingClientRect(),dpr=devicePixelRatio||1;canvas.width=Math.max(1,Math.round(rect.width*dpr));canvas.height=Math.max(1,Math.round(rect.height*dpr));
  const factor=Math.min(rect.width/w,rect.height/h);ctx.setTransform(dpr*factor,0,0,dpr*factor,dpr*(rect.width-w*factor)/2,dpr*(rect.height-h*factor)/2);
  ctx.lineWidth=3/factor;ctx.lineCap='round';ctx.lineJoin='round';let count=0;
  const path=cache.path,first=Math.max(0,indexAt(path,pose.s_m-3,p=>p.s_m));
  const counts={lane:0,center:0,section:0},lines=[];
  if(view.show_lanes&&source.edges)lines.push([source.edges.left,'#ed9696','lane'],[source.edges.right,'#ed9696','lane']);
  if(view.show_center)lines.push([source.points,'#4e9bea','center']);
  function stroke(a,b,kind){const segment=projectedSegment(a,b,pose,config,w,h);if(!segment)return;ctx.moveTo(segment[0].x,segment[0].y);ctx.lineTo(segment[1].x,segment[1].y);count++;counts[kind]++;}
  for(const [points,color,kind] of lines){
   ctx.strokeStyle=color;ctx.beginPath();
   for(let i=first;i<points.length-1&&path[i].s_m<=pose.s_m+60;i++)stroke(points[i],points[i+1],kind);
   ctx.stroke();
  }
  if(view.show_sections&&dashboardModes.buildStep!=='lane'){
   const marks=new Map();
   for(const section of source.task_sections||[])for(const mark of [section.start,section.end])marks.set(mark.s_m.toFixed(6),mark);
   for(const mark of source.preview_boundaries||[])marks.set(mark.s_m.toFixed(6),mark);
   ctx.strokeStyle='#dda640';ctx.beginPath();
   for(const mark of marks.values()){
    if(mark.s_m<pose.s_m-3||mark.s_m>pose.s_m+60)continue;
    const a=mark.left,b=mark.right,steps=Math.max(1,Math.ceil(Math.hypot(b.e-a.e,b.n-a.n)/.1));
    const point=t=>({e:mix(a.e,b.e,t),n:mix(a.n,b.n,t)});
    for(let i=0;i<steps;i++)stroke(point(i/steps),point((i+1)/steps),'section');
   }ctx.stroke();
  }
  for(const [key,value] of Object.entries(counts))canvas.dataset[key+'SegmentCount']=String(value);
  ctx.setTransform(1,0,0,1,0,0);canvas.hidden=false;canvas.dataset.segmentCount=String(count);canvas.dataset.gpsTime=String(t);canvas.dataset.frameTime=String(frame.time);canvas.dataset.heading=String(pose.heading_rad);
  status.textContent=`${count?'지도 영상 투영':'화면 안에 투영할 선 없음'} · 영상 ${frame.time.toFixed(2)} s / GPS ${t.toFixed(2)} s`+(w!==cal.image_width||h!==cal.image_height?' · 해상도 비례 조정(동일 화각 가정)':'');
 }
 async function loadConfig(){const version=++generation;config=null;configError='';cache=null;draw();try{const data=await gpsProject.api('/api/gps/projects/projection-config');if(version!==generation)return;config=data;const cal=data.calibration;$('gps-projection-config').textContent=`보정 ${cal.image_width}×${cal.image_height} · 카메라 높이 ${data.camera.height_above_ground_m} m · 장착 각도 ${data.camera.pitch_deg}°`;}
  catch(error){if(version===generation)configError=error.message;}finally{if(version===generation)draw();}}
 function syncView(){const view=viewFor();$('gps-projection-enabled').checked=view.show_lanes;$('gps-projection-center').checked=view.show_center;$('gps-projection-sections').checked=view.show_sections;$('gps-projection-offset').value=view.time_offset_s;draw();}
 function changeView(){const offset=Number($('gps-projection-offset').value);if(!Number.isFinite(offset)||Math.abs(offset)>30){$('gps-projection-status').textContent='시간 보정은 -30~30초로 입력하세요.';return;}
  const view={enabled:true,time_offset_s:offset,show_lanes:$('gps-projection-enabled').checked,show_center:$('gps-projection-center').checked,show_sections:$('gps-projection-sections').checked};
  if(dashboardModes.buildStep==='lane')gpsLane.setProjectionView(view);else laterView=view;draw();
 }
 for(const id of ['gps-projection-enabled','gps-projection-center','gps-projection-sections','gps-projection-offset'])$(id).onchange=changeView;
 $('gps-projection-reload').onclick=loadConfig;
 window.gpsProjection={poseAt,setFrame(value){frame=value;draw();},clear(){frame=null;clear();},redraw:draw};
 window.gpsProjectionGeometry={toENU,preparePath,matchTrack,poseAtTrack,optical,pixel,projectedSegment};
 window.addEventListener('gps:lanechange',syncView);window.addEventListener('gps:sectionschange',draw);window.addEventListener('gps:projectchange',()=>{laterView=null;cache=null;frame=null;clear();});
 window.addEventListener('dashboard:modechange',()=>{if(active()){syncView();loadConfig();}else{frame=null;clear();}});
 new ResizeObserver(draw).observe(canvas.parentElement);
})();
