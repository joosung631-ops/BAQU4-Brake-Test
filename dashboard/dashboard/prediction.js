/* Constant-steering, no-slip reference geometry, not a vehicle dynamics model. */
(() => {
  function geometry(model,plane){
    if(!model||!plane)return null;
    const required=['angle_deg','wheelbase_m','width_m','lidar_x_m','lidar_y_m','yaw_deg'];
    if(required.some(k=>!Number.isFinite(model[k]))||model.wheelbase_m<=0||model.width_m<=0)return null;
    const curvature=Math.tan(model.angle_deg*Math.PI/180)/model.wheelbase_m;
    const yaw=model.yaw_deg*Math.PI/180,c=Math.cos(yaw),s=Math.sin(yaw);
    const sensor=(x,y)=>{const dx=x-model.lidar_x_m,dy=y-model.lidar_y_m,rx=-(c*dx+s*dy),ry=-(-s*dx+c*dy);return [rx,ry,plane[0]*rx+plane[1]*ry+plane[2]+.18];};
    const pose=d=>Math.abs(curvature)<1e-8?[d,0,0]:[Math.sin(curvature*d)/curvature,(1-Math.cos(curvature*d))/curvature,curvature*d];
    const center=[],left=[],right=[];
    for(let i=0;i<=40;i++){
      const [x,y,a]=pose(i*.25),nx=-Math.sin(a),ny=Math.cos(a),half=model.width_m/2;
      center.push(sensor(x,y));left.push(sensor(x+nx*half,y+ny*half));right.push(sensor(x-nx*half,y-ny*half));
    }
    const body=[[-.225,-model.width_m/2],[1.997,-model.width_m/2],[1.997,model.width_m/2],[-.225,model.width_m/2],[-.225,-model.width_m/2]].map(p=>sensor(...p));
    const [x,y,a]=pose(10),arrow=[sensor(x-.45*Math.cos(a)+.22*Math.sin(a),y-.45*Math.sin(a)-.22*Math.cos(a)),sensor(x,y),sensor(x-.45*Math.cos(a)-.22*Math.sin(a),y-.45*Math.sin(a)+.22*Math.cos(a))];
    return {center,left,right,body,arrow};
  }
  window.BrakePrediction={geometry};
})();
