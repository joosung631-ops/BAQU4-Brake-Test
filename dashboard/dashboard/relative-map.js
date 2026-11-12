(() => {
  const gps = document.getElementById('gps-view'), pane = document.getElementById('relative-view');
  const canvas = document.getElementById('relative-canvas'), status = document.getElementById('relative-status');
  let loaded = false, gl, program, points, path, center, extent, azimuth = 0, elevation = Math.PI/2, zoom = 1, drag;
  let socket, retry, session, low = [Infinity,Infinity,Infinity], high = [-Infinity,-Infinity,-Infinity];
  let activePage = true, revision=0;
  const slots=new Map(), coordinates=new Float32Array(500000*3);
  const surfaceStatus=document.getElementById('relative-surface-status');
  let surfaceMode=false,surface,worker,meshEpoch=0;
  document.getElementById('relative-surface').onclick=()=>{
    surfaceMode=!surfaceMode;
    document.getElementById('relative-surface').setAttribute('aria-pressed',String(surfaceMode));
    restartSurface();draw();
  };
  function stopSurface(){if(worker)worker.terminate();worker=null;meshEpoch++;if(surface)surface.count=0;}
  function restartSurface(){
    stopSurface();
    surfaceStatus.textContent=surfaceMode?'면 계산 대기…':'점군 표시';
    if(!surfaceMode || !points || pane.hidden || document.hidden || !activePage)return;
    worker=new Worker('/relative-surface.js');
    worker.onmessage=({data})=>{
      if(data.epoch!==meshEpoch || !surfaceMode)return;
      gl.bindBuffer(gl.ARRAY_BUFFER,surface.buffer);gl.bufferSubData(gl.ARRAY_BUFFER,0,data.vertices);
      surface.count=data.vertices.length/3;
      surfaceStatus.textContent=`면 미리보기 · ${data.faces.toLocaleString()}개`+(data.limited?' · 표시 한도 도달':'')+' · 연결되지 않은 점은 유지';
      draw();
    };
    worker.onerror=()=>{stopSurface();surfaceStatus.textContent='면 계산 실패 · 점군을 표시합니다';draw();};
    const values=coordinates.slice(0,points.count*3);
    worker.postMessage({reset:true,epoch:meshEpoch,values:values.buffer},[values.buffer]);
  }
  const toggle = (relative) => {
    gps.hidden = relative; pane.hidden = !relative;
    document.getElementById('show-gps').setAttribute('aria-pressed',String(!relative));
    document.getElementById('show-relative').setAttribute('aria-pressed',String(relative));
    if (relative && !loaded) { loaded = true; load(); }
    else if (relative) { connect(); draw(); }
    else disconnect();
  };
  document.getElementById('show-gps').onclick = () => toggle(false);
  document.getElementById('show-relative').onclick = () => toggle(true);
  document.getElementById('relative-top').onclick = () => { azimuth=0; elevation=Math.PI/2; zoom=1; draw(); };
  document.getElementById('relative-angle').onclick = () => { azimuth=-.4; elevation=.65; zoom=1; draw(); };
  function shader(kind, source) {
    const shader = gl.createShader(kind); gl.shaderSource(shader,source); gl.compileShader(shader);
    if (!gl.getShaderParameter(shader,gl.COMPILE_STATUS)) throw new Error('지도 셰이더 초기화 실패');
    return shader;
  }
  function buffer(capacity) {
    const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER,b); gl.bufferData(gl.ARRAY_BUFFER,capacity*12,gl.DYNAMIC_DRAW);
    return {buffer:b,count:0,capacity};
  }
  function load() {
    try {
      gl=canvas.getContext('webgl',{antialias:true,preserveDrawingBuffer:true});
      if (!gl) throw new Error('이 브라우저에서 WebGL을 사용할 수 없습니다.');
      center=[0,0,0];extent=20;
      program=gl.createProgram();
      gl.attachShader(program,shader(gl.VERTEX_SHADER,`attribute vec3 position; uniform mat4 matrix; uniform vec2 heightRange; uniform float track; varying vec3 color;
        void main(){ gl_Position=matrix*vec4(position,1.0); gl_PointSize=2.0;
        float h=clamp((position.z-heightRange.x)/max(1.0,heightRange.y-heightRange.x),0.0,1.0);
        color=track>0.5?vec3(1.0,0.25,0.2):mix(vec3(0.15,0.5,0.85),vec3(0.9,0.85,0.2),h); }`));
      gl.attachShader(program,shader(gl.FRAGMENT_SHADER,'precision mediump float; varying vec3 color; void main(){gl_FragColor=vec4(color,1.0);}'));
      gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw new Error('지도 렌더러 초기화 실패');
      gl.useProgram(program);
      points=buffer(500000);path=buffer(20000);surface=buffer(90000*3);
      connect();draw();
    } catch(error) {status.textContent=error.message;}
  }
  function disconnect() {
    clearTimeout(retry);stopSurface();
    if (socket) { const old=socket;socket=null;old.close(); }
  }
  function connect() {
    if (!points || pane.hidden || document.hidden || !activePage || socket) return;
    restartSurface();
    status.textContent='LiDAR 지도 연결 중…';
    const ws=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/ws/lidar-map`);
    ws.binaryType='arraybuffer';socket=ws;
    ws.onmessage=event=>{
      if(socket!==ws)return;
      try {
        const payload=event.data, view=new DataView(payload), headerSize=view.getUint32(0,true);
        if(headerSize>8192 || headerSize+4>payload.byteLength)throw new Error('지도 헤더 오류');
        const h=JSON.parse(new TextDecoder().decode(new Uint8Array(payload,4,headerSize)));
        const start=4+headerSize,split=start+h.point_count*16;
        if(payload.byteLength!==split+h.path_count*12)throw new Error('지도 크기 오류');
        if(h.reset || session!==h.session){
          session=h.session;points.count=path.count=revision=0;slots.clear();low=[Infinity,Infinity,Infinity];high=[-Infinity,-Infinity,-Infinity];
          center=[0,0,0];extent=20;zoom=1;restartSurface();
        }
        if(h.point_start!==revision || h.path_start!==path.count)throw new Error('지도 순서 오류 · 재연결');
        const cloud=new Float32Array(h.point_count*3), trace=new Float32Array(payload.slice(split));
        function append(target,data){
          if(target.count+data.length/3>target.capacity)throw new Error('지도 표시 한도 초과');
          if(data.length){gl.bindBuffer(gl.ARRAY_BUFFER,target.buffer);gl.bufferSubData(gl.ARRAY_BUFFER,target.count*12,data);target.count+=data.length/3;}
        }
        const changes=worker?new Float32Array(h.point_count*4):null;
        gl.bindBuffer(gl.ARRAY_BUFFER,points.buffer);
        for(let i=0;i<h.point_count;i++){
          const offset=start+i*16,id=view.getUint32(offset,true);
          if(id>=points.capacity)throw new Error('지도 점 ID 오류');
          let slot=slots.get(id);
          if(slot===undefined){slot=points.count++;slots.set(id,slot);}
          for(let axis=0;axis<3;axis++)cloud[i*3+axis]=view.getFloat32(offset+4+axis*4,true);
          const xyz=cloud.subarray(i*3,i*3+3);
          coordinates.set(xyz,slot*3);
          if(changes){changes[i*4]=slot;changes.set(xyz,i*4+1);}
          gl.bufferSubData(gl.ARRAY_BUFFER,slot*12,xyz);
        }
        if(changes?.length)worker.postMessage({epoch:meshEpoch,values:changes.buffer},[changes.buffer]);
        revision=h.point_end;append(path,trace);
        for(let i=0;i<cloud.length;i++){const axis=i%3;low[axis]=Math.min(low[axis],cloud[i]);high[axis]=Math.max(high[axis],cloud[i]);}
        if(points.count){center=low.map((x,i)=>(x+high[i])/2);extent=Math.max(20,...low.map((x,i)=>high[i]-x));}
        const state=h.status||{},lag=h.total_points-points.count;
        status.textContent=`${h.active?'정합 중':'수신 대기 / 일시정지'} · ${Number(state.scans||0).toLocaleString()}스캔 · 표시 ${points.count.toLocaleString()}점 · 2회 이상 관측 평균`+
          (lag>0?` · 지도 복원 ${lag.toLocaleString()}점 남음`:'')+
          ` · 처리 ${Number(state.processing_ms||0).toFixed(0)}ms · 큐 누락 ${state.dropped||0}`+
          (state.limited?' · 지도 저장 한도 도달':'')+
          (!h.active && state.message?` · ${state.message}`:'');
        draw();
        ws.send(JSON.stringify({session:h.session,points:revision,path:path.count}));
      }catch(error){status.textContent=error.message;ws.close();}
    };
    ws.onclose=()=>{if(socket!==ws)return;socket=null;status.textContent='지도 연결 끊김 · 다시 연결 중…';retry=setTimeout(connect,1500);};
    ws.onerror=()=>ws.close();
  }
  document.addEventListener('visibilitychange',()=>{if(document.hidden)disconnect();else connect();});
  window.addEventListener('pagehide',()=>{activePage=false;disconnect();});
  window.addEventListener('pageshow',e=>{if(e.persisted){activePage=true;connect();}});
  function draw() {
    if (!points || pane.hidden || gl.isContextLost()) return;
    const rect=canvas.getBoundingClientRect(),ratio=Math.min(window.devicePixelRatio||1,2);
    canvas.width=Math.max(1,Math.round(rect.width*ratio));canvas.height=Math.max(1,Math.round(rect.height*ratio));
    gl.viewport(0,0,canvas.width,canvas.height);gl.clearColor(.045,.065,.095,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
    const ca=Math.cos(azimuth),sa=Math.sin(azimuth),se=Math.sin(elevation),ce=Math.cos(elevation);
    const base=1.7*zoom/extent, sx=base*Math.min(1,rect.height/rect.width),sy=base*Math.min(1,rect.width/rect.height),sz=.5/extent;
    const x=[ca*sx,sa*sx,0],y=[-sa*se*sy,ca*se*sy,ce*sy],z=[sa*ce*sz,-ca*ce*sz,se*sz];
    const dot=(v)=>v.reduce((sum,a,i)=>sum+a*center[i],0);
    const matrix=new Float32Array([x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,-dot(x),-dot(y),-dot(z),1]);
    gl.useProgram(program);
    gl.uniform2f(gl.getUniformLocation(program,'heightRange'),points.count?low[2]:0,points.count?high[2]:1);
    gl.uniformMatrix4fv(gl.getUniformLocation(program,'matrix'),false,matrix);
    const position=gl.getAttribLocation(program,'position');gl.enableVertexAttribArray(position);
    function render(b,kind,track){gl.bindBuffer(gl.ARRAY_BUFFER,b.buffer);gl.vertexAttribPointer(position,3,gl.FLOAT,false,0,0);gl.uniform1f(gl.getUniformLocation(program,'track'),track);gl.drawArrays(kind,0,b.count);}
    gl.enable(gl.DEPTH_TEST);
    if(surfaceMode && surface.count){
      gl.enable(gl.POLYGON_OFFSET_FILL);gl.polygonOffset(1,1);render(surface,gl.TRIANGLES,0);gl.disable(gl.POLYGON_OFFSET_FILL);
    }
    render(points,gl.POINTS,0);gl.disable(gl.DEPTH_TEST);render(path,gl.LINE_STRIP,1);
  }
  canvas.addEventListener('pointerdown',e=>{drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);});
  canvas.addEventListener('pointermove',e=>{if(!drag)return;azimuth-=(e.clientX-drag[0])*.007;elevation=Math.max(.05,Math.min(Math.PI/2,elevation+(e.clientY-drag[1])*.007));drag=[e.clientX,e.clientY];draw();});
  canvas.addEventListener('pointerup',()=>drag=null);canvas.addEventListener('pointercancel',()=>drag=null);
  canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.2,Math.min(20,zoom*Math.exp(-e.deltaY*.001)));draw();},{passive:false});
  canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();disconnect();points=null;status.textContent='그래픽 연결이 중단되었습니다. 페이지를 새로고침해 주세요.';});
  new ResizeObserver(draw).observe(canvas);
})();
