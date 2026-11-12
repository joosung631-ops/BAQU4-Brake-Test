(() => {
  const select=document.getElementById('bag-select'), loop=document.getElementById('bag-loop');
  const play=document.getElementById('bag-play'), stop=document.getElementById('bag-stop');
  const slower=document.getElementById('bag-slower'), faster=document.getElementById('bag-faster'), rate=document.getElementById('bag-rate');
  const status=document.getElementById('bag-status');
  const results=document.getElementById('bag-results-only');
  const labels={idle:'정지',preparing:'재생 준비 / 압축 해제 중',playing:'재생 중',stopping:'정지 중',finished:'재생 완료',error:'재생 오류'};
  let busy=false, timer, ended=false, snapshot=null;
  const active=()=>['rosbag','map-compare'].includes(window.dashboardModes?.current);
  const rosbag=()=>window.dashboardModes?.current==='rosbag';
  function placeControls(){
    const panel=document.getElementById('bag-playback-controls'),slot=document.getElementById('map-compare-bag-player'),home=document.getElementById('bag-playback-home');
    if(!panel||!slot||!home)return;
    if(window.dashboardModes?.current==='map-compare')slot.append(panel);else home.after(panel);
  }
  const announce=()=>window.dispatchEvent(new CustomEvent('dashboard:bagchange',{detail:{bag:select.value,state:snapshot?.state||'idle',rate:snapshot?.rate||1}}));
  function render(data) {
    if (data.error && !data.bags) throw new Error(data.error);
    snapshot=data;
    const selected=select.value;
    if (JSON.stringify([...select.options].map(o=>o.value))!==JSON.stringify(data.bags)) {
      select.replaceChildren(...data.bags.map(name=>new Option(name,name)));
      if (data.bags.includes(selected)) select.value=selected;
    }
    const running=['preparing','playing','stopping'].includes(data.state);
    if (running && data.selected) {select.value=data.selected;loop.checked=data.loop;}
    if(rosbag()){
      window.dashboardBagGPS?.select(select.value);
      if(results.checked)window.dashboardBagGPS?.prepare(select.value).catch(()=>{});
    }
    announce();
    select.disabled=loop.disabled=running||busy;
    results.disabled=busy;
    play.disabled=busy||running||data.external||!data.bags.length;
    stop.disabled=busy||!running;
    const rateBlocked=busy||data.external||['preparing','stopping'].includes(data.state);
    slower.disabled=rateBlocked||data.rate<=0.1;faster.disabled=rateBlocked;
    rate.textContent=Number(data.rate??1).toFixed(1)+'×';
    if (!busy) status.textContent=data.external?'터미널 rosbag 실행 중 · 먼저 정지하세요':
      `${labels[data.state]||data.state}${data.selected?' · '+data.selected:''}${data.error?' · '+data.error:''}`;
  }
  async function refresh() {
    try {const r=await fetch('/api/bags',{cache:'no-store'});render(await r.json());}
    catch(e){status.textContent=e.message;play.disabled=true;stop.disabled=true;slower.disabled=faster.disabled=true;}
  }
  async function command(action, step) {
    if(busy)return;
    busy=true;play.disabled=stop.disabled=slower.disabled=faster.disabled=true;
    select.disabled=loop.disabled=results.disabled=true;
    try {
      if (action==='play'&&rosbag()) {
        if (results.checked) status.textContent='전체 GPS를 준비하는 중…';
        await window.dashboardBagGPS?.prepare(select.value);
        window.dashboardBagGPS?.begin();
      }
      const r=await fetch('/api/bags/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Control':'1'},
        body:JSON.stringify({bag:select.value,loop:loop.checked,step})});
      const data=await r.json();if(!r.ok)throw new Error(data.error||'재생 요청 실패');
      busy=false;render(data);
    }catch(e){busy=false;await refresh();status.textContent=e.message;}
  }
  slower.onclick=()=>command('rate',-1);faster.onclick=()=>command('rate',1);
  play.onclick=()=>command('play');stop.onclick=()=>command('stop');
  select.addEventListener('change',()=>{
    if(rosbag()){
      window.dashboardBagGPS?.select(select.value);
      if(results.checked)window.dashboardBagGPS?.prepare(select.value).catch(()=>{});
    }
    announce();
  });
  async function poll(){if(!document.hidden&&active())await refresh();if(!ended)timer=setTimeout(poll,3000);}
  window.addEventListener('pagehide',()=>{ended=true;clearTimeout(timer);});
  window.addEventListener('pageshow',e=>{if(e.persisted){ended=false;poll();}});
  window.addEventListener('dashboard:modechange',()=>{placeControls();if(active())refresh();});
  placeControls();poll();
})();
