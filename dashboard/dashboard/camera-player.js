/* Low-latency H.264/fMP4 player; latest source, bounded append queue, no JPEG fallback. */
(() => {
  const $=id=>document.getElementById(id), video=$('camera-video'), select=$('camera-topic');
  if(!video||!select)return;
  const toggle=$('camera-toggle'), input=$('camera-fps'), message=$('camera-message');
  const allowed=[5,10,15,20,25,30];
  let enabled=false, fps=15, edited=false, mode='', signature='', ws=null, retry=null, configuration=null;
  let media=null, buffer=null, url=null, appending=false, queue=[], frameTimes=[], callback=null, started=0;
  let lastFrame=0, bytes=0, byteStart=performance.now(), ended=false;
  const eligible=()=>enabled&&!!select.value&&!document.hidden&&!ended&&(!window.dashboardModes||dashboardModes.current==='rosbag');
  function show(text){message.textContent=text;message.hidden=false;}
  function stop(){
    clearTimeout(retry);const old=ws;ws=null;if(old)old.close();
    if(callback!==null&&video.cancelVideoFrameCallback)video.cancelVideoFrameCallback(callback);
    callback=null;queue=[];buffer=null;media=null;frameTimes=[];lastFrame=0;
    video.pause();video.removeAttribute('src');video.load();video.hidden=true;
    if(url)URL.revokeObjectURL(url);url=null;
    $('camera-update-rate').textContent='(0Hz)';
  }
  function fail(text){show(text);if(ws)ws.close();}
  function observeFrames(socket){
    if(!video.requestVideoFrameCallback)return;
    const frame=()=>{
      if(ws!==socket)return;
      const now=performance.now();frameTimes.push(now);lastFrame=Date.now();
      message.hidden=true;video.hidden=false;
      callback=video.requestVideoFrameCallback(frame);
    };
    callback=video.requestVideoFrameCallback(frame);
  }
  function pump(socket){
    if(ws!==socket||!buffer||buffer.updating||!queue.length)return;
    try{appending=true;buffer.appendBuffer(queue.shift());}catch(error){fail('영상 재생 오류: '+error.message);}
  }
  function initialize(info,socket){
    if(!window.MediaSource||!MediaSource.isTypeSupported(info.mime)){
      show('이 브라우저에서 H.264 재생을 지원하지 않습니다. Chrome 또는 Edge를 사용하세요.');
      enabled=false;stop();toggle.textContent='OFF';toggle.setAttribute('aria-pressed','false');return;
    }
    $('camera-profile').textContent=`H.264 · ${info.width}×${info.height} · 최대 ${info.bitrate_kbps/1000}Mbps`;
    media=new MediaSource();url=URL.createObjectURL(media);video.src=url;video.hidden=false;
    media.addEventListener('sourceopen',()=>{
      if(ws!==socket||!media)return;
      try{
        buffer=media.addSourceBuffer(info.mime);
        buffer.addEventListener('updateend',()=>{
          if(ws!==socket||!buffer)return;
          if(appending&&socket.readyState===WebSocket.OPEN)socket.send('ack');
          appending=false;
          try{
            if(video.buffered.length){
              const end=video.buffered.end(video.buffered.length-1), lag=end-video.currentTime;
              if(lag>.6)video.currentTime=Math.max(video.buffered.start(0),end-.15);
              if(video.currentTime>10&&buffer.buffered.length&&buffer.buffered.start(0)<video.currentTime-6&&!buffer.updating){buffer.remove(0,video.currentTime-5);return;}
            }
          }catch(_){}
          pump(socket);video.play().catch(()=>{});
        });
        buffer.addEventListener('error',()=>fail('영상 디코딩 오류'));
        pump(socket);
      }catch(error){fail('영상 초기화 오류: '+error.message);}
    },{once:true});
    observeFrames(socket);
  }
  function start(){
    stop();toggle.disabled=!select.value;toggle.textContent=enabled?'ON':'OFF';
    toggle.setAttribute('aria-pressed',String(enabled));
    if(!eligible()){show(enabled?'영상 일시 중단':'카메라 꺼짐');return;}
    show('영상 연결 중…');started=Date.now();bytes=0;byteStart=performance.now();
    const query=new URLSearchParams({mode,topic:select.value,fps});
    const socket=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/ws/camera?${query}`);
    ws=socket;socket.binaryType='arraybuffer';
    socket.onmessage=event=>{
      if(ws!==socket)return;
      if(typeof event.data==='string'){
        let info;try{info=JSON.parse(event.data);}catch(_){fail('영상 응답 오류');return;}
        if(info.type==='init')initialize(info,socket);
        else if(info.error)show(info.error);
      }else{
        bytes+=event.data.byteLength;
        if(queue.length>=8){fail('연결 지연 · 최신 영상으로 재연결 중');return;}
        queue.push(event.data);pump(socket);
      }
    };
    socket.onclose=()=>{if(ws!==socket)return;stop();show('영상 연결 대기 · 재연결 중');if(eligible())retry=setTimeout(start,1500);};
    socket.onerror=()=>socket.close();
  }
  function configure(data){
    configuration=data;
    let changed=false;
    if(!edited&&allowed.includes(data.camera_default_fps)&&fps!==data.camera_default_fps){fps=data.camera_default_fps;input.value=fps;changed=true;}
    // ROS Bag view always requests recorded video, independently of topic-health tabs.
    const cameraMode=window.dashboardModes?.current==='rosbag'?'bag':data.topic_mode;
    const configured=data.camera_topics_by_mode?.[cameraMode]||(cameraMode===data.topic_mode?data.camera_topics:[]);
    const topics=(configured||[]).filter(t=>!t.startsWith('/lidar/')&&!t.startsWith('/ouster/'));
    const next=JSON.stringify([cameraMode,topics]);
    if(next!==signature){
      signature=next;mode=cameraMode;const previous=select.value;
      select.replaceChildren(...topics.map(t=>new Option(t,t)));select.value=topics.includes(previous)?previous:(topics.find(t=>t.endsWith('/compressed'))||topics[0]||'');
      select.disabled=!topics.length;if(!topics.includes(previous))enabled=false;changed=true;
    }
    if(changed)start();
    return changed;
  }
  toggle.onclick=()=>{if(select.value){enabled=!enabled;start();}};
  select.onchange=start;
  function applyFPS(){const value=Number(input.value);if(!allowed.includes(value)){input.value=fps;return;}edited=true;if(value!==fps){fps=value;start();}}
  input.onchange=applyFPS;input.onkeydown=e=>{if(e.key==='Enter')applyFPS();};
  document.addEventListener('visibilitychange',start);
  window.addEventListener('dashboard:modechange',()=>{if(!configuration||!configure(configuration))start();});
  window.addEventListener('pagehide',()=>{ended=true;stop();});
  window.addEventListener('pageshow',e=>{if(e.persisted){ended=false;start();}});
  video.addEventListener('error',()=>{if(ws)fail('영상 재생 오류');});
  setInterval(()=>{
    const now=performance.now();frameTimes=frameTimes.filter(t=>now-t<2000);
    let rate=frameTimes.length>1?(frameTimes.length-1)*1000/(frameTimes.at(-1)-frameTimes[0]):0;
    if(!video.requestVideoFrameCallback&&ws){
      const quality=video.getVideoPlaybackQuality?.();
      if(quality){const before=video._quality;video._quality=[now,quality.totalVideoFrames];if(before)rate=(quality.totalVideoFrames-before[1])*1000/(now-before[0]);if(rate>0){message.hidden=true;lastFrame=Date.now();}}
    }
    $('camera-update-rate').textContent=`(${Math.round(rate*10)/10}Hz)`;
    const elapsed=(now-byteStart)/1000;
    $('camera-transfer').textContent=ws&&elapsed>0?`영상 ${(bytes/elapsed/1000).toFixed(1)} kB/s`:'';
    if(ws&&(lastFrame||started)&&Date.now()-(lastFrame||started)>3000)show('영상 수신 대기');
  },500);
  window.dashboardCamera={configure,stop,start};
})();
