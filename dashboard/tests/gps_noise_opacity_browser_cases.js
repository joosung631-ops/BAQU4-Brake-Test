/* Run against isolated noise-map.json and merge-map.json fixtures. */
async function gpsNoiseOpacityBrowserCases(){
 const $=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);};
 const wait=async f=>{for(let i=0;i<400;i++){if(f())return;await new Promise(r=>setTimeout(r,25));}throw Error('timeout: '+f);};
 async function open(name){
  await dashboardModes.set('map-build');await wait(()=>[...$('gps-project-files').options].some(o=>JSON.parse(o.value).filename===name));
  $('gps-project-method').value='edit';$('gps-project-method').dispatchEvent(new Event('change'));
  $('gps-project-files').value=[...$('gps-project-files').options].find(o=>JSON.parse(o.value).filename===name).value;
  $('gps-project-open').click();await wait(()=>!gpsProject.busy&&gpsProject.current?.filename.endsWith(name));
 }
 const go=async(step,editor)=>{await dashboardModes.setBuildStep(step);await wait(()=>dashboardModes.buildStep===step&&!window[editor].busy);};
 const opacity=value=>{$('gps-noise-opacity').value=String(value);$('gps-noise-opacity').dispatchEvent(new Event('input'));};
 const snapshot=()=>JSON.stringify(gpsProject.current.project.stages);
 await open('noise-map.json');assert($('gps-noise-controls').hidden,'Hidden before noise removal');
 await go('points','gpsEditor');assert($('gps-noise-controls').hidden,'Noise editor keeps its exclusion controls');
 const editor=await gpsProject.api('/api/gps/projects/editor?step=points&filename='+encodeURIComponent(gpsProject.current.filename));
 const specs=editor.review.tracks.map(t=>({id:t.id,excluded_seq:[3,...Array.from({length:100},(_,i)=>i+7)],start_seq:2,end_seq:105}));
 await gpsProject.save(3,{dataset_id:editor.review.dataset_id,tracks:specs});
 // Reload the editor with the saved exclusions so autosave cannot replace them.
 window.dispatchEvent(new Event('gps:projectchange'));await dashboardModes.setBuildStep('points');await wait(()=>!gpsEditor.busy);
 await go('add-points','gpsAdditions');
 const scenes=[];
 function scene(step,id,count=102){
  const c=$(id);assert(!$('gps-noise-controls').hidden,'Slider visible in '+step);
  assert(Number(c.dataset.noisePointCount)===count,'Only excluded fixes in '+step+': '+c.dataset.noisePointCount);
  const before=snapshot();opacity(0);assert(c.dataset.noiseAlpha==='0'&&c.dataset.noiseVisiblePointCount==='0','0% hides noise immediately in '+step);
  opacity(45);assert(c.dataset.noiseAlpha==='0.45'&&Number(c.dataset.noiseVisiblePointCount)>0,'45% shows noise immediately in '+step);
  opacity(100);assert(c.dataset.noiseAlpha==='1','100% opaque in '+step);
  assert(snapshot()===before,'Display settings preserve calculation inputs in '+step);
  opacity(18);scenes.push(step);
 }
 scene('additions','gps-add-canvas');assert($('gps-add-canvas').dataset.pointCount==='4','Excluded points absent from editor inputs');
 // Probe actual canvas alpha away from grid/active points, with 100 coincident fixes.
 const probe=document.createElement('canvas');probe.width=200;probe.height=200;
 const ctx=probe.getContext('2d'),projection=()=>({e:0,n:0});
 opacity(18);drawGpsReference(ctx,200,200,1,0,0,projection);
 const alpha=ctx.getImageData(100,100,1,1).data[3];assert(alpha>=45&&alpha<=47,'Overlapping noise stays at 18%: '+alpha);
 opacity(0);ctx.clearRect(0,0,200,200);drawGpsReference(ctx,200,200,1,0,0,projection);assert(ctx.getImageData(100,100,1,1).data[3]===0,'Hidden layer paints no pixels');
 opacity(100);drawGpsReference(ctx,200,200,1,0,0,projection);assert(ctx.getImageData(100,100,1,1).data[3]===255,'100% paints opaque pixels');opacity(18);
 await go('matching','gpsMerger');scene('within-bag merge','gps-merge-canvas');
 await go('fusion','gpsFusion');scene('cross-bag merge','gps-fusion-canvas');
 await go('ordering','gpsOrdering');scene('ordering','gps-order-canvas');
 $('gps-order-auto').click();await wait(()=>!gpsOrdering.busy&&!$('gps-order-save').disabled);
 await go('path','gpsPath');scene('path','gps-path-canvas');assert($('gps-path-canvas').dataset.pointCount==='4','Only retained waypoints generate path');
 await go('lane','gpsLane');scene('lanes','gps-lane-canvas');
 $('gps-lane-width-input').value='3.2';$('gps-lane-width-input').dispatchEvent(new Event('input'));$('gps-lane-apply').click();await wait(()=>!gpsLane.busy&&!$('gps-lane-save').disabled);
 await go('sections','gpsSections');scene('sections','gps-section-canvas');
 await go('validation','gpsLane');scene('validation','gps-lane-canvas');
 await go('export','gpsLane');scene('export','gps-lane-canvas');
 opacity(0);const result=await gpsProject.finalize('noise-final.json');
 assert(gpsProject.current.project.stages['3'].tracks[0].excluded_seq.length===102,'Export keeps exclusions');
 await dashboardModes.set('none');await open('merge-map.json');await go('points','gpsEditor');
 const mergeEditor=await gpsProject.api('/api/gps/projects/editor?step=points&filename='+encodeURIComponent(gpsProject.current.filename));
 await gpsProject.save(3,{dataset_id:mergeEditor.review.dataset_id,tracks:mergeEditor.review.tracks.map(t=>({id:t.id,excluded_seq:[3]}))});
 window.dispatchEvent(new Event('gps:projectchange'));await dashboardModes.setBuildStep('points');await wait(()=>!gpsEditor.busy);await go('add-points','gpsAdditions');
 assert($('gps-noise-opacity').value==='0'&&$('gps-add-canvas').dataset.noiseAlpha==='0','Hidden setting persists between projects');
 scene('MAP placement','gps-add-canvas',1);
 assert($('gps-add-canvas').dataset.referencePointCount==='106','Original MAP reference is a separate layer');
 opacity(37);assert(localStorage.getItem('dashboard.gpsNoiseOpacity')==='37','Browser stores selected opacity');
 return {result:'PASS',scenes,overlapAlpha:alpha,export:result.export.filename};
}
