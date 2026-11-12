// Thin ABI only: algorithms and wire conversion come from control_manager.
#include "control_manager/core/tracking.hxx"
#include <cmath>
#include <vector>
namespace cm = control_manager::core;
extern "C" int stop_pp(const double *xy, int count, double speed, double *angle) {
  try {
    std::vector<cm::Point> path;
    for (int i=0;i<count;++i) path.push_back({xy[2*i],xy[2*i+1]});
    cm::TrackingState state;
    state.localization_valid=true; state.speed_valid=true; state.speed_mps=speed;
    cm::AdaptivePurePursuit pp(cm::PurePursuitConfig{});
    const auto result=pp.compute(state,path);
    if (!result.valid || result.goal_reached) return 0;
    *angle=result.steering_rad;
    return 1;
  } catch (...) { return 0; }
}
extern "C" void stop_raw(double angle,double speed,int brake,double zero,double diameter,float *out) {
  cm::Command command;
  command.target_steer_rad=angle; command.target_speed_mps=speed;
  command.target_brake=brake!=0; command.valid=true;
  const auto raw=cm::actuatorRaw(command,cm::ActuatorConversionConfig{diameter,17.01,891.387,zero});
  for (int i=0;i<3;++i) out[i]=raw[i];
}
