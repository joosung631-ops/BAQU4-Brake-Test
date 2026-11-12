#pragma once

#include <array>
#include <atomic>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

#include <geometry_msgs/msg/transform_stamped.hpp>
#include <nav_msgs/msg/odometry.hpp>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/nav_sat_fix.hpp>
#include <std_msgs/msg/u_int8.hpp>
#include <tf2_ros/transform_broadcaster.h>

#include "gnss_cxx/geodesy.hxx"
#include "gnss_cxx/covariance.hxx"
#include "gnss_cxx/heading.hxx"
#include "gnss_cxx/nmea.hxx"
#include "gnss_cxx/ntrip_client.hxx"

namespace gnss_cxx {

class SerialPort;

class GnssNode final : public rclcpp::Node {
 public:
  explicit GnssNode(const rclcpp::NodeOptions & options = rclcpp::NodeOptions());
  ~GnssNode() override;

  GnssNode(const GnssNode &) = delete;
  GnssNode & operator=(const GnssNode &) = delete;

 private:
  struct PositionCovariance {
    double east_variance_m2{1.0e12};
    double north_variance_m2{1.0e12};
    double up_variance_m2{1.0e12};
    bool from_gst{false};
  };

  void readParameters();
  void validateParameters() const;
  void loadReplayFile();
  void startInput();
  void stopInput();
  void serialLoop();
  void fileLoop();
  bool processLine(const std::string & line);
  void processSentence(const nmea::Sentence & sentence, double monotonic_time_s);
  void processGga(const nmea::Gga & gga, double monotonic_time_s);
  void processRmc(const nmea::Rmc & rmc, double monotonic_time_s);
  void processVtg(const nmea::Vtg & vtg, double monotonic_time_s);
  void processGst(const nmea::Gst & gst, double monotonic_time_s);
  void configureReceiver(SerialPort & port);
  bool waitForStop(double seconds);
  void publishStatusLine();

  // RTK corrections: the NTRIP client thread reads the rover GGA from here and
  // writes the caster's RTCM bytes to the one serial port this node owns.
  void startNtrip();
  void stopNtrip();
  void storeGgaForNtrip(const std::string & line, double monotonic_time_s);
  std::optional<std::string> ggaForNtrip() const;
  void forwardRtcm(const std::uint8_t * data, std::size_t size);
  std::string ntripStatusText() const;

  bool initializeDatumFrom(const nmea::Gga & gga);
  PositionCovariance positionCovariance(int fix_quality, double monotonic_time_s) const;
  double headingVariance(const HeadingState & heading) const;

  static double monotonicSeconds();
  static const char * fixName(int fix_quality) noexcept;
  static const char * headingSourceName(HeadingSource source) noexcept;

  std::string source_;
  std::string device_;
  int baudrate_{115200};
  std::string nmea_file_;
  double replay_rate_hz_{10.0};
  bool replay_loop_{true};
  std::vector<std::string> replay_lines_;
  std::size_t replay_gga_count_{0};
  bool configure_on_start_{false};
  std::vector<std::string> startup_commands_;
  int startup_command_delay_ms_{100};

  std::string map_frame_;
  std::string base_frame_;
  std::string gnss_frame_;
  bool publish_tf_{false};

  double datum_lat_parameter_{std::numeric_limits<double>::quiet_NaN()};
  double datum_lon_parameter_{std::numeric_limits<double>::quiet_NaN()};
  double datum_alt_parameter_{std::numeric_limits<double>::quiet_NaN()};
  double antenna_offset_x_m_{0.0};
  double antenna_offset_y_m_{0.0};

  double min_speed_for_cog_mps_{0.7};
  double course_timeout_s_{0.5};
  double heading_hold_timeout_s_{3.0};
  double gst_timeout_s_{2.0};
  double cog_heading_sigma_deg_{5.0};
  double heading_hold_growth_deg_per_s_{10.0};
  double speed_sigma_mps_{0.03};

  double sigma_rtk_fixed_m_{0.02};
  double sigma_rtk_float_m_{0.3};
  double sigma_dgps_m_{0.8};
  double sigma_spp_m_{1.5};
  double sigma_no_fix_m_{1.0e6};

  bool ntrip_enabled_{false};
  bool ntrip_credentials_from_environment_{false};
  ntrip::Config ntrip_config_;
  double ntrip_gga_max_age_s_{10.0};

  rclcpp::Publisher<nav_msgs::msg::Odometry>::SharedPtr odom_publisher_;
  rclcpp::Publisher<sensor_msgs::msg::NavSatFix>::SharedPtr fix_publisher_;
  rclcpp::Publisher<std_msgs::msg::UInt8>::SharedPtr status_publisher_;
  std::unique_ptr<tf2_ros::TransformBroadcaster> tf_broadcaster_;
  rclcpp::TimerBase::SharedPtr status_timer_;

  std::atomic<bool> stopping_{false};
  std::thread input_thread_;
  mutable std::mutex stop_mutex_;
  std::condition_variable stop_condition_;

  mutable std::mutex state_mutex_;
  LocalCartesian projector_;
  std::optional<HeadingEstimator> heading_estimator_;
  std::optional<nmea::Gst> latest_gst_;
  double latest_gst_time_s_{-std::numeric_limits<double>::infinity()};
  double latest_rmc_time_s_{-std::numeric_limits<double>::infinity()};
  std::optional<nmea::Gga> latest_gga_;
  HeadingState latest_heading_;
  PositionCovariance latest_position_covariance_;
  std::size_t parsed_sentence_count_{0};
  std::size_t rejected_sentence_count_{0};
  bool warned_low_coordinate_precision_{false};
  bool datum_is_automatic_{true};

  // Guards every write to the receiver. active_port_ is non-null only while
  // serialLoop() holds an open port.
  std::mutex port_mutex_;
  SerialPort * active_port_{nullptr};
  std::atomic<std::uint64_t> rtcm_bytes_forwarded_{0};
  std::atomic<std::uint64_t> rtcm_bytes_dropped_{0};

  mutable std::mutex ntrip_gga_mutex_;
  std::string ntrip_gga_sentence_;
  double ntrip_gga_time_s_{-std::numeric_limits<double>::infinity()};

  // Declared last so it is destroyed first; its thread calls into this node.
  std::unique_ptr<ntrip::Client> ntrip_client_;
};

}  // namespace gnss_cxx
