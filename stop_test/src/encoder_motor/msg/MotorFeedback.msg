# Actual controller RPM, preserving the board's sign (currently negative forward).
int32 motor_rpm
# Last CAN RPM acquisition tick, uint32 milliseconds since the MOTOR MCU booted.
# Not ROS time; independent of the steering MCU clock. Wraps at 2^32 ms.
uint32 motor_rpm_mcu_ms
# PC-side packet/freshness validity, NOT an MCU health/calibration status flag.
# On timeout the last value/tick are retained, with validity false.
bool motor_rpm_valid
