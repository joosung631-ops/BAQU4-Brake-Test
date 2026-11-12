#include <exception>
#include <memory>

#include <rclcpp/rclcpp.hpp>

#include "gnss_cxx/gnss_node.hxx"

int main(int argc, char ** argv) {
  rclcpp::init(argc, argv);
  try {
    auto node = std::make_shared<gnss_cxx::GnssNode>();
    rclcpp::spin(node);
  } catch (const std::exception & error) {
    RCLCPP_FATAL(rclcpp::get_logger("gnss_node"), "Fatal error: %s", error.what());
    rclcpp::shutdown();
    return 1;
  }
  rclcpp::shutdown();
  return 0;
}
