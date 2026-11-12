# Relative steering angle in degrees, after the configurable sign multiplier.
# The board's boot/reset position is zero; straight-ahead calibration is separate.
float32 steer_angle
# Acquisition tick, uint32 milliseconds since the STEERING MCU booted.
# Not ROS time; independent of the motor MCU clock. Wraps at 2^32 ms.
uint32 steer_angle_mcu_ms
# PC-side packet/freshness validity, NOT proof of servo health or calibration.
# On timeout the last value/tick are retained, with validity false.
bool steer_angle_valid
