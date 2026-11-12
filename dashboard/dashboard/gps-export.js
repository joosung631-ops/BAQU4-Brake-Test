(() => {
 const $=id=>document.getElementById(id),input=$('gps-export-name');if(!input)return;
 let busy=false,saved=null,effective=null,summaryVersion=0;
 const finalStageName=name=>{const parts=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(new Date()).map(p=>[p.type,p.value]));const suffix=name.replace(/\.json$/,'').replace(/^(?:\d+단계|맵|MAP)_\d{4}-\d{2}-\d{2}_\d{6,12}_/,'');return `${gpsProject.stageNumber(12)}단계_${parts.year}-${parts.month}-${parts.day}_${parts.hour}${parts.minute}${parts.second}_${suffix}`;};
 const filename=()=>{const name=input.value.trim();return name.endsWith('.json')?name:name+'.json';};
 const number=value=>Number.isFinite(value)?value.toLocaleString('ko-KR',{maximumFractionDigits:3}):'기록 없음';
 const count=value=>Number.isFinite(value)?`${number(value)}점`:'기록 없음';
 const sumPoints=(tracks,key)=>Array.isArray(tracks)&&tracks.every(t=>Array.isArray(t[key]))?tracks.reduce((sum,t)=>sum+t[key].length,0):null;
 const shortName=value=>{const name=String(value).split('/').filter(Boolean).at(-1)||String(value);return name.length>34?name.slice(0,19)+'…'+name.slice(-12):name;};
 function summaryData(project){
  const s=project.stages,raw=s['2']?.map_merge?(project.map_merge_result?.raw.tracks||[]).filter(t=>t.map_merge_clip):s['2']?.raw?.tracks;
  const bags=(raw||[]).map((track,i)=>({name:track.source_bag||track.bag_path||(s['2'].map_merge?track.name:s['2'].bags?.[i]||track.name),count:Array.isArray(track.points)?track.points.length:null,skipped:track.skipped}));
  const counts={raw:sumPoints(raw,'points'),clean:sumPoints(s['3']?.tracks,'retained_points'),added:s['4']?.additions?.length||0,withAdded:sumPoints(s['4']?.tracks,'points'),within:sumPoints(s['5']?.tracks,'points'),merged:Array.isArray(s['6']?.points)?s['6'].points.length:null,ordered:Array.isArray(s['7']?.ordered_points)?s['7'].ordered_points.length:null,final:effective?.points.length??null};
  return {bags,counts,path:effective,lane:s['9'],verified:[...new Set(s['11']?.validated_bags||[])],skipped:bags.reduce((sum,b)=>sum+(Number.isFinite(b.skipped)?b.skipped:0),0)};
 }
 function renderSummary(){
  const parent=$('gps-export-summary');parent.replaceChildren();if(!gpsProject.current)return;
  const summary=summaryData(gpsProject.current.project),c=summary.counts,p=summary.path;
  const node=(tag,text)=>{const element=document.createElement(tag);if(text!==undefined)element.textContent=text;return element;};
  const title=text=>{const el=node('strong',text);el.style.cssText='display:block;margin:10px 0 4px';parent.append(el);};
  const line=text=>{const el=node('p',gpsProject.formatStages(text));el.style.margin='3px 0';parent.append(el);};
  const table=rows=>{const el=node('table');el.style.cssText='width:100%;border-collapse:collapse;font-size:inherit';for(const [label,value,tooltip] of rows){const row=node('tr'),a=node('td',label),b=node('td',value);a.style.cssText='padding:3px 8px 3px 0;overflow-wrap:anywhere';if(tooltip)a.title=tooltip;b.style.cssText='text-align:right;vertical-align:top;padding:3px 0';row.append(a,b);el.append(row);}parent.append(el);};
  title(gpsProject.mapMergeEnabled?'경로 작업 ROS bag':'기반 ROS bag');
  if(gpsProject.mapMergeEnabled)line('2단계 기준 로스백은 배경 표시 전용이며 최종 경로 계산에서 제외됩니다.');
  if(summary.bags.length){table(summary.bags.map(b=>[shortName(b.name),count(b.count),b.name]));line(`불러온 GPS 총 ${count(c.raw)} · 로스백당 평균 ${count(Number.isFinite(c.raw)?c.raw/summary.bags.length:null)}`);}else line('저장된 원본 로스백 기록 없음');
  const reduced=(previous,current,label)=>Number.isFinite(previous)&&Number.isFinite(current)&&previous>=current?` (${label} ${count(previous-current)})`:'';
  title('GPS 점 정리');
  table([
   ['원본 GPS',count(c.raw)],
   ['노이즈·범위 제외 후',count(c.clean)+reduced(c.raw,c.clean,'제외')],
   ['직접 추가한 GPS',count(c.added)],
   ['기록별 평균 병합 후',count(c.within)+reduced(c.clean,c.within,'감소')],
   ['기록 간 평균 병합 후',count(c.merged)+reduced(c.within,c.merged,'감소')],
   ['순서 확정 · 웨이포인트',count(c.ordered)+reduced(c.merged,c.ordered,'미사용')]
  ]);
  if(Number.isFinite(c.clean)&&Number.isFinite(c.merged)&&c.clean>=c.merged)line(`평균 병합으로 총 ${count(c.clean-c.merged)} 감소`);
  title('최종 직선 보간 경로 · 맵');
  if(p){
   line(`웨이포인트 ${number(p.waypoint_count)}개를 연결한 직선 보간선 · GPS 위치 기준 · 열린 경로`);
   table([['점 추출 간격',Number.isFinite(p.output_spacing_m)?`최대 ${number(p.output_spacing_m)} m · 웨이포인트·끝점 포함`:'기록 없음'],['최종 GPS 점 개수',count(c.final)],['경로 길이',Number.isFinite(p.statistics?.length_m??p.points?.at(-1)?.s_m)?`${number(p.statistics?.length_m??p.points?.at(-1)?.s_m)} m`:'기록 없음'],['예상 차선',summary.lane?.enabled===false?'미적용':Number.isFinite(summary.lane?.lane_width_m)?`폭 ${number(summary.lane.lane_width_m)} m`:'기록 없음']]);
   const stats=p.statistics;
   if(Number.isFinite(stats?.distance_mean_m)&&Number.isFinite(stats?.distance_max_m))line(`입력 GPS와 예상 GPS 경로의 거리: 평균 ${number(stats.distance_mean_m)} m / 최대 ${number(stats.distance_max_m)} m`);
  }else line('직선 보간 경로를 불러오는 중…');
  title('최종 웨이포인트 추가');
  line(`직접 추가 ${gpsProject.current.project.stages['10.5']?.additions?.length||0}점`);
  title('과제 구간');
  const sections=gpsProject.current.project.stages['10']?.sections||[];
  if(sections.length)for(const [i,section] of sections.entries())line(`${i+1}. ${section.name} · ${number(section.end.s_m-section.start.s_m)} m · ${section.description}`);else line('설정된 과제 구간 없음');
  title('검증한 ROS bag');
  if(summary.verified.length){const list=node('ul');list.style.cssText='margin:3px 0;padding-left:18px';for(const name of summary.verified){const item=node('li',shortName(name));item.title=name;list.append(item);}parent.append(list);line(`검증 완료 체크 ${summary.verified.length}개`);}else line('검증 완료로 체크한 로스백 없음');
  title('확인 사항');
  if(summary.skipped)line(`측위 무효 등으로 불러올 때 제외된 GPS ${count(summary.skipped)}`);
  if(Number.isFinite(c.merged)&&Number.isFinite(c.ordered)&&c.merged>c.ordered)line(`순서에 포함하지 않은 ${count(c.merged-c.ordered)}은 순서 확정 웨이포인트에서 제외됨`);
  if(p)line('9단계 이후 모든 계산과 최종 저장은 직선 보간선 기준');
  if(!summary.verified.length)line('11단계의 검증 로스백 체크·저장 필요');
 }
 function update(){
  const current=gpsProject.current;if(!current)return;
  const parent=current.workspace_path.slice(0,current.workspace_path.lastIndexOf('/')+1),name=saved?filename():finalStageName(filename())+'.json';
  const parts=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(new Date()).map(p=>[p.type,p.value]));
  const suffix=name.slice(0,-5).replace(/^(?:\d+단계|맵|MAP)_\d{4}-\d{2}-\d{2}_\d{6,12}_/,'');
  const output=`MAP_${parts.year}-${parts.month}-${parts.day}_${parts.hour}${parts.minute}${parts.second}_${suffix}.json`;
  $('gps-export-working-path').textContent='작업 파일 경로: '+parent+name;
  $('gps-export-output-path').textContent=(saved?'최종 맵 저장 경로: ':'최종 맵 저장 예정 경로: ')+(saved?.workspace_path||parent+output);
  input.disabled=busy;$('gps-export-save').disabled=busy||!input.value.trim();$('gps-export-competition').disabled=busy;
 }
 function chooseCompetition(source){
  const dialog=$('gps-export-competition-dialog'),kind=$('gps-export-competition-kind'),confirm=$('gps-export-competition-confirm'),cancel=$('gps-export-competition-cancel'),message=$('gps-export-competition-message');
  let version=0,target=null,publishing=false,result=null;
  kind.value='';kind.disabled=false;cancel.disabled=false;confirm.disabled=true;confirm.textContent='추가 저장';
  $('gps-export-competition-path').textContent='';message.textContent='예선 맵인지 본선 맵인지 선택하세요.';
  async function refresh(){
   const request=++version;target=null;confirm.disabled=true;$('gps-export-competition-path').textContent='';
   if(!kind.value){message.textContent='예선 맵인지 본선 맵인지 선택하세요.';return;}
   message.textContent='기존 파일 확인 중…';
   try{
    const next=await gpsProject.api('/api/gps/projects/competition-map?category='+encodeURIComponent(kind.value));
    if(request!==version||!dialog.open)return;
    target=next;$('gps-export-competition-path').textContent='추가 저장 경로: '+next.workspace_path;
    message.textContent=next.exists?`${next.filename} 파일이 이미 있습니다. 확인을 누르면 기존 파일을 최신 맵으로 덮어씁니다.`:`${next.filename} 파일을 추가로 저장합니다.`;
    confirm.textContent=next.exists?'확인 · 덮어쓰기':'추가 저장';confirm.disabled=false;
   }catch(e){if(request===version&&dialog.open)message.textContent=e.message;}
  }
  return new Promise(resolve=>{
   dialog.addEventListener('close',()=>{version++;kind.onchange=null;confirm.onclick=null;cancel.onclick=null;dialog.oncancel=null;resolve(result);},{once:true});
   dialog.oncancel=e=>{if(publishing)e.preventDefault();};
   cancel.onclick=()=>dialog.close('cancel');kind.onchange=refresh;
   confirm.onclick=async()=>{
    if(!target||publishing)return;publishing=true;confirm.disabled=true;cancel.disabled=true;kind.disabled=true;message.textContent='추가 맵 저장 중…';
    try{
     result=await gpsProject.api('/api/gps/projects/competition-map',{source_filename:source.filename,category:kind.value,expected_digest:target.digest});
     dialog.close('saved');
    }catch(e){
     await refresh();message.textContent=e.message+' '+(target?.exists?'확인을 누르면 기존 파일을 최신 맵으로 덮어씁니다.':'추가 저장을 다시 시도할 수 있습니다.');
    }finally{publishing=false;cancel.disabled=false;kind.disabled=false;}
   };
   dialog.showModal();
  });
 }
 input.oninput=()=>{saved=null;update();};
 async function save(onExit=false){if(busy)throw Error('최종 맵 저장 중입니다.');if(onExit&&saved)return;if(!input.value.trim())throw Error('파일 이름을 입력하세요.');busy=true;update();$('gps-export-status').textContent='최종 맵 저장 중…';try{
  const result=await gpsProject.finalize(filename());saved=result.export;renderSummary();input.value=result.working.filename.replace(/\.json$/,'');
  $('gps-export-status').textContent='최종 맵을 별도 파일로 저장했습니다. 작업 파일에는 편집 내용을 유지합니다.';
  if(!onExit&&$('gps-export-competition').checked){
   const competition=await chooseCompetition(saved);
   $('gps-export-status').textContent+=competition?` ${competition.filename} 파일도 ${competition.overwritten?'덮어써서 최신화':'추가 저장'}했습니다.`:' 예선·본선 맵 추가 저장은 취소했습니다.';
  }
 }catch(e){$('gps-export-status').textContent=e.message;throw e;}finally{busy=false;update();}}
 $('gps-export-save').onclick=()=>save().catch(e=>{$('gps-export-status').textContent=e.message;});
 window.gpsExport={save,get busy(){return busy;}};
 window.addEventListener('dashboard:modechange',()=>{if(dashboardModes.current==='map-build'&&dashboardModes.buildStep==='export'&&gpsProject.current){input.value=finalStageName(gpsProject.current.filename);saved=null;effective=null;renderSummary();const request=++summaryVersion;gpsProject.api('/api/gps/projects/lane-source?filename='+encodeURIComponent(gpsProject.current.filename)+'&final=1').then(data=>{if(request===summaryVersion){effective=data;renderSummary();}}).catch(e=>{if(request===summaryVersion)$('gps-export-status').textContent=e.message;});$('gps-export-status').textContent='이름을 변경하면 최종 저장 시 기존 작업 파일 이름도 변경됩니다.';update();}});
 window.addEventListener('gps:projectchange',()=>{summaryVersion++;saved=null;effective=null;$('gps-export-summary').replaceChildren();});
})();
