/* Three concurrent sensors, one acknowledged stream; no external assets. */
(() => {
  const $=id=>document.getElementById(id), pane=$('brake-view');if(!pane)return;
  const canvas=$('brake-cloud'), coneCanvas=$('brake-cones'), gpsCanvas=$('brake-gps'), video=$('brake-video');
  let socket=null,retry=null,ended=false,lastStatus=0,state=null,firstState=true;
  let session=null,gps=[],lastGPS='',sourceBusy=false,sourceRevision=0;
  let media=null,buffer=null,url=null,videoQueue=[],videoStarted=false,renderEpoch=0;
  let cloudTimes=[];
  let courseLines={},lineMask=0,stopEvidence={state:0},stopReason='';
  let driverPrediction=null,driverPredictionTime=0;
  let driveTelemetry=null,driveTelemetryTime=0;
  function driveStatus(){
    const live=state?.mode==='live',connected=!!lastStatus&&Date.now()-lastStatus<2500;
    const t=live&&connected&&performance.now()-driveTelemetryTime<1000?driveTelemetry:null,d=t?.drive;
    const sourceSpeed=connected&&state?.fresh?.odom?state.speed_kph:null;
    const speed=t?t.speed_mps==null?null:t.speed_mps*3.6:sourceSpeed;
    $('brake-current-speed').textContent=speed==null?'— km/h (지연/대기)':speed.toFixed(1)+' km/h · GNSS';
    $('brake-drive-mode').textContent=!live?'bag 센서 보기 · 실시간 주행 상태 표시 안 함':!t?'주행 노드 수신 대기 / 지연':t.publish_cmd?'/cmd 발행 켜짐':'모의 계산 · /cmd 발행 꺼짐';
    const set=(id,text,tone='')=>{const el=$(id);el.textContent=text;el.dataset.tone=tone;};
    set('brake-accelerating',!d?'확인 불가':t.brake?'아니오':speed==null?'속도 수신 대기':d.accelerating?'예 (명령 기준)':'아니오',d?.accelerating?'active':'');
    set('brake-target-reached',!d?'확인 불가':(d.reached_max_speed?'도달':'미도달')+' · '+d.max_speed_kph.toFixed(1)+' km/h',d?.reached_max_speed?'active':'');
    set('brake-braking',!d?'확인 불가':t.brake?(t.publish_cmd?'제동 명령 발행 중':'제동 계산 · 발행 꺼짐'):'아니오',t?.brake?'brake':'');
    const distance=d?.stop_distance_m,threshold=d?.brake_distance_m;
    const stopBraking=d?.reason==='stop_row_braking'&&t.brake;
    const protecting=d&&t.brake&&d.reason!=='waiting_for_sensors'&&!stopBraking;
    const tracked=Number.isFinite(distance);
    let stopText='확인 불가',tone='';
    if(d){
      if(stopBraking){stopText=t.publish_cmd?'정지선 제동 시작 · 명령 유지':'정지선 제동 계산 · 발행 꺼짐';tone='brake';}
      else if(protecting){stopText=t.publish_cmd?'보호정지 · 제동 명령 유지':'보호정지 계산 · 발행 꺼짐';tone='brake';}
      else if(tracked&&!t.brake){stopText=d.stop_state==='confirmed'?'정지선 인식 · 제동 거리 대기':'정지선 추적 · 제동 거리 대기';tone='active';}
      else if(d.stop_state==='candidate')stopText='정지선 후보 · 확인 중';
      else if(d.stop_state==='unavailable')stopText='인식 상태 수신 지연';
      else if(d.stop_state==='none'||d.stop_state==='confirmed')stopText='정지선 추적 대기';
      else stopText='상세 상태는 주행 노드 다음 실행부터 표시';
    }
    set('brake-stop-phase',stopText,tone);
    $('brake-stop-distance').textContent=tracked?distance.toFixed(2)+' m (라이다 기준 추정)':'—';
    $('brake-trigger-distance').textContent=Number.isFinite(threshold)?threshold.toFixed(2)+' m'+(t.brake?' (제동 직전 기준)':' (현재 속도 기준)'):'—';
    $('brake-drive-target').textContent=d?d.goal_kph.toFixed(1)+' / '+d.command_kph.toFixed(1)+' km/h':'—';
    const reasons={waiting_for_sensors:'센서 / 유효 경로 대기',accelerate:'최고 목표 속도로 가속 단계',maintain:'설정 유지 속도로 주행',stop_row_braking:'정지선 제동 · 정지 유지',sensor_or_path_lost:'센서 / 경로 소실 · 정지 유지',another_cmd_publisher:'다른 /cmd 발행자 감지 · 정지 유지',bag_replay_detected:'bag 재생 감지 · 정지 유지',invalid_pursuit:'추종 계산 실패',clock_reversed:'시계 역행 · 정지 유지'};
    $('brake-drive-reason').textContent=d?(reasons[d.reason]||d.reason):'주행 노드를 실행하면 상태가 표시됩니다.';
  }
  let count=0,coneCount=0,coneValid=false,ground=null,center=[-15,0,0],extent=35,azimuth=-1.5,elevation=.65,zoom=1,drag=null;
  const cloudView=makeView(canvas,false),coneView=makeView(coneCanvas,true);
  const active=()=>!ended&&!document.hidden&&window.dashboardModes?.current==='brake';
  const format=n=>(n/1e6).toFixed(1)+'MB';
  function predictionModel(){
    if(!$('brake-show-prediction').checked)return null;
    if($('brake-prediction-mode').value==='manual')return {angle_deg:Number($('brake-steering').value),wheelbase_m:1.328,width_m:1.280,lidar_x_m:.559,lidar_y_m:0,yaw_deg:0};
    return state?.mode==='live'&&driverPrediction?.sensors_fresh&&performance.now()-driverPredictionTime<1000?driverPrediction:null;
  }
  function predictionInfo(){
    const manual=$('brake-prediction-mode').value==='manual',m=predictionModel();
    $('brake-steering').disabled=!manual;
    $('brake-steering-value').textContent=Number($('brake-steering').value).toFixed(1)+'°';
    $('brake-prediction-info').textContent=!$('brake-show-prediction').checked?'예상 진행선 숨김':!m?
      (state?.mode==='bag'?'bag 보기: 가상 조향을 선택하세요':'주행 계산값 / 유효 센서 대기'):
      (manual?'가상 조향':'주행 계산값'+(m.publish_cmd?' · 발행 켜짐':' · 발행 꺼짐'))+' · '+m.angle_deg.toFixed(1)+'° · '+(Math.abs(m.angle_deg)<.05?'직진':m.angle_deg>0?'좌회전':'우회전')+
      (!manual&&m.brake?' · 제동 중: 방향 참고':'')+' · 노랑 10m 기하 예측 / 얇은 선 차폭 참고';
  }
  function clearLines(){courseLines={};lineMask=0;stopEvidence={state:0};lineInfo();}
  function lineInfo(){
    const names=[];if(lineMask&1)names.push('좌 경계');if(lineMask&2)names.push('우 경계');
    if(lineMask&4)names.push('가운데 추종선');if(lineMask&8)names.push(stopEvidence.state===2?'정지열 반복 확인':'가로 정지선 후보');
    $('brake-line-info').textContent=names.length?names.join(' · '):'코스 선 대기 / 검출 조건 부족';
    const row=stopEvidence,reasons={boundary_stale:'좌우 경계 대기 / 갱신 지연',no_corridor:'양쪽 경계 조건 부족',ground_unreliable:'지면 추정 확인 필요',no_transverse_support:'가로 배열 대기'};
    const info=$('brake-stop-info');
    info.textContent=row.state?('정지열 '+(row.state===2?'반복 확인':'후보')+' · '+(row.distance/100).toFixed(1)+'m · '+row.cells+'개 지지 셀 · '+(row.span/100).toFixed(1)+'m 폭'+(row.state===1&&stopReason==='speed_unavailable'?' · 속도 정보 대기':'')):
      '원거리 정지열: '+(reasons[stopReason]||'관측 대기');
    info.className=row.state===2?'brake-stop-confirmed':row.state===1?'brake-stop-candidate':'';
  }
  async function control(data){
    try{
      const response=await fetch('/api/brake/control',{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Control':'1'},body:JSON.stringify(data)});
      const result=await response.json();if(!response.ok)throw Error(result.error||'요청 실패');return true;
    }catch(error){$('brake-status').textContent=error.message;return false;}
  }
  async function bags(){
    try{
      const response=await fetch('/api/brake/bags'), data=await response.json();if(!response.ok)throw Error(data.error);
      const select=$('brake-bag'), previous=select.value;
      select.replaceChildren(...data.bags.map(b=>{const o=new Option(b.id+(!b.camera?' · 영상 없음':'')+(!b.gps?' · GPS 없음':''),b.id);o.disabled=!b.supported;return o;}));
      if([...select.options].some(o=>o.value===previous))select.value=previous;
      if(!data.bags.length)$('brake-status').textContent='라이다가 기록된 bag이 없습니다.';
    }catch(error){$('brake-status').textContent=error.message;}
  }
  $('brake-source').onchange=async()=>{
    sourceRevision++;
    const mode=$('brake-source').value;$('brake-bag-controls').hidden=mode!=='bag';
    if(mode==='bag')await bags();else await control({action:'source',mode:'live'});
  };
  $('brake-refresh').onclick=bags;
  $('brake-load').onclick=async()=>{sourceRevision++;sourceBusy=true;await control({action:'source',mode:'bag',bag:$('brake-bag').value});sourceBusy=false;};
  $('brake-play').onclick=()=>control({action:'play'});
  $('brake-pause').onclick=()=>control({action:'pause'});
  $('brake-rate').onchange=()=>control({action:'rate',rate:Number($('brake-rate').value)});
  $('brake-seek').onchange=()=>control({action:'seek',position:Number($('brake-seek').value)});

  function clearVideo(){
    video.pause();video.removeAttribute('src');video.load();
    if(url)URL.revokeObjectURL(url);url=null;media=buffer=null;videoQueue=[];videoStarted=false;
  }
  function pump(){
    if(!buffer||buffer.updating||!videoQueue.length)return;
    try{videoStarted=true;buffer.appendBuffer(videoQueue.shift());}catch(error){$('brake-video-message').textContent='영상 재연결: '+error.message;socket?.close();}
  }
  function initializeVideo(mime, ws){
    clearVideo();
    if(!window.MediaSource||!MediaSource.isTypeSupported(mime))throw Error('브라우저의 H.264 재생 지원을 확인하세요.');
    media=new MediaSource();const owner=media;url=URL.createObjectURL(media);video.src=url;
    media.addEventListener('sourceopen',()=>{
      if(socket!==ws||media!==owner)return;
      try{
        buffer=media.addSourceBuffer(mime);
        buffer.addEventListener('updateend',()=>{
          if(socket!==ws||media!==owner||!buffer)return;
          if(videoStarted){videoStarted=false;if(ws.readyState===WebSocket.OPEN)ws.send('ack:2:'+renderEpoch);}
          if(buffer.buffered.length){
            const end=buffer.buffered.end(buffer.buffered.length-1);
            if(end-video.currentTime>1)video.currentTime=Math.max(0,end-.15);
            if(video.currentTime>12&&buffer.buffered.start(0)<video.currentTime-8){buffer.remove(0,video.currentTime-5);return;}
          }
          pump();video.play().catch(()=>{});
        });pump();
      }catch(error){$('brake-video-message').textContent=error.message;ws.close();}
    },{once:true});
  }
  function status(h){
    state=h;lastStatus=Date.now();
    if(h.phase==='error'&&!h.fresh){$('brake-status').textContent=h.error||'입력 연결 중단';$('brake-video-message').hidden=false;$('brake-video-message').textContent='입력 연결 중단';coneValid=false;coneCount=0;coneView.set([]);clearLines();draw();canvas.style.opacity=coneCanvas.style.opacity='.35';$('brake-cone-info').textContent='검출 입력 연결 중단';return;}
    const phases={idle:'수신 대기',live:'수신 중',preparing:'bag 준비 중',ready:h.playing?'재생 중':'일시정지',error:'입력 오류'};
    $('brake-status').textContent=(h.mode==='bag'?'ROS bag · ':'실시간 · ')+(phases[h.phase]||h.phase)+(h.error?' · '+h.error:'');
    if(firstState&&!sourceBusy){
      firstState=false;
      if(sourceRevision===0){
        $('brake-source').value=h.mode;$('brake-bag-controls').hidden=h.mode!=='bag';
        const revision=sourceRevision;
        if(h.mode==='bag')bags().then(()=>{if(sourceRevision===revision)$('brake-bag').value=h.bag;});
      }
    }
    $('brake-seek').max=Math.max(.1,h.duration||0);if(document.activeElement!==$('brake-seek'))$('brake-seek').value=h.position||0;
    $('brake-time').textContent=(h.position||0).toFixed(1)+' / '+(h.duration||0).toFixed(1)+'초';
    $('brake-play').disabled=h.phase!=='ready';$('brake-pause').disabled=h.mode!=='bag';$('brake-seek').disabled=h.phase!=='ready';
    $('brake-speed').textContent=h.speed_kph==null?'— km/h':h.speed_kph.toFixed(1)+' km/h';
    const cloud=h.cloud||{};
    $('brake-cloud-info').textContent=(h.fresh?.cloud?'':'수신 지연 · ')+count.toLocaleString()+'점 · '+Number(h.lidar_hz||0).toFixed(1)+'Hz / 목표 10Hz · 처리 '+Number(cloud.processing_ms||0).toFixed(0)+'ms';
    canvas.style.opacity=h.fresh?.cloud?'1':'.35';
    ground=cloud.plane||null;draw();
    const cones=h.cones||{};
    if(!h.fresh?.cones)clearLines();
    const course=cones.course||{};
    stopReason=h.stop_row?.reason||'';lineInfo();
    $('brake-line-info').title=course.state==='ambiguous'?'복수의 코스 후보가 비슷하게 지지되어 가운데 선과 정지선을 보류했습니다.':
      course.state==='partial'?'양쪽 경계의 평행·폭·겹치는 길이 조건이 부족하여 가운데 선과 정지선을 보류했습니다.':
      '직선 코스의 기하 추정입니다. 주황은 후보, 빨강은 최근 스캔에서 거리 변화까지 반복 확인된 정지열입니다. 제동 명령이 아닙니다.';
    $('brake-stop-info').title=h.stop_row?.reason==='speed_unavailable'?'속도 정보가 없거나 오래되어 반복 확인을 보류합니다.':
      '가까운 지면 적합도만 검사합니다. 먼 노면의 경사와 명목 센서 좌표 오차는 남아 있으며, 거리는 범퍼 여유 거리가 아닙니다.';
    $('brake-cone-info').textContent=cones.error?'검출 오류 · '+cones.error:
      !h.fresh?.cones?'검출 대기 / 지연':coneCount+'개'+(cones.total>coneCount?' / '+cones.total+'개 중 가까운 순':'')+' · 검출 최대 5Hz · '+Number(cones.processing_ms||0).toFixed(0)+'ms · '+Number(h.ages?.cones||0).toFixed(1)+'초 전';
    coneCanvas.style.opacity=h.fresh?.cones?'1':'.35';
    $('brake-video-info').textContent='H.264 · '+h.video_fps+'fps · '+h.video_kbps+'kbps';
    $('brake-video-message').hidden=!!h.fresh?.camera&&video.readyState>=2;
    $('brake-video-message').textContent=h.mode==='bag'&&!h.playing?'일시정지 / 영상 수신 대기':'카메라 수신 대기 / 지연';
    if(h.budget)$('brake-budget').textContent='1GB/시간 목표 · 최근 60분 본문 '+format(h.budget.last_hour_bytes)+' · 합산 '+(h.budget.limit_bytes_s/1000).toFixed(0)+'KB/s · 라이다 우선 · '+h.viewers+'명';
    if(h.gps){
      const p=h.gps,key=p.lat+','+p.lon;
      if(key!==lastGPS){gps.push(p);if(gps.length>1200)gps.shift();lastGPS=key;}
      $('brake-gps-info').textContent=p.lat.toFixed(7)+', '+p.lon.toFixed(7)+' · '+(h.ages?.gps||0).toFixed(1)+'초 전 · 북쪽 ↑';
    }else $('brake-gps-info').textContent='GPS 수신 대기 / 위치 무효';
    drawGPS();
  }
  function connect(){
    if(!active()||socket)return;
    const ws=new WebSocket((location.protocol==='https:'?'wss:':'ws:')+'//'+location.host+'/ws/brake');socket=ws;ws.binaryType='arraybuffer';
    ws.onmessage=({data})=>{
      if(socket!==ws)return;
      try{
        if(typeof data==='string'){
          const h=JSON.parse(data);
          if(h.type==='reset'){
            renderEpoch=h.render_epoch||0;
            if(session!==h.session){session=h.session;driverPrediction=null;driveTelemetry=null;gps=[];lastGPS='';count=coneCount=0;coneValid=false;ground=null;cloudTimes=[];cloudView.set([]);coneView.set([]);clearLines();$('brake-cone-info').textContent='라바콘 검출 대기';draw();drawGPS();}
            clearVideo();
          }else if(h.type==='prediction'){
            driverPrediction=h.value;driverPredictionTime=performance.now();draw();
          }else if(h.type==='drive-status'){
            driveTelemetry=h.value;driveTelemetryTime=performance.now();driveStatus();
          }else if(h.type==='video-init')initializeVideo(h.mime,ws);
          else if(h.type==='status')status(h);
          return;
        }
        const v=new DataView(data),kind=v.getUint8(0);
        if(kind===1){
          const n=v.getUint32(1,true),offset=5+n*6;
          if(n>4000||data.byteLength<offset+3)throw Error('점군 패킷 오류');
          coneValid=!!v.getUint8(offset);coneCount=v.getUint16(offset+1,true);
          if(coneCount>64||data.byteLength<offset+3+coneCount*14||(!coneValid&&coneCount))throw Error('라바콘 패킷 오류');
          let tail=offset+3+coneCount*14;clearLines();
          if(tail<data.byteLength){
            if(data.byteLength<tail+3||v.getUint8(tail)!==76||v.getUint8(tail+1)!==49)throw Error('코스 선 패킷 오류');
            lineMask=v.getUint8(tail+2);tail+=3;if(lineMask>15||(!coneValid&&lineMask))throw Error('코스 선 상태 오류');
            for(let i=0;i<4;i++)if(lineMask&(1<<i)){
              if(tail+12>data.byteLength)throw Error('코스 선 길이 오류');
              const a=Array.from({length:6},(_,k)=>v.getInt16(tail+2*k,true)*.01);
              if(a.some(x=>Math.abs(x)>60))throw Error('코스 선 범위 오류');
              courseLines[['left','right','center','stop'][i]]=a;tail+=12;
            }
          }
          if(tail<data.byteLength){
            if(tail+3>data.byteLength||v.getUint8(tail)!==83||v.getUint8(tail+1)!==49)throw Error('정지열 패킷 오류');
            const s=v.getUint8(tail+2);tail+=3;if(s>2)throw Error('정지열 상태 오류');
            if(s){
              if(tail+18>data.byteLength)throw Error('정지열 길이 오류');
              const distance=v.getUint16(tail,true),cells=v.getUint16(tail+2,true),span=v.getUint16(tail+4,true);
              const points=Array.from({length:6},(_,k)=>v.getInt16(tail+6+k*2,true)*.01);tail+=18;
              if(distance<200||distance>4500||cells<3||cells>64||span<150||span>800||points.some(x=>Math.abs(x)>60))throw Error('정지열 범위 오류');
              stopEvidence={state:s,distance,cells,span};courseLines.stop=points;lineMask|=8;
            }
          }
          if(tail!==data.byteLength)throw Error('코스 선 패킷 크기 오류');lineInfo();
          const points=new Float32Array(n*3);
          for(let i=0;i<n*3;i++)points[i]=v.getInt16(5+i*2,true)*.01;
          count=n;cloudView.set(points);
          const centers=[],edges=[],pairs=[[0,1],[0,2],[0,4],[1,3],[1,5],[2,3],[2,6],[3,7],[4,5],[4,6],[5,7],[6,7]];
          for(let i=0;i<coneCount;i++){
            const p=offset+3+i*14,c=[0,1,2].map(k=>v.getInt16(p+2*k,true)*.01),s=[3,4,5].map(k=>v.getInt16(p+2*k,true)*.01);
            centers.push(...c);
            const corners=Array.from({length:8},(_,j)=>c.map((a,k)=>a+((j>>k&1)?1:-1)*s[k]/2));
            for(const [a,b] of pairs)edges.push(...corners[a],...corners[b]);
          }
          coneView.set(centers,edges);coneCanvas.style.opacity=coneValid?'1':'.35';
          $('brake-cone-info').textContent=coneValid?coneCount+'개 검출 · 3D 관측 상자':'검출 대기 / 지연';draw();
          const now=performance.now();cloudTimes.push(now);cloudTimes=cloudTimes.filter(t=>now-t<2500);
          const hz=cloudTimes.length>1?(cloudTimes.length-1)*1000/(now-cloudTimes[0]):0;
          ws.send('ack:1:'+renderEpoch);$('brake-cloud-info').textContent=count.toLocaleString()+'점 · '+hz.toFixed(1)+'Hz / 목표 10Hz';
        }else if(kind===2){
          if(videoQueue.length>=3)throw Error('영상 처리 지연');videoQueue.push(data.slice(1));pump();
        }else throw Error('알 수 없는 센서 패킷');
      }catch(error){$('brake-status').textContent=error.message;ws.close();}
    };
    ws.onclose=()=>{if(socket!==ws)return;socket=null;driverPrediction=null;clearVideo();clearLines();draw();$('brake-status').textContent='연결 중단 · 재연결 중';if(active())retry=setTimeout(connect,1500);};
    ws.onerror=()=>ws.close();
  }
  function disconnect(){clearTimeout(retry);driverPrediction=null;driveTelemetry=null;driveStatus();if(socket){const old=socket;socket=null;old.close();}clearVideo();}
  function makeView(target,cones){
    let gl,program,gpu,lines,grid,courseGPU,points=new Float32Array(),boxes=new Float32Array();
    function init(){
    if(gl)return;gl=target.getContext('webgl',{antialias:true});if(!gl)throw Error('WebGL을 사용할 수 없습니다.');
    const shader=(kind,text)=>{const s=gl.createShader(kind);gl.shaderSource(s,text);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;};
    program=gl.createProgram();gl.attachShader(program,shader(gl.VERTEX_SHADER,'attribute vec3 position;uniform mat4 matrix;uniform vec3 tint;uniform float pointSize;varying vec3 color;void main(){gl_Position=matrix*vec4(position,1.);gl_PointSize=pointSize;float h=clamp((position.z+1.5)/3.,0.,1.);color=tint.r<0.?mix(vec3(.15,.65,.95),vec3(1.,.65,.15),h):tint;}'));
    gl.attachShader(program,shader(gl.FRAGMENT_SHADER,'precision mediump float;varying vec3 color;void main(){gl_FragColor=vec4(color,1.);}'));gl.linkProgram(program);
    if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error('3D 초기화 오류');gpu=gl.createBuffer();lines=gl.createBuffer();grid=gl.createBuffer();courseGPU=gl.createBuffer();
    }
    function upload(buffer,data){gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,data,gl.DYNAMIC_DRAW);}
    function set(p,b=[]){points=new Float32Array(p);boxes=new Float32Array(b);if(gl){upload(gpu,points);upload(lines,boxes);}}
    function render(){
    if(!active())return;
    if(!gl){init();upload(gpu,points);upload(lines,boxes);}if(gl.isContextLost())return;
    const r=target.getBoundingClientRect(),ratio=Math.min(devicePixelRatio||1,2);
    target.width=Math.max(1,r.width*ratio);target.height=Math.max(1,r.height*ratio);
    gl.viewport(0,0,target.width,target.height);gl.clearColor(.045,.075,.11,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
    gl.useProgram(program);gl.uniformMatrix4fv(gl.getUniformLocation(program,'matrix'),false,matrix(r));gl.enable(gl.DEPTH_TEST);
    function layer(buffer,n,mode,tint,size){
      gl.bindBuffer(gl.ARRAY_BUFFER,buffer);const p=gl.getAttribLocation(program,'position');gl.enableVertexAttribArray(p);gl.vertexAttribPointer(p,3,gl.FLOAT,false,0,0);
      gl.uniform3fv(gl.getUniformLocation(program,'tint'),tint);gl.uniform1f(gl.getUniformLocation(program,'pointSize'),size);gl.drawArrays(mode,0,n);
    }
    if(cones&&ground){
      const a=[],z=(x,y)=>ground[0]*x+ground[1]*y+ground[2];
      for(let x=-45;x<=0;x+=5)a.push(x,-8,z(x,-8),x,8,z(x,8));
      for(let y=-8;y<=8;y+=2)a.push(-45,y,z(-45,y),0,y,z(0,y));
      upload(grid,new Float32Array(a));layer(grid,a.length/3,gl.LINES,[.15,.24,.32],1);
    }
    layer(lines,boxes.length/3,gl.LINES,[1.,.56,.16],1);
    layer(gpu,points.length/3,gl.POINTS,cones?[1.,.8,.4]:[-1,0,0],cones?6:3);
    if($('brake-show-lines').checked){
      const colors={left:[.2,.7,1],right:[.8,.45,1],center:[.4,1,.3],stop:stopEvidence.state===2?[1,.25,.3]:[1,.65,.15]};
      for(const [name,points] of Object.entries(courseLines)){
        let segment=points;
        if(name==='stop'&&stopEvidence.state!==2){
          segment=[];const a=points.slice(0,3),b=points.slice(3);
          for(let i=0;i<12;i++)for(const f of [i/12,(i+.6)/12])segment.push(...a.map((x,k)=>x+(b[k]-x)*f));
        }
        // WebGL often supports only 1px GL_LINES. A narrow world-space ribbon
        // keeps the inferred lines readable without relying on lineWidth.
        const ribbon=[],w=Math.max(.025,.08/zoom);
        for(let i=0;i<segment.length;i+=6){
          const a=segment.slice(i,i+3),b=segment.slice(i+3,i+6),dx=b[0]-a[0],dy=b[1]-a[1],n=Math.hypot(dx,dy);
          if(n<1e-6)continue;
          const side=[-dy*w/n,dx*w/n,0],q=[a.map((v,k)=>v+side[k]),a.map((v,k)=>v-side[k]),b.map((v,k)=>v+side[k]),b.map((v,k)=>v-side[k])];
          for(const j of [0,1,2,2,1,3])ribbon.push(...q[j]);
        }
        upload(courseGPU,new Float32Array(ribbon));layer(courseGPU,ribbon.length/3,gl.TRIANGLES,colors[name],1);
      }
    }
    const predicted=state?.fresh?.cloud?window.BrakePrediction.geometry(predictionModel(),ground):null;
    if(predicted){
      function stroke(path,width,color){
        const ribbon=[];
        for(let i=1;i<path.length;i++){
          const a=path[i-1],b=path[i],dx=b[0]-a[0],dy=b[1]-a[1],n=Math.hypot(dx,dy);
          if(n<1e-7)continue;
          const side=[-dy*width/n,dx*width/n,0],q=[a.map((v,k)=>v+side[k]),a.map((v,k)=>v-side[k]),b.map((v,k)=>v+side[k]),b.map((v,k)=>v-side[k])];
          for(const j of [0,1,2,2,1,3])ribbon.push(...q[j]);
        }
        upload(courseGPU,new Float32Array(ribbon));layer(courseGPU,ribbon.length/3,gl.TRIANGLES,color,1);
      }
      stroke(predicted.left,.018,[.65,.65,.23]);stroke(predicted.right,.018,[.65,.65,.23]);
      stroke(predicted.body,.025,[1,.9,.12]);stroke(predicted.center,.055,[1,.9,.12]);stroke(predicted.arrow,.055,[1,.9,.12]);
    }
    }
    return {set,draw:render};
  }
  function matrix(r){
    const ca=Math.cos(azimuth),sa=Math.sin(azimuth),se=Math.sin(elevation),ce=Math.cos(elevation),base=1.7*zoom/extent;
    const sx=base*Math.min(1,r.height/r.width),sy=base*Math.min(1,r.width/r.height),sz=.5/extent;
    const x=[ca*sx,sa*sx,0],y=[-sa*se*sy,ca*se*sy,ce*sy],z=[sa*ce*sz,-ca*ce*sz,se*sz],dot=v=>v.reduce((n,a,i)=>n+a*center[i],0);
    return new Float32Array([x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,-dot(x),-dot(y),-dot(z),1]);
  }
  function draw(){predictionInfo();driveStatus();cloudView.draw();coneView.draw();}
  $('brake-show-lines').onchange=draw;
  for(const id of ['brake-show-prediction','brake-prediction-mode'])$(id).onchange=draw;
  $('brake-steering').oninput=draw;
  $('brake-steering-zero').onclick=()=>{$('brake-steering').value=0;draw();};
  function drawGPS(){
    const r=gpsCanvas.getBoundingClientRect();gpsCanvas.width=Math.max(1,r.width*2);gpsCanvas.height=Math.max(1,r.height*2);
    const ctx=gpsCanvas.getContext('2d'),w=gpsCanvas.width,h=gpsCanvas.height;ctx.clearRect(0,0,w,h);
    if(!gps.length){ctx.fillStyle='#64748b';ctx.font='24px sans-serif';ctx.fillText('GPS 수신 대기',20,h/2);return;}
    const origin=gps[0],xy=gps.map(p=>[(p.lon-origin.lon)*111320*Math.cos(origin.lat*Math.PI/180),(p.lat-origin.lat)*111320]);
    const xs=xy.map(p=>p[0]),ys=xy.map(p=>p[1]),xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys);
    const scale=Math.min((w-60)/Math.max(10,xmax-xmin),(h-60)/Math.max(10,ymax-ymin));
    const project=p=>[w/2+(p[0]-(xmin+xmax)/2)*scale,h/2-(p[1]-(ymin+ymax)/2)*scale];
    ctx.strokeStyle='#3c82b8';ctx.lineWidth=3;ctx.beginPath();xy.forEach((p,i)=>{const [x,y]=project(p);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();
    const [x,y]=project(xy.at(-1));ctx.beginPath();ctx.arc(x,y,7,0,Math.PI*2);ctx.fillStyle=state?.fresh?.gps?'#e97837':'#94a3b8';ctx.fill();
    ctx.fillStyle='#64748b';ctx.font='20px sans-serif';ctx.fillText('N ↑',12,25);ctx.fillText('이동 '+Math.hypot(...xy.at(-1)).toFixed(1)+'m',12,h-12);
  }
  for(const prefix of ['brake','brake-cone']){
    $(prefix+'-top').onclick=()=>{azimuth=-Math.PI/2;elevation=Math.PI/2;draw();};
    $(prefix+'-angle').onclick=()=>{azimuth=-1.5;elevation=.65;draw();};
    $(prefix+'-fit').onclick=()=>{
      const points=Object.values(courseLines).flatMap(p=>[p.slice(0,3),p.slice(3)]);
      if(prefix==='brake-cone'&&points.length){
        const lo=[0,1,2].map(k=>Math.min(...points.map(p=>p[k]))),hi=[0,1,2].map(k=>Math.max(...points.map(p=>p[k])));
        center=lo.map((v,k)=>(v+hi[k])/2);extent=Math.max(12,1.3*Math.max(hi[0]-lo[0],hi[1]-lo[1]));
      }else{center=[-18,0,0];extent=45;}
      zoom=1;draw();
    };
  }
  for(const canvas of [ $('brake-cloud'),coneCanvas ]){
  canvas.onpointerdown=e=>{drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);};
  canvas.onpointermove=e=>{if(!drag)return;azimuth-=(e.clientX-drag[0])*.007;elevation=Math.max(.05,Math.min(Math.PI/2,elevation+(e.clientY-drag[1])*.007));drag=[e.clientX,e.clientY];draw();};
  canvas.onpointerup=canvas.onpointercancel=()=>drag=null;
  canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.3,Math.min(8,zoom*Math.exp(-e.deltaY*.001)));draw();},{passive:false});
  canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();disconnect();$('brake-status').textContent='3D 연결 중단 · 새로고침해 주세요.';});
  }
  new ResizeObserver(()=>{draw();drawGPS();}).observe(pane);
  function mode(){if(active()){connect();draw();drawGPS();}else disconnect();}
  window.addEventListener('dashboard:modechange',mode);document.addEventListener('visibilitychange',mode);
  window.addEventListener('pagehide',()=>{ended=true;disconnect();});window.addEventListener('pageshow',()=>{ended=false;mode();});
  setInterval(()=>{if(active())driveStatus();if(active()&&lastStatus&&Date.now()-lastStatus>2500){$('brake-status').textContent='데이터 수신 중단';canvas.style.opacity=coneCanvas.style.opacity='.35';clearLines();draw();$('brake-video-message').hidden=false;$('brake-video-message').textContent='데이터 수신 중단';}},1000);
  mode();
})();
