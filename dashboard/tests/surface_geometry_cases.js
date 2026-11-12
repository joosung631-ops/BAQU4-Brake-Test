function runSurfaceGeometryTests(buildSurface){
  const check=(condition,message)=>{if(!condition)throw new Error(message);};
  const square=[[.1,.1,.1],[.6,.1,.1],[.1,.6,.1],[.6,.6,.1]];
  check(buildSurface(square).faces===2,'flat square should form two triangles');
  check(buildSurface(square.map(([x,y,z])=>[z,x,y])).faces===2,'vertical wall should form two triangles');
  check(buildSurface(square.slice(0,3)).faces===1,'three neighboring points form one triangle');
  check(buildSurface([[.1,.1,.1],[2.1,.1,.1],[.1,2.1,.1]]).faces===0,'do not bridge a large gap');
  check(buildSurface([[.1,.1,.1],[.6,.1,.1],[.1,.6,.49]]).faces===0,'reject sharp depth changes');
  check(buildSurface([[.1,.1,.1],[.6,.6,.1],[1.1,1.1,.1]]).faces===0,'collinear points have no surface');
  const capped=buildSurface(square,1);check(capped.faces===1&&capped.limited,'bound face storage');
  check(buildSurface([]).faces===0,'empty map has no surface');
  check(buildSurface(square.map(p=>p.map(x=>x-2))).faces===2,'negative coordinates form a surface');
  return {passed:9};
}
