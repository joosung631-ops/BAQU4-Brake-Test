async function gpsProjectBrowserCases(){
 const $=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);};
 const api=gpsProject.api,p=await api('/api/gps/projects/load?filename=summary-test.json'),original=structuredClone(p.project);
 window.gpsProject={current:p,api,beforeStep:async()=>true};
 await dashboardModes.setBuildStep('export');const summary=$('gps-export-summary'),text=summary.textContent;
 for(const value of ['2026-09-20_4','371점','2026-09-20_5','163점','534점','267점','320점','214점','193점','127점','174점','19점','146점','0.1 m','4,835점','483.376 m','검증 완료 체크 2개','경로 제약 검증 통과'])assert(text.includes(value),'Summary includes '+value);
 assert(summary.compareDocumentPosition($('gps-export-name'))&Node.DOCUMENT_POSITION_FOLLOWING,'Summary appears before filename');
 assert([...summary.querySelectorAll('[title]')].some(e=>e.title==='2026-09-20/2026-09-20_4'),'Full path available on hover');
 assert(!text.includes('2026-09-20/'),'Only short bag names displayed');
 p.project.stages['8'].statistics.point_count=99999;delete p.project.stages['3'];delete p.project.stages['5'];p.project.stages['11']={bag:'not-confirmed.bag'};
 await dashboardModes.setBuildStep('export');assert(summary.textContent.includes('기록 없음'),'Missing stages are not counted as zero');assert(!summary.textContent.includes('99,999'),'Point count comes from final point data');assert(summary.textContent.includes('검증 완료로 체크한 로스백 없음'),'Playing a bag does not imply validation');
 p.project.stages['8'].valid=false;p.project.stages['8'].validation.solver_converged=false;p.project.stages['8'].validation.violation_samples=3;
 await dashboardModes.setBuildStep('export');assert(summary.textContent.includes('경로 제약 초과 검사점 3점')&&summary.textContent.includes('수렴 여부 확인 필요'),'Recorded calculation issues are displayed');
 p.project=original;await dashboardModes.setBuildStep('export');await new Promise(r=>setTimeout(r,1500));summary.scrollIntoView({block:'start'});
 return 'Real project source counts, exclusion/merge counts, curve sampling/output count, confirmed validation bags, missing records and recorded issues: passed';
}
