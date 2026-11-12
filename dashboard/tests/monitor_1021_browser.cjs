const fs = require('fs'), assert = require('assert');
const {chromium} = require(process.env.PLAYWRIGHT_DRIVER_PATH || '/browser/playwright/driver/package');
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.BROWSER_EXECUTABLE,
    args: ['--no-sandbox', '--disable-dev-shm-usage']});
  const page = await browser.newPage({viewport: {width: 1400, height: 900}}), errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  const routePoints = [[0,0],[20,0],[40,10],[45,20],[40,30],[20,30]];
  const state = {session:'fixture', revision:'preview', sequence:0, reset:false, active:true, server_age_s:0,
    path:{frame:'monitor_map_preview', points:routePoints, source:'preview', name:'선택한 예선맵.json'}, trail:[],
    pose:{frame:'map', x:0, y:0, yaw:0, valid:false, position_valid:false, fresh:false,
      reason:'GNSS_ANTENNA_OBSERVATION_UNAVAILABLE'}};
  let unavailable = false;
  await page.route('http://display.test/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/monitor-1021') {
      if (unavailable) return route.fulfill({status:503, body:'offline'});
      return route.fulfill({json:state});
    }
    const file = url.pathname === '/monitor-1021' ? '/source/dashboard/monitor-1021.html' : '/source/dashboard/monitor-1021.js';
    return route.fulfill({body:fs.readFileSync(file), contentType:file.endsWith('.html') ? 'text/html' : 'application/javascript'});
  });
  const waitStatus = text => page.waitForFunction(text => document.getElementById('status').textContent.includes(text), text);
  const vehicle = () => page.locator('canvas').getAttribute('data-vehicle-state');
  const target = () => page.locator('canvas').getAttribute('data-target-visible');
  try {
    await page.goto('http://display.test/monitor-1021');
    await waitStatus('지도 미리보기');
    assert.equal(await page.locator('canvas').getAttribute('data-route-points'), '6');
    assert.equal(await vehicle(), 'none', 'default zero coordinates must never be shown as a vehicle');
    await page.screenshot({path:'/evidence/monitor-preview.png', fullPage:true});
    state.path = {frame:'map', points:routePoints, source:'planned', name:'선택한 예선맵.json'};
    state.revision = 'map'; state.reference = {count:0,frame:'map'};
    await waitStatus('GNSS 안테나 위치 관측 없음');
    assert.equal(await vehicle(), 'none');
    assert.equal(await page.locator('canvas').getAttribute('data-route-points'), '6', 'invalid tracking must retain planned map');
    state.pose = {frame:'map',x:10,y:.5,yaw:.2,valid:true,position_valid:true,fresh:true,
      source_age_s:.01,received_age_s:0,reason:'NEW_OR_FRESH_GNSS_COG'};
    state.last_good_pose = {...state.pose, age_s:.01};
    state.sequence = 3;
    state.trail = [{seq:1,x:0,y:.2},{seq:2,x:5,y:.4},{seq:3,x:10,y:.5}];
    state.diagnostic = {frame:'map',valid:true,fresh:true,target:[14,0],lateral:-.12,heading:-.03,
      lookahead:4,steering:-.02,reason:'PURE_PURSUIT_ACTIVE'};
    state.motion = {valid:true,fresh:true,speed:5};
    state.command = {valid:true,fresh:true,steering:-.018};
    state.control = {fresh:true,paused:false,fsm_state:2,reason:'PURE_PURSUIT_ACTIVE'};
    await waitStatus('현재 차량 위치 표시 중');
    assert.equal(await vehicle(), 'live'); assert.equal(await target(), 'true');
    assert((await page.locator('#speed').textContent()).includes('18.00'));
    await page.screenshot({path:'/evidence/monitor-desktop.png',fullPage:true});
    await page.locator('#follow').click();
    assert.equal(await page.locator('#follow').getAttribute('aria-pressed'),'true');
    await page.locator('#fit').click();
    state.diagnostic.valid=false; state.diagnostic.reason='PURE_PURSUIT_COMPUTE_FAILED';
    await page.waitForFunction(()=>document.getElementById('lateral').textContent==='—');
    assert.equal(await target(),'false'); assert.equal(await vehicle(),'live');
    state.pose={...state.pose,x:0,y:0,valid:false,position_valid:false,reason:'GNSS_ANTENNA_OBSERVATION_UNAVAILABLE'};
    state.last_good_pose.age_s=2.5;
    await waitStatus('GNSS 안테나 위치 관측 없음');
    assert.equal(await vehicle(),'last-known');
    assert((await page.locator('#pose-age').textContent()).includes('2.5초'));
    await page.screenshot({path:'/evidence/monitor-last-position.png',fullPage:true});
    unavailable=true;
    await waitStatus('모니터 연결 끊김');
    assert.equal(await vehicle(),'last-known'); assert.equal(await target(),'false');
    await page.screenshot({path:'/evidence/monitor-disconnected.png',fullPage:true});
    unavailable=false; state.pose={...state.last_good_pose,frame:'other',fresh:true,valid:true,position_valid:true};
    await waitStatus('좌표 기준 불일치');
    // Frame changes must never make an invalid zero marker visible.
    state.last_good_pose=null;
    await page.waitForFunction(()=>document.querySelector('canvas').dataset.vehicleState==='none');
    assert.equal(await page.locator('canvas').getAttribute('data-trail-visible'),'false');
    state.pose={...state.pose,frame:'map'}; state.last_good_pose={...state.pose,age_s:.02};
    state.diagnostic.valid=true;
    await waitStatus('현재 차량 위치 표시 중');
    await page.setViewportSize({width:390,height:844});
    await page.waitForTimeout(250);
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'mobile layout must fit');
    assert.equal(await vehicle(),'live');
    await page.screenshot({path:'/evidence/monitor-mobile.png',fullPage:true});
    // A healthy HTTP polling loop cannot make an old ROS sample fresh again.
    state.server_age_s=2;
    await waitStatus('모니터 연결 끊김');
    assert.equal(await target(),'false');
    assert.deepEqual(errors,[]);
    fs.writeFileSync('/evidence/browser-result.json',JSON.stringify({
      planned_preview_before_gnss:true,no_zero_marker:true,planned_route_survives_invalid_pose:true,
      live_vehicle:true,follow_and_fit:true,invalid_target_hidden:true,last_position_retained:true,
      disconnected_history:true,frame_mismatch_hidden:true,server_age_expires:true,mobile_layout:true,
      page_errors:errors},null,2));
    console.log('ALL DISPLAY BROWSER CHECKS PASSED');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
