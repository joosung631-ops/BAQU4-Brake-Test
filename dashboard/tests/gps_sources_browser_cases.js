async function gpsSourcesBrowserCases(){
  const get=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);};
  const wait=async predicate=>{for(let i=0;i<1000;i++){if(predicate())return;await new Promise(r=>setTimeout(r,50));}throw Error('Timeout: '+get('gps-source-status').textContent);};
  dashboardModes.setBuildStep('points');
  await wait(()=>get('gps-source-list').querySelectorAll('input').length>2&&get('gps-test-tracks').children.length===2);
  const baseline=await(await fetch('/api/gps/review')).json();
  assert(get('gps-source-list').querySelectorAll('input:disabled').length>0,'Bags without GPS identified');
  const select=async suffixes=>{
    get('gps-source-clear').click();
    for(const suffix of suffixes){
      const input=[...get('gps-source-list').querySelectorAll('input')].find(x=>x.dataset.bagId===`2026-09-20/2026-09-20_${suffix}`);
      assert(input&&!input.disabled,'Bag available: '+suffix);input.checked=true;input.onchange();
    }
    get('gps-source-load').click();
    await wait(()=>get('gps-source-status').textContent.startsWith('불러오기 완료')&&get('gps-test-tracks').children.length===suffixes.length);
  };
  await select([4,5,6]);
  const raw=await(await fetch('/api/gps/test')).json();
  assert(raw.tracks.length===3&&raw.tracks.some(t=>t.name==='2026-09-20_6'),'All selected bags imported');
  const review=await(await fetch('/api/gps/review')).json();
  for(const previous of baseline.tracks){const current=review.tracks.find(t=>t.id===previous.id);assert(current&&JSON.stringify(current.excluded_seq)===JSON.stringify(previous.excluded_seq)&&current.start_seq===previous.start_seq&&current.end_seq===previous.end_seq,'Saved exclusions and bounds preserved');}
  await select([5]);assert(get('gps-test-tracks').children.length===1,'Single selection replaces displayed set');
  await select([4,5]);assert(get('gps-test-tracks').children.length===2,'Multiple records restored from cache');
  const slider=get('gps-test-tracks').querySelector('input[type=range]');slider.value=10;slider.oninput();
  const smooth=get('gps-test-tracks').querySelector('input[type=number]');smooth.value=Number(smooth.value)+.1;smooth.onchange();
  assert(get('gps-source-load').disabled,'Unsaved work blocks source replacement');
  await get('gps-review-save').onclick();assert(!get('gps-source-load').disabled,'Save allows source replacement');
  return 'Catalog, multiple selection, cached switching, saved edits and unsaved protection: passed';
}
