/* Read-only multi-map GPS overlay. Every map shares the same WGS84 ENU origin. */
(() => {
  const $=id=>document.getElementById(id),canvas=$('map-compare-canvas');if(!canvas)return;
  const ctx=canvas.getContext('2d'),buffer=document.createElement('canvas'),paint=buffer.getContext('2d');
  const files=$('map-compare-files'),status=$('map-compare-status'),summary=$('map-compare-summary');
  const palette=['#0072b2','#e66b15','#b51a86','#009e73','#d55e00','#6f5acb','#202c44','#b79a00'];
  const entries=new Map();let width=1,height=1,ratio=1,scale=1,cx=0,cy=0,origin=null,drag=null,listRequest=null;
  let bagTrack=[],currentGPS=null,gpsFresh=false;
  const visible=()=>window.dashboardModes?.current==='map-compare';
  const selected=()=>[...entries.values()].filter(e=>e.selected);
  const loaded=()=>selected().filter(e=>e.data);
  const screen=p=>[width/2+(p.e-cx)*scale,height/2-(p.n-cy)*scale];
  function ecef(lat,lon){
    lat*=Math.PI/180;lon*=Math.PI/180;
    const e2=6.6943799901413165e-3,n=6378137/Math.sqrt(1-e2*Math.sin(lat)**2);
    return [n*Math.cos(lat)*Math.cos(lon),n*Math.cos(lat)*Math.sin(lon),n*(1-e2)*Math.sin(lat)];
  }
  function project(points){
    const lat=origin[0]*Math.PI/180,lon=origin[1]*Math.PI/180,base=ecef(...origin);
    return points.map(p=>{const [x,y,z]=ecef(p.lat,p.lon).map((v,i)=>v-base[i]);
      return {...p,e:-Math.sin(lon)*x+Math.cos(lon)*y,n:-Math.sin(lat)*Math.cos(lon)*x-Math.sin(lat)*Math.sin(lon)*y+Math.cos(lat)*z};});
  }
  function updateSummary(){
    const all=selected(),ready=loaded();
    summary.textContent=all.length?`${all.length}개 선택 · ${ready.length}개 표시 · ${ready.reduce((n,e)=>n+e.data.point_count,0).toLocaleString()}점`:'비교할 MAP을 체크하세요.';
    canvas.dataset.mapCount=String(ready.length);
    canvas.dataset.layers=JSON.stringify(ready.map(e=>({filename:e.name,opacity:e.opacity,color:e.color,points:e.xy.length})));
    canvas.dataset.bagPointCount=String($('map-compare-bag-show').checked?bagTrack.length:0);
    canvas.dataset.currentLat=$('map-compare-current-show').checked&&currentGPS?String(currentGPS.lat):'';
    canvas.dataset.currentLon=$('map-compare-current-show').checked&&currentGPS?String(currentGPS.lon):'';
    canvas.dataset.gpsFresh=String(gpsFresh);
  }
  function draw(){
    if(!visible())return;
    ctx.clearRect(0,0,width,height);ctx.fillStyle='#f8fafc';ctx.fillRect(0,0,width,height);
    const step=Math.pow(10,Math.ceil(Math.log10(65/scale)));
    ctx.strokeStyle='#e2e8f0';ctx.lineWidth=1;ctx.beginPath();
    for(let e=Math.ceil((cx-width/2/scale)/step)*step;e<cx+width/2/scale;e+=step){const x=screen({e,n:0})[0];ctx.moveTo(x,0);ctx.lineTo(x,height);}
    for(let n=Math.ceil((cy-height/2/scale)/step)*step;n<cy+height/2/scale;n+=step){const y=screen({e:0,n})[1];ctx.moveTo(0,y);ctx.lineTo(width,y);}
    ctx.stroke();
    for(const entry of loaded()){
      if(entry.opacity===0)continue;
      // Composite once per map so dense overlapping dots keep the chosen opacity.
      paint.clearRect(0,0,width,height);paint.strokeStyle=entry.color;paint.fillStyle=entry.color;paint.lineWidth=1;
      const points=entry.xy;
      if($('map-compare-lines').checked){
        paint.beginPath();points.forEach((p,i)=>{const [x,y]=screen(p);if(!i||p.break_before)paint.moveTo(x,y);else paint.lineTo(x,y);});paint.stroke();
      }
      if($('map-compare-points').checked){
        paint.beginPath();for(const p of points){const [x,y]=screen(p);if(x< -3||x>width+3||y< -3||y>height+3)continue;paint.moveTo(x+1.7,y);paint.arc(x,y,1.7,0,Math.PI*2);}paint.fill();
      }
      if($('map-compare-points').checked||$('map-compare-lines').checked){
        paint.lineWidth=1.8;paint.beginPath();const [sx,sy]=screen(points[0]),[ex,ey]=screen(points.at(-1));
        paint.arc(sx,sy,5,0,Math.PI*2);paint.stroke();paint.strokeRect(ex-4,ey-4,8,8);
      }
      ctx.save();ctx.globalAlpha=entry.opacity;ctx.drawImage(buffer,0,0,buffer.width,buffer.height,0,0,width,height);ctx.restore();
    }
    if($('map-compare-bag-show').checked&&bagTrack.length){
      paint.clearRect(0,0,width,height);paint.strokeStyle='#0d9488';paint.fillStyle='#0d9488';paint.lineWidth=1;
      paint.beginPath();bagTrack.forEach((p,i)=>{const [x,y]=screen(p);if(!i||p.break_before||p.break)paint.moveTo(x,y);else paint.lineTo(x,y);});paint.stroke();
      if($('map-compare-points').checked){paint.beginPath();for(const p of bagTrack){const [x,y]=screen(p);if(x< -3||x>width+3||y< -3||y>height+3)continue;paint.moveTo(x+1.5,y);paint.arc(x,y,1.5,0,Math.PI*2);}paint.fill();}
      ctx.save();ctx.globalAlpha=Number($('map-compare-bag-opacity').value)/100;ctx.drawImage(buffer,0,0,buffer.width,buffer.height,0,0,width,height);ctx.restore();
    }
    if($('map-compare-current-show').checked&&currentGPS){
      const [x,y]=screen(currentGPS);ctx.save();ctx.fillStyle=gpsFresh?'#dc2626':'#64748b';ctx.strokeStyle='white';ctx.lineWidth=2.5;
      ctx.beginPath();ctx.moveTo(x,y-9);ctx.lineTo(x+9,y);ctx.lineTo(x,y+9);ctx.lineTo(x-9,y);ctx.closePath();ctx.fill();ctx.stroke();
      ctx.font='bold 12px sans-serif';ctx.lineWidth=4;const text=gpsFresh?'현재 GPS':'마지막 GPS';ctx.strokeText(text,x+14,y-12);ctx.fillText(text,x+14,y-12);ctx.restore();
    }
    ctx.fillStyle='#64748b';ctx.font='12px sans-serif';ctx.fillText(`격자 ${step} m`,16,70);
    if(!loaded().length&&!($('map-compare-bag-show').checked&&bagTrack.length)&&!($('map-compare-current-show').checked&&currentGPS)){ctx.textAlign='center';ctx.fillText('왼쪽 목록에서 비교할 MAP 파일을 체크하세요.',width/2,height/2);ctx.textAlign='left';}
    updateSummary();
  }
  function fit(){
    if(!visible())return;
    let minE=Infinity,maxE=-Infinity,minN=Infinity,maxN=-Infinity;
    const include=p=>{minE=Math.min(minE,p.e);maxE=Math.max(maxE,p.e);minN=Math.min(minN,p.n);maxN=Math.max(maxN,p.n);};
    for(const e of loaded())for(const p of e.xy)include(p);
    if($('map-compare-bag-show').checked)bagTrack.forEach(include);
    if($('map-compare-current-show').checked&&currentGPS)include(currentGPS);
    if(Number.isFinite(minE)){cx=(minE+maxE)/2;cy=(minN+maxN)/2;scale=Math.max(.00001,Math.min(Math.max(40,width-100)/Math.max(10,maxE-minE),Math.max(40,height-160)/Math.max(10,maxN-minN)));}
    draw();
  }
  function resize(){
    if(!visible())return;
    const r=canvas.getBoundingClientRect();if(!r.width||!r.height)return;
    width=r.width;height=r.height;ratio=window.devicePixelRatio||1;
    canvas.width=buffer.width=Math.round(width*ratio);canvas.height=buffer.height=Math.round(height*ratio);
    ctx.setTransform(ratio,0,0,ratio,0,0);paint.setTransform(ratio,0,0,ratio,0,0);draw();
  }
  function rowStatus(entry){
    entry.note.dataset.error=String(Boolean(entry.error));
    entry.note.textContent=entry.error||(entry.request?'불러오는 중…':entry.data?`${entry.data.point_count.toLocaleString()}점 · ${entry.data.source}`:'체크하면 표시합니다.');
  }
  async function load(entry){
    entry.request?.abort();const request=new AbortController();entry.request=request;entry.error='';rowStatus(entry);
    try{
      const response=await fetch('/api/map-compare/maps/'+encodeURIComponent(entry.name),{cache:'no-store',signal:request.signal});
      if(!response.ok)throw Error(await response.text());const data=await response.json();
      if(entry.request!==request||!entry.selected||entries.get(entry.name)!==entry)return;
      if(!origin)origin=[data.points[0].lat,data.points[0].lon];
      entry.data=data;entry.xy=project(data.points);fit();
    }catch(error){if(entry.request===request&&error.name!=='AbortError')entry.error=error.message;}
    finally{if(entry.request===request){entry.request=null;rowStatus(entry);draw();}}
  }
  function addRow(name,index){
    const entry={name,color:palette[index%palette.length],opacity:.8,selected:false,data:null,xy:[],error:'',request:null};
    const row=document.createElement('div');row.className='map-compare-file';row.dataset.filename=name;row.style.setProperty('--map-color',entry.color);entry.row=row;
    const label=document.createElement('label'),check=document.createElement('input'),text=document.createElement('span');
    check.type='checkbox';check.dataset.mapSelect='';text.textContent=name;label.append(check,text);
    const controls=document.createElement('div');controls.className='map-compare-layer-controls';
    const color=document.createElement('input');color.type='color';color.value=entry.color;color.setAttribute('aria-label',name+' 색상');
    const caption=document.createElement('span');caption.textContent='투명도';
    const range=document.createElement('input');range.type='range';range.min='0';range.max='100';range.step='1';range.value='80';range.setAttribute('aria-label',name+' 투명도');
    const output=document.createElement('output');output.textContent='80%';
    const note=document.createElement('small');note.setAttribute('role','status');entry.note=note;entry.check=check;
    controls.append(color,caption,range,output);row.append(label,controls,note);entries.set(name,entry);files.append(row);rowStatus(entry);
    check.onchange=()=>{entry.selected=check.checked;if(entry.selected){if(entry.data)fit();else load(entry);}else{entry.request?.abort();entry.request=null;rowStatus(entry);draw();}updateSummary();};
    range.oninput=()=>{entry.opacity=Number(range.value)/100;output.textContent=range.value+'%';draw();};
    color.oninput=()=>{entry.color=color.value;row.style.setProperty('--map-color',entry.color);draw();};
  }
  function filter(){const query=$('map-compare-search').value.trim().toLocaleLowerCase();for(const e of entries.values())e.row.hidden=!e.name.toLocaleLowerCase().includes(query);}
  async function refresh(){
    listRequest?.abort();const request=new AbortController();listRequest=request;$('map-compare-refresh').disabled=true;status.textContent='파일 목록 불러오는 중…';
    try{
      const response=await fetch('/api/map-compare/maps',{cache:'no-store',signal:request.signal});if(!response.ok)throw Error(await response.text());
      const data=await response.json();if(listRequest!==request)return;
      const names=new Set(data.maps);
      for(const [name,e] of entries)if(!names.has(name)){e.request?.abort();e.row.remove();entries.delete(name);}
      data.maps.forEach((name,i)=>{if(!entries.has(name))addRow(name,i);else files.append(entries.get(name).row);});
      filter();status.textContent=data.maps.length?`${data.maps.length}개 파일 · 비교할 파일을 여러 개 체크하세요.`:'선택할 MAP 파일이 없습니다.';
      // A refreshed filename may contain new GPS data. Reload selected maps.
      for(const e of selected()){e.data=null;e.xy=[];load(e);}draw();
    }catch(error){if(error.name!=='AbortError')status.textContent='파일 목록 오류: '+error.message;}
    finally{if(listRequest===request){listRequest=null;$('map-compare-refresh').disabled=false;}}
  }
  function activate(){
    if(visible()){resize();refresh();}
    else{listRequest?.abort();for(const e of entries.values()){e.request?.abort();e.request=null;rowStatus(e);}drag=null;}
  }
  function centerCurrent(){if(!currentGPS||!$('map-compare-current-show').checked)return;cx=currentGPS.e;cy=currentGPS.n;draw();}
  window.mapCompare={
    setBagTrack(points){
      if(points.length&&!origin)origin=[points[0].lat,points[0].lon];
      bagTrack=points.length?project(points):[];if(bagTrack.length)fit();else draw();
    },
    setCurrent(point,fresh){
      const first=!currentGPS;if(point&&!origin)origin=[point.lat,point.lon];
      currentGPS=point?project([point])[0]:null;gpsFresh=Boolean(fresh);
      if($('map-compare-current-show').checked&&$('map-compare-follow').checked&&currentGPS)centerCurrent();
      else if(first&&currentGPS&&!loaded().length&&!bagTrack.length)fit();else draw();
    },centerCurrent,draw
  };
  $('map-compare-center').onclick=centerCurrent;
  $('map-compare-follow').onchange=()=>{if($('map-compare-follow').checked)centerCurrent();};
  $('map-compare-bag-opacity').oninput=()=>{$('map-compare-bag-alpha').textContent=$('map-compare-bag-opacity').value+'%';draw();};
  $('map-compare-refresh').onclick=refresh;$('map-compare-fit').onclick=fit;$('map-compare-search').oninput=filter;
  $('map-compare-points').onchange=draw;$('map-compare-lines').onchange=draw;
  canvas.addEventListener('wheel',event=>{event.preventDefault();$('map-compare-follow').checked=false;const r=canvas.getBoundingClientRect(),x=event.clientX-r.left-width/2,y=event.clientY-r.top-height/2;
    const next=Math.max(.00001,Math.min(100000,scale*Math.exp(-event.deltaY*.001)));cx+=x/scale-x/next;cy-=y/scale-y/next;scale=next;draw();},{passive:false});
  canvas.addEventListener('pointerdown',event=>{$('map-compare-follow').checked=false;drag=[event.clientX,event.clientY];canvas.setPointerCapture(event.pointerId);});
  canvas.addEventListener('pointermove',event=>{if(!drag)return;cx-=(event.clientX-drag[0])/scale;cy+=(event.clientY-drag[1])/scale;drag=[event.clientX,event.clientY];draw();});
  for(const event of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(event,()=>{drag=null;});
  canvas.addEventListener('dblclick',fit);new ResizeObserver(resize).observe(canvas);
  window.addEventListener('dashboard:modechange',activate);window.addEventListener('pagehide',()=>{listRequest?.abort();for(const e of entries.values())e.request?.abort();});
  window.addEventListener('pageshow',()=>{if(visible())activate();});activate();
})();
