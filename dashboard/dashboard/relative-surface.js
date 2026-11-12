/* Local, conservative grid triangulation. No network requests or hole filling. */
'use strict';
const SIZE=.5, MAX_FACES=90000;
function buildSurface(points, maxFaces=MAX_FACES) {
  const cells=new Map(),key=(x,y,z)=>`${x},${y},${z}`;
  for(const p of points){
    const c=p.map(x=>Math.floor(x/SIZE));
    cells.set(key(...c),{p,c});
  }
  const output=new Float32Array(maxFaces*9);let faces=0,limited=false;
  const planes=[[0,1,2],[0,2,1],[1,2,0]];
  function triangle(a,b,c,axis){
    if(!a||!b||!c)return;
    const u=b.map((v,i)=>v-a[i]),v=c.map((v,i)=>v-a[i]);
    const lengths=[u.reduce((s,x)=>s+x*x,0),v.reduce((s,x)=>s+x*x,0),b.reduce((s,x,i)=>s+(x-c[i])**2,0)];
    if(Math.max(...lengths)>.9**2 || Math.min(...lengths)<.05**2)return;
    if(Math.max(a[axis],b[axis],c[axis])-Math.min(a[axis],b[axis],c[axis])>.25)return;
    const n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],area=Math.hypot(...n);
    if(area<.03 || Math.abs(n[axis])/area<.85)return;
    if(faces>=maxFaces){limited=true;return;}
    output.set(a,faces*9);output.set(b,faces*9+3);output.set(c,faces*9+6);faces++;
  }
  outer:for(const {p,c} of cells.values()){
    for(const [a,b,axis] of planes){
      const ca=c.slice(),cb=c.slice(),cc=c.slice();ca[a]++;cb[b]++;cc[a]++;cc[b]++;
      const q=cells.get(key(...ca))?.p,r=cells.get(key(...cb))?.p,s=cells.get(key(...cc))?.p;
      if(q&&r&&s){triangle(p,q,s,axis);triangle(p,s,r,axis);}
      else if(q&&r)triangle(p,q,r,axis);
      else if(q&&s)triangle(p,q,s,axis);
      else if(r&&s)triangle(p,s,r,axis);
      if(limited)break outer;
    }
  }
  return {vertices:output.slice(0,faces*9),faces,limited};
}
const positions=new Map();let timer=null,epoch=0;
self.onmessage=({data})=>{
  if(data.reset){positions.clear();epoch=data.epoch;clearTimeout(timer);timer=null;}
  if(data.epoch!==epoch)return;
  const values=new Float32Array(data.values);
  if(data.reset){for(let i=0;i<values.length;i+=3)positions.set(i/3,Array.from(values.subarray(i,i+3)));}
  else{for(let i=0;i<values.length;i+=4)positions.set(values[i],Array.from(values.subarray(i+1,i+4)));}
  if(timer===null)timer=setTimeout(()=>{
    timer=null;const started=performance.now(),result=buildSurface(positions.values());
    self.postMessage({...result,epoch,ms:performance.now()-started},[result.vertices.buffer]);
  },data.reset?0:2000);
};
