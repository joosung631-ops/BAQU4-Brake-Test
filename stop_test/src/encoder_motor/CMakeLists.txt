cmake_minimum_required(VERSION 3.8)
project(encoder_motor)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/MotorFeedback.msg"
  "msg/SteeringFeedback.msg"
)

# rosidl installs encoder_motor/__init__.py and encoder_motor/msg. Install only
# our runtime modules alongside them, without a second Python package target.
ament_get_python_install_dir(PYTHON_INSTALL_DIR)
install(FILES
  encoder_motor/config.py
  encoder_motor/feedback_freshness.py
  encoder_motor/motor_rpm_node.py
  encoder_motor/steer_angle_node.py
  DESTINATION "${PYTHON_INSTALL_DIR}/${PROJECT_NAME}"
)
install(PROGRAMS scripts/motor_rpm scripts/steer_angle
  DESTINATION lib/${PROJECT_NAME}
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
