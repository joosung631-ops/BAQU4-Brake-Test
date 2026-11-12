cmake_minimum_required(VERSION 3.8)
project(gnss_0920 LANGUAGES CXX)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(Threads REQUIRED)

add_library(gnss_core
  src/nmea.cxx
  src/ntrip_client.cxx
  src/serial_port.cxx
)
set_target_properties(gnss_core PROPERTIES OUTPUT_NAME gnss_0920_core)
target_include_directories(gnss_core
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
)
# ntrip_client runs its own std::thread.
target_link_libraries(gnss_core PUBLIC Threads::Threads)

add_executable(gnss_node
  src/gnss_node.cxx
  src/main.cxx
)
target_include_directories(gnss_node PRIVATE include)
target_link_libraries(gnss_node gnss_core Threads::Threads)
ament_target_dependencies(gnss_node
  geometry_msgs
  nav_msgs
  rclcpp
  sensor_msgs
  std_msgs
  tf2
  tf2_ros
)

install(
  TARGETS gnss_core gnss_node
  EXPORT export_gnss_core
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION lib/${PROJECT_NAME}
)
install(DIRECTORY include/ DESTINATION include)
install(DIRECTORY launch data DESTINATION share/${PROJECT_NAME})
install(PROGRAMS scripts/check_gnss.sh DESTINATION lib/${PROJECT_NAME})

ament_export_targets(export_gnss_core HAS_LIBRARY_TARGET)
ament_export_include_directories(include)
ament_export_dependencies(Threads)

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_core test/test_core.cxx)
  target_link_libraries(test_core gnss_core)
  target_include_directories(test_core PRIVATE include)
  target_compile_definitions(test_core PRIVATE GNSS_CXX_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}")

  # Talks to a loopback mock caster only; needs no network and no receiver.
  ament_add_gtest(test_ntrip test/test_ntrip.cxx)
  target_link_libraries(test_ntrip gnss_core)
  target_include_directories(test_ntrip PRIVATE include)
endif()

ament_package()
