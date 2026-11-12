async function gpsProjectBrowserCases(){
 const $=id=>document.getElementById(id),assert=(v,m)=>{if(!v)throw Error(m);},wait=async f=>{for(let i=0;i<100;i++){if(f())return;await new Promise(r=>setTimeout(r,30));}throw Error('timeout');};
 const point=(seq,lat,lon)=>({seq,lat,lon,segment:0});
 const source={origin:[37,127],tracks:[{id:'blue',name:'blue',points:[0,1,2].map(i=>point(i+1,37+i*.0001,127+i*.0001))},{id:'orange',name:'orange',points:[point(1,37,127),...Array.from({length:100},(_,i)=>point(i+2,37.0001,127.00015))]}]};
 const realFetch=window.fetch;window.fetch=(url,...args)=>String(url).includes('/api/gps/projects/merge-source')?Promise.resolve(new Response(JSON.stringify({source,source_digest:'test',tracks:null}),{headers:{'Content-Type':'application/json'}})):realFetch(url,...args);
 window.gpsProject={current:{filename:'test'},beforeStep:async()=>true,save:async()=>{}};
 await dashboardModes.setBuildStep('matching');const c=$('gps-merge-canvas');await wait(()=>c.dataset.pointCount==='104');
 function alphas(){const data=c.getContext('2d').getImageData(0,0,c.width,c.height).data;let orange=0,blue=0;for(let i=0;i<data.length;i+=4){const [r,g,b,a]=data.slice(i,i+4);if(r>150&&g>40&&g<140&&b<70)orange=Math.max(orange,a);if(r<70&&g>65&&g<150&&b>150)blue=Math.max(blue,a);}return {orange,blue};}
 let a=alphas();assert(a.orange>=40&&a.orange<=47,'100 overlapping inactive orange points remain at 18% opacity');assert(a.blue===255,'Active blue stays opaque');
 $('gps-merge-track').value='1';$('gps-merge-track').dispatchEvent(new Event('change'));a=alphas();assert(a.orange===255,'Active orange becomes opaque');assert(a.blue>=40&&a.blue<=47,'Inactive blue remains faint');
 return 'Overlapping inactive points stay faint; active recording remains opaque in both directions: passed';
}
