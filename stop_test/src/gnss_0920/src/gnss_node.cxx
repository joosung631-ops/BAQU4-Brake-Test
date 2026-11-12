#include "gnss_cxx/gnss_node.hxx"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <functional>
#include <iomanip>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <type_traits>
#include <utility>

#include <sensor_msgs/msg/nav_sat_status.hpp>

#include "gnss_cxx/serial_port.hxx"

namespace gnss_cxx {
namespace {

constexpr double kUnobservedVariance = 1.0e12;

bool isUnset(double value) {
  return std::isnan(value);
}

double ggaAltitude(const nmea::Gga & gga) {
  return gga.altitude_m.value_or(0.0) + gga.geoid_separation_m.value_or(0.0);
}

std::string environmentValue(const char * name) {
  const char * value = std::getenv(name);
  return value == nullptr ? std::string() : std::string(value);
}

// The caster sends about one burst per second. Past this silence the status
// line must stop saying OK even though the session is still open.
constexpr double kNtripStaleSeconds = 3.0;

bool hasWhitespaceOrControl(const std::string & text) {
  return std::any_of(text.begin(), text.end(), [](unsigned char character) {
             return character <= 0x20 || character == 0x7f;
           });
}

}  // namespace

GnssNode::GnssNode(const rclcpp::NodeOptions & options)
: Node("gnss_node", options) {
  readParameters();
  validateParameters();
  if (source_ == "file") {
    loadReplayFile();
  }
  heading_estimator_.emplace(min_speed_for_cog_mps_, course_timeout_s_);

  const bool fixed_horizontal_datum =
      std::isfinite(datum_lat_parameter_) && std::isfinite(datum_lon_parameter_);
  datum_is_automatic_ = !fixed_horizontal_datum;
  if (fixed_horizontal_datum && std::isfinite(datum_alt_parameter_)) {
    projector_.reset(datum_lat_parameter_, datum_lon_parameter_, datum_alt_parameter_);
    RCLCPP_INFO(
      get_logger(),
      "[DATUM FIXED lat=%.10f lon=%.10f alt=%.3f] [FRAME %s -> %s]",
      projector_.datumLatitudeDeg(), projector_.datumLongitudeDeg(),
      projector_.datumAltitudeM(), map_frame_.c_str(), base_frame_.c_str());
  }

  odom_publisher_ = create_publisher<nav_msgs::msg::Odometry>(
    "/gnss/odom", rclcpp::SensorDataQoS());
  fix_publisher_ = create_publisher<sensor_msgs::msg::NavSatFix>(
    "/gnss/fix", rclcpp::SensorDataQoS());
  status_publisher_ = create_publisher<std_msgs::msg::UInt8>(
    "/gnss/status", rclcpp::QoS(10).reliable());

  if (publish_tf_) {
    tf_broadcaster_ = std::make_unique<tf2_ros::TransformBroadcaster>(*this);
  }

  status_timer_ = create_wall_timer(
    std::chrono::seconds(1), std::bind(&GnssNode::publishStatusLine, this));

  RCLCPP_INFO(
    get_logger(),
    "GNSS source=%s configure_on_start=%s odom=/gnss/odom fix=/gnss/fix status=/gnss/status",
    source_.c_str(), configure_on_start_ ? "true" : "false");
  if (!configure_on_start_) {
    RCLCPP_INFO(get_logger(), "Receiver configuration is disabled (safe default; receive-only)");
  }
  startInput();
  try {
    startNtrip();
  } catch (...) {
    // The input thread is already running; a joinable std::thread member must
    // not be destroyed by a throwing constructor.
    stopInput();
    throw;
  }
}

GnssNode::~GnssNode() {
  stopNtrip();
  stopInput();
}

void GnssNode::readParameters() {
  source_ = declare_parameter<std::string>("source", "serial");

  // [TUNE] Receiver device and line speed. Confirm with TESTING B-1..B-4.
  //        launch: device, baudrate
  device_ = declare_parameter<std::string>("device", "/dev/ttyUSB0");
  baudrate_ = declare_parameter<int>("baudrate", 115200);

  nmea_file_ = declare_parameter<std::string>("nmea_file", "");
  // [TUNE] File replay fix rate. sample.nmea is authored for 10 Hz playback.
  //        launch: replay_rate_hz
  replay_rate_hz_ = declare_parameter<double>("replay_rate_hz", 10.0);
  replay_loop_ = declare_parameter<bool>("replay_loop", true);

  configure_on_start_ = declare_parameter<bool>("configure_on_start", false);
  startup_commands_ = declare_parameter<std::vector<std::string>>(
    "startup_commands",
    {"UNLOGALL", "GPGGA 0.05", "GPRMC 0.05", "GPVTG 0.05", "GPGST 1", "SAVECONFIG"});
  // [TUNE] Delay between receiver configuration commands. Only used when the
  //        operator explicitly enables configure_on_start.
  //        launch: startup_command_delay_ms
  startup_command_delay_ms_ = declare_parameter<int>("startup_command_delay_ms", 100);

  map_frame_ = declare_parameter<std::string>("map_frame", "map");
  base_frame_ = declare_parameter<std::string>("base_frame", "base_link");
  gnss_frame_ = declare_parameter<std::string>("gnss_frame", "gnss");
  publish_tf_ = declare_parameter<bool>("publish_tf", false);

  // [TUNE] Fixed ENU datum. Leave latitude/longitude as NaN to latch the first
  //        valid fix exactly once. Record and follow must use the same values.
  //        launch: datum_lat, datum_lon, datum_alt
  datum_lat_parameter_ = declare_parameter<double>(
    "datum_lat", std::numeric_limits<double>::quiet_NaN());
  datum_lon_parameter_ = declare_parameter<double>(
    "datum_lon", std::numeric_limits<double>::quiet_NaN());
  datum_alt_parameter_ = declare_parameter<double>(
    "datum_alt", std::numeric_limits<double>::quiet_NaN());

  // [TUNE] Measured rear-axle-centre -> antenna lever arm in base_link axes.
  //        Forward is +x, left is +y. Confirm with TESTING E-4.
  //        launch: antenna_offset_x, antenna_offset_y
  antenna_offset_x_m_ = declare_parameter<double>("antenna_offset_x", 0.0);
  antenna_offset_y_m_ = declare_parameter<double>("antenna_offset_y", 0.0);

  // [TUNE] COG is accepted only above this physical speed.
  //        launch: min_speed_for_cog
  min_speed_for_cog_mps_ = declare_parameter<double>("min_speed_for_cog", 0.7);
  // [TUNE] RMC/VTG freshness and maximum time for retaining the last COG yaw.
  //        launch: course_timeout, heading_hold_timeout
  course_timeout_s_ = declare_parameter<double>("course_timeout", 0.5);
  heading_hold_timeout_s_ = declare_parameter<double>("heading_hold_timeout", 3.0);
  // [TUNE] GST freshness. Older GST uncertainty is discarded in favour of the
  //        conservative fix-quality fallback.
  //        launch: gst_timeout
  gst_timeout_s_ = declare_parameter<double>("gst_timeout", 2.0);

  // [TUNE] Conservative yaw uncertainty model used in odom covariance[35].
  //        launch: cog_heading_sigma_deg, heading_hold_growth_deg_per_s
  cog_heading_sigma_deg_ = declare_parameter<double>("cog_heading_sigma_deg", 5.0);
  heading_hold_growth_deg_per_s_ =
    declare_parameter<double>("heading_hold_growth_deg_per_s", 10.0);
  // [TUNE] Receiver ground-speed sigma used in twist covariance.
  //        launch: speed_sigma
  speed_sigma_mps_ = declare_parameter<double>("speed_sigma", 0.03);

  // [TUNE] Axis-wise fallback position sigmas. TESTING E-2 compares these
  //        against measured stationary scatter. Covariance stores sigma^2.
  //        launch: sigma_rtk_fixed, sigma_rtk_float, sigma_dgps, sigma_spp
  sigma_rtk_fixed_m_ = declare_parameter<double>("sigma_rtk_fixed", 0.02);
  sigma_rtk_float_m_ = declare_parameter<double>("sigma_rtk_float", 0.3);
  sigma_dgps_m_ = declare_parameter<double>("sigma_dgps", 0.8);
  sigma_spp_m_ = declare_parameter<double>("sigma_spp", 1.5);
  sigma_no_fix_m_ = declare_parameter<double>("sigma_no_fix", 1.0e6);

  // [TUNE] RTK corrections over NTRIP. Off by default: the node then never
  //        touches the network. Needs internet on this computer and
  //        source=serial; RTCM goes out on the same serial port NMEA comes in.
  //        launch: ntrip_enabled
  ntrip_enabled_ = declare_parameter<bool>("ntrip_enabled", false);
  // [TUNE] Caster address. Default is the NGII (국토지리정보원) setup that was
  //        confirmed to reach RTK fixed with this receiver: RTS1.ngii.go.kr:2101,
  //        RTK-RTCM32. Spare: RTS2.ngii.go.kr:2101 with VRS-RTCM32 / VRS-RTCM31.
  //        launch: ntrip_host, ntrip_port, ntrip_mountpoint
  ntrip_config_.host = declare_parameter<std::string>("ntrip_host", "RTS1.ngii.go.kr");
  ntrip_config_.port = static_cast<int>(declare_parameter<int>("ntrip_port", 2101));
  ntrip_config_.mountpoint =
    declare_parameter<std::string>("ntrip_mountpoint", "RTK-RTCM32");
  // Credentials. Leave the parameters empty and export NTRIP_USERNAME /
  // NTRIP_PASSWORD instead so they never end up in a launch file or a bag.
  //        launch: ntrip_username, ntrip_password
  ntrip_config_.username = declare_parameter<std::string>("ntrip_username", "");
  ntrip_config_.password = declare_parameter<std::string>("ntrip_password", "");
  if (ntrip_config_.username.empty()) {
    ntrip_config_.username = environmentValue("NTRIP_USERNAME");
    ntrip_credentials_from_environment_ = !ntrip_config_.username.empty();
  }
  if (ntrip_config_.password.empty()) {
    ntrip_config_.password = environmentValue("NTRIP_PASSWORD");
  }
  // [TUNE] How often the rover position is reported to the VRS caster, and how
  //        old a receiver GGA may be before it is no longer reported.
  //        launch: ntrip_gga_interval, ntrip_gga_max_age
  ntrip_config_.gga_interval_s = declare_parameter<double>("ntrip_gga_interval", 5.0);
  ntrip_gga_max_age_s_ = declare_parameter<double>("ntrip_gga_max_age", 10.0);
  // [TUNE] Link supervision: connect/handshake limit, silence after which the
  //        session is dropped, and the pause before reconnecting.
  //        launch: ntrip_connect_timeout, ntrip_data_timeout, ntrip_reconnect_delay
  ntrip_config_.connect_timeout_s = declare_parameter<double>("ntrip_connect_timeout", 5.0);
  ntrip_config_.data_timeout_s = declare_parameter<double>("ntrip_data_timeout", 10.0);
  ntrip_config_.reconnect_delay_s = declare_parameter<double>("ntrip_reconnect_delay", 5.0);
}

void GnssNode::validateParameters() const {
  if (source_ != "serial" && source_ != "file") {
    throw std::invalid_argument("source must be 'serial' or 'file'");
  }
  if (source_ == "serial" && device_.empty()) {
    throw std::invalid_argument("device must not be empty for source=serial");
  }
  if (source_ == "file" && nmea_file_.empty()) {
    throw std::invalid_argument("nmea_file must not be empty for source=file");
  }
  if (baudrate_ <= 0 || !(replay_rate_hz_ > 0.0) ||
      startup_command_delay_ms_ < 0 || !(course_timeout_s_ > 0.0) ||
      !(heading_hold_timeout_s_ > 0.0) || !(gst_timeout_s_ > 0.0) ||
      !(min_speed_for_cog_mps_ >= 0.0) || !(cog_heading_sigma_deg_ > 0.0) ||
      !(heading_hold_growth_deg_per_s_ >= 0.0) || !(speed_sigma_mps_ > 0.0)) {
    throw std::invalid_argument("one or more timing/uncertainty parameters are invalid");
  }
  if (map_frame_.empty() || base_frame_.empty() || gnss_frame_.empty()) {
    throw std::invalid_argument("frame names must not be empty");
  }

  const bool datum_latitude_set = std::isfinite(datum_lat_parameter_);
  const bool datum_longitude_set = std::isfinite(datum_lon_parameter_);
  if (datum_latitude_set != datum_longitude_set) {
    throw std::invalid_argument("datum_lat and datum_lon must be provided together");
  }
  if ((!datum_latitude_set && !isUnset(datum_lat_parameter_)) ||
      (!datum_longitude_set && !isUnset(datum_lon_parameter_)) ||
      (!std::isfinite(datum_alt_parameter_) && !isUnset(datum_alt_parameter_))) {
    throw std::invalid_argument("datum parameters must be finite or NaN");
  }
  if (datum_latitude_set &&
      (datum_lat_parameter_ < -90.0 || datum_lat_parameter_ > 90.0 ||
      datum_lon_parameter_ < -180.0 || datum_lon_parameter_ > 180.0)) {
    throw std::invalid_argument("fixed datum is outside WGS84 bounds");
  }
  if (!std::isfinite(antenna_offset_x_m_) || !std::isfinite(antenna_offset_y_m_)) {
    throw std::invalid_argument("antenna offsets must be finite");
  }
  for (const double sigma : {
      sigma_rtk_fixed_m_, sigma_rtk_float_m_, sigma_dgps_m_,
      sigma_spp_m_, sigma_no_fix_m_}) {
    if (!(sigma > 0.0) || !std::isfinite(sigma)) {
      throw std::invalid_argument("fallback sigmas must be finite and positive");
    }
  }
  for (const auto & command : startup_commands_) {
    if (command.find('\r') != std::string::npos || command.find('\n') != std::string::npos) {
      throw std::invalid_argument("startup_commands entries must not contain line endings");
    }
  }

  if (ntrip_enabled_ && source_ == "serial") {
    if (ntrip_config_.host.empty() || hasWhitespaceOrControl(ntrip_config_.host) ||
        ntrip_config_.mountpoint.empty() || hasWhitespaceOrControl(ntrip_config_.mountpoint)) {
      throw std::invalid_argument(
              "ntrip_host and ntrip_mountpoint must be non-empty and free of whitespace");
    }
    if (ntrip_config_.port <= 0 || ntrip_config_.port > 65535) {
      throw std::invalid_argument("ntrip_port must be within 1..65535");
    }
    if (ntrip_config_.username.empty()) {
      throw std::invalid_argument(
              "ntrip_enabled requires a user name: set ntrip_username or export NTRIP_USERNAME");
    }
    if (ntrip_config_.username.find(':') != std::string::npos ||
        ntrip_config_.username.find_first_of("\r\n") != std::string::npos ||
        ntrip_config_.password.find_first_of("\r\n") != std::string::npos) {
      throw std::invalid_argument("NTRIP credentials contain characters that cannot be sent");
    }
    if (!(ntrip_config_.gga_interval_s > 0.0) || !(ntrip_gga_max_age_s_ > 0.0) ||
        !(ntrip_config_.connect_timeout_s > 0.0) || !(ntrip_config_.data_timeout_s > 0.0) ||
        !(ntrip_config_.reconnect_delay_s > 0.0)) {
      throw std::invalid_argument("one or more NTRIP timing parameters are invalid");
    }
  }
}

void GnssNode::startInput() {
  stopping_.store(false);
  if (source_ == "serial") {
    input_thread_ = std::thread(&GnssNode::serialLoop, this);
  } else {
    input_thread_ = std::thread(&GnssNode::fileLoop, this);
  }
}

void GnssNode::loadReplayFile() {
  std::ifstream stream(nmea_file_);
  if (!stream) {
    throw std::runtime_error("cannot open NMEA replay file: " + nmea_file_);
  }

  std::string line;
  while (std::getline(stream, line)) {
    if (line.empty() || line.front() == '#') {
      continue;
    }
    const auto parsed = nmea::parseSentence(line);
    if (parsed && std::holds_alternative<nmea::Gga>(*parsed.sentence)) {
      ++replay_gga_count_;
    }
    replay_lines_.push_back(line);
  }
  if (replay_lines_.empty() || replay_gga_count_ == 0) {
    throw std::runtime_error("NMEA replay file contains no valid GGA epochs: " + nmea_file_);
  }
}

void GnssNode::stopInput() {
  stopping_.store(true);
  stop_condition_.notify_all();
  if (input_thread_.joinable()) {
    input_thread_.join();
  }
}

bool GnssNode::waitForStop(double seconds) {
  std::unique_lock<std::mutex> lock(stop_mutex_);
  return stop_condition_.wait_for(
    lock, std::chrono::duration<double>(seconds), [this]() {return stopping_.load();});
}

void GnssNode::serialLoop() {
  while (!stopping_.load()) {
    try {
      SerialPort port(device_, baudrate_);
      RCLCPP_INFO(get_logger(), "Opened GNSS serial device %s at %d baud", device_.c_str(), baudrate_);

      if (configure_on_start_) {
        configureReceiver(port);
      }

      // Publishes the open port to forwardRtcm(). Declared after `port`, so it
      // withdraws the pointer before the port is closed on every exit path, and
      // after configureReceiver(), so RTCM chunks (which do not end on frame
      // boundaries) can never be interleaved with a receiver command.
      struct ActivePortScope {
        GnssNode & node;
        ActivePortScope(GnssNode & owner, SerialPort & opened) : node(owner) {
          std::lock_guard<std::mutex> lock(node.port_mutex_);
          node.active_port_ = &opened;
        }
        ~ActivePortScope() {
          std::lock_guard<std::mutex> lock(node.port_mutex_);
          node.active_port_ = nullptr;
        }
      } active_port_scope(*this, port);

      std::string pending;
      std::array<std::uint8_t, 1024> buffer{};
      while (!stopping_.load()) {
        if (!port.waitReadable(std::chrono::milliseconds(200))) {
          continue;
        }
        const std::size_t count = port.readSome(buffer.data(), buffer.size());
        pending.append(reinterpret_cast<const char *>(buffer.data()), count);

        std::size_t newline;
        while ((newline = pending.find('\n')) != std::string::npos) {
          processLine(pending.substr(0, newline));
          pending.erase(0, newline + 1);
        }
        if (pending.size() > 16384) {
          RCLCPP_WARN(get_logger(), "Discarding overlong serial input without newline");
          pending.clear();
        }
      }
    } catch (const std::exception & error) {
      if (!stopping_.load()) {
        RCLCPP_ERROR(
          get_logger(), "GNSS serial error on %s: %s; retrying in 1 s",
          device_.c_str(), error.what());
      }
    }
    if (waitForStop(1.0)) {
      return;
    }
  }
}

void GnssNode::fileLoop() {
  RCLCPP_INFO(
    get_logger(), "Replaying %zu NMEA lines (%zu GGA epochs) from %s at %.2f Hz",
    replay_lines_.size(), replay_gga_count_, nmea_file_.c_str(), replay_rate_hz_);
  const double epoch_period_s = 1.0 / replay_rate_hz_;
  do {
    for (const auto & replay_line : replay_lines_) {
      if (stopping_.load()) {
        return;
      }
      const bool was_gga = processLine(replay_line);
      if (was_gga && waitForStop(epoch_period_s)) {
        return;
      }
    }
  } while (replay_loop_ && !stopping_.load());
  RCLCPP_INFO(get_logger(), "NMEA replay reached end of file");
}

bool GnssNode::processLine(const std::string & line) {
  const auto parsed = nmea::parseSentence(line);
  if (!parsed) {
    if (parsed.error != nmea::ParseError::kUnsupported &&
        parsed.error != nmea::ParseError::kEmpty) {
      std::size_t rejected;
      {
        std::lock_guard<std::mutex> lock(state_mutex_);
        rejected = ++rejected_sentence_count_;
      }
      if (rejected == 1 || rejected % 100 == 0) {
        RCLCPP_WARN(
          get_logger(), "Rejected NMEA sentence (%s), total rejected=%zu",
          nmea::toString(parsed.error), rejected);
      }
    }
    return false;
  }

  const double monotonic_time_s = monotonicSeconds();
  const auto * gga = std::get_if<nmea::Gga>(&*parsed.sentence);
  if (ntrip_enabled_ && gga != nullptr && gga->fix_quality > 0 &&
      gga->latitude_deg.has_value() && gga->longitude_deg.has_value()) {
    storeGgaForNtrip(line, monotonic_time_s);
  }
  processSentence(*parsed.sentence, monotonic_time_s);
  return gga != nullptr;
}

void GnssNode::processSentence(const nmea::Sentence & sentence, double monotonic_time_s) {
  {
    std::lock_guard<std::mutex> lock(state_mutex_);
    ++parsed_sentence_count_;
  }
  std::visit(
    [this, monotonic_time_s](const auto & value) {
      using Value = std::decay_t<decltype(value)>;
      if constexpr (std::is_same_v<Value, nmea::Gga>) {
        processGga(value, monotonic_time_s);
      } else if constexpr (std::is_same_v<Value, nmea::Rmc>) {
        processRmc(value, monotonic_time_s);
      } else if constexpr (std::is_same_v<Value, nmea::Vtg>) {
        processVtg(value, monotonic_time_s);
      } else if constexpr (std::is_same_v<Value, nmea::Gst>) {
        processGst(value, monotonic_time_s);
      }
    }, sentence);
}

void GnssNode::processRmc(const nmea::Rmc & rmc, double monotonic_time_s) {
  if (!rmc.valid || !rmc.speed_mps.has_value()) {
    return;
  }
  std::lock_guard<std::mutex> lock(state_mutex_);
  heading_estimator_->observe(
    *rmc.speed_mps, rmc.cog_deg, monotonic_time_s, HeadingSource::kRmc);
  if (rmc.cog_deg.has_value()) {
    latest_rmc_time_s_ = monotonic_time_s;
  }
}

void GnssNode::processVtg(const nmea::Vtg & vtg, double monotonic_time_s) {
  if (!vtg.valid || !vtg.speed_mps.has_value()) {
    return;
  }
  std::lock_guard<std::mutex> lock(state_mutex_);
  if (monotonic_time_s - latest_rmc_time_s_ <= course_timeout_s_) {
    return;
  }
  heading_estimator_->observe(
    *vtg.speed_mps, vtg.cog_deg, monotonic_time_s, HeadingSource::kVtg);
}

void GnssNode::processGst(const nmea::Gst & gst, double monotonic_time_s) {
  std::lock_guard<std::mutex> lock(state_mutex_);
  latest_gst_ = gst;
  latest_gst_time_s_ = monotonic_time_s;
}

void GnssNode::processGga(const nmea::Gga & gga, double monotonic_time_s) {
  std::lock_guard<std::mutex> lock(state_mutex_);
  latest_gga_ = gga;
  latest_heading_ = heading_estimator_->state(monotonic_time_s);
  latest_position_covariance_ = positionCovariance(gga.fix_quality, monotonic_time_s);

  const rclcpp::Time stamp = now();
  std_msgs::msg::UInt8 status_message;
  status_message.data = static_cast<std::uint8_t>(std::clamp(gga.fix_quality, 0, 255));
  status_publisher_->publish(status_message);

  sensor_msgs::msg::NavSatFix fix_message;
  fix_message.header.stamp = stamp;
  fix_message.header.frame_id = gnss_frame_;
  fix_message.status.service = sensor_msgs::msg::NavSatStatus::SERVICE_GPS;
  if (gga.fix_quality <= 0) {
    fix_message.status.status = sensor_msgs::msg::NavSatStatus::STATUS_NO_FIX;
  } else if (gga.fix_quality == 2) {
    fix_message.status.status = sensor_msgs::msg::NavSatStatus::STATUS_SBAS_FIX;
  } else if (gga.fix_quality == 4 || gga.fix_quality == 5) {
    fix_message.status.status = sensor_msgs::msg::NavSatStatus::STATUS_GBAS_FIX;
  } else {
    fix_message.status.status = sensor_msgs::msg::NavSatStatus::STATUS_FIX;
  }
  fix_message.latitude = gga.latitude_deg.value_or(
    std::numeric_limits<double>::quiet_NaN());
  fix_message.longitude = gga.longitude_deg.value_or(
    std::numeric_limits<double>::quiet_NaN());
  fix_message.altitude = gga.altitude_m.has_value()
    ? ggaAltitude(gga) : std::numeric_limits<double>::quiet_NaN();
  fix_message.position_covariance.fill(0.0);
  fix_message.position_covariance[0] = latest_position_covariance_.east_variance_m2;
  fix_message.position_covariance[4] = latest_position_covariance_.north_variance_m2;
  fix_message.position_covariance[8] = latest_position_covariance_.up_variance_m2;
  fix_message.position_covariance_type = latest_position_covariance_.from_gst
    ? sensor_msgs::msg::NavSatFix::COVARIANCE_TYPE_DIAGONAL_KNOWN
    : sensor_msgs::msg::NavSatFix::COVARIANCE_TYPE_APPROXIMATED;
  fix_publisher_->publish(fix_message);

  if (gga.fix_quality <= 0 || !gga.latitude_deg.has_value() ||
      !gga.longitude_deg.has_value()) {
    return;
  }
  if (!initializeDatumFrom(gga)) {
    return;
  }

  if (!warned_low_coordinate_precision_ &&
      (gga.latitude_fraction_digits < 6 || gga.longitude_fraction_digits < 6)) {
    warned_low_coordinate_precision_ = true;
    RCLCPP_WARN(
      get_logger(),
      "NMEA coordinate precision is only lat=%d/lon=%d fractional minute digits; "
      "RTK centimetre precision may be lost (TESTING B-5)",
      gga.latitude_fraction_digits, gga.longitude_fraction_digits);
  }

  const EnuPoint antenna_position = projector_.forward(
    *gga.latitude_deg, *gga.longitude_deg, ggaAltitude(gga));
  const EnuPoint base_position = latest_heading_.initialized
    ? antennaToBaseLink(
      antenna_position, latest_heading_.yaw_rad,
      antenna_offset_x_m_, antenna_offset_y_m_)
    : antenna_position;

  nav_msgs::msg::Odometry odometry;
  odometry.header.stamp = stamp;
  odometry.header.frame_id = map_frame_;
  odometry.child_frame_id = base_frame_;
  odometry.pose.pose.position.x = base_position.east_m;
  odometry.pose.pose.position.y = base_position.north_m;
  odometry.pose.pose.position.z = base_position.up_m;
  odometry.pose.pose.orientation.x = 0.0;
  odometry.pose.pose.orientation.y = 0.0;
  odometry.pose.pose.orientation.z = std::sin(latest_heading_.yaw_rad * 0.5);
  odometry.pose.pose.orientation.w = std::cos(latest_heading_.yaw_rad * 0.5);

  odometry.pose.covariance.fill(0.0);
  odometry.pose.covariance[0] = latest_position_covariance_.east_variance_m2;
  odometry.pose.covariance[7] = latest_position_covariance_.north_variance_m2;
  odometry.pose.covariance[14] = latest_position_covariance_.up_variance_m2;
  odometry.pose.covariance[21] = kUnobservedVariance;
  odometry.pose.covariance[28] = kUnobservedVariance;
  odometry.pose.covariance[35] = headingVariance(latest_heading_);

  // Odometry twist is explicitly in child_frame_id (base_link). The MVP is
  // forward-only, so GNSS ground speed maps to body +x.
  odometry.twist.twist.linear.x = latest_heading_.speed_mps;
  odometry.twist.covariance.fill(0.0);
  odometry.twist.covariance[0] = latest_heading_.speed_fresh
    ? speed_sigma_mps_ * speed_sigma_mps_ : kUnobservedVariance;
  odometry.twist.covariance[7] = kUnobservedVariance;
  odometry.twist.covariance[14] = kUnobservedVariance;
  odometry.twist.covariance[21] = kUnobservedVariance;
  odometry.twist.covariance[28] = kUnobservedVariance;
  odometry.twist.covariance[35] = kUnobservedVariance;
  odom_publisher_->publish(odometry);

  if (tf_broadcaster_) {
    geometry_msgs::msg::TransformStamped transform;
    transform.header = odometry.header;
    transform.child_frame_id = base_frame_;
    transform.transform.translation.x = base_position.east_m;
    transform.transform.translation.y = base_position.north_m;
    transform.transform.translation.z = base_position.up_m;
    transform.transform.rotation = odometry.pose.pose.orientation;
    tf_broadcaster_->sendTransform(transform);
  }
}

bool GnssNode::initializeDatumFrom(const nmea::Gga & gga) {
  if (projector_.initialized()) {
    return true;
  }
  if (!gga.latitude_deg.has_value() || !gga.longitude_deg.has_value()) {
    return false;
  }

  const bool fixed_horizontal =
      std::isfinite(datum_lat_parameter_) && std::isfinite(datum_lon_parameter_);
  const double latitude = fixed_horizontal ? datum_lat_parameter_ : *gga.latitude_deg;
  const double longitude = fixed_horizontal ? datum_lon_parameter_ : *gga.longitude_deg;
  const double altitude = std::isfinite(datum_alt_parameter_)
    ? datum_alt_parameter_ : ggaAltitude(gga);
  projector_.reset(latitude, longitude, altitude);
  datum_is_automatic_ = !fixed_horizontal;
  if (datum_is_automatic_) {
    const auto result = set_parameters_atomically({
      rclcpp::Parameter("datum_lat", latitude),
      rclcpp::Parameter("datum_lon", longitude),
      rclcpp::Parameter("datum_alt", altitude)});
    if (!result.successful) {
      RCLCPP_WARN(
        get_logger(), "Datum latched, but ROS parameter update failed: %s",
        result.reason.c_str());
    }
  }
  RCLCPP_INFO(
    get_logger(), "[DATUM %s lat=%.10f lon=%.10f alt=%.3f] [FRAME %s -> %s]",
    datum_is_automatic_ ? "AUTO-LATCHED" : "FIXED",
    latitude, longitude, altitude, map_frame_.c_str(), base_frame_.c_str());
  return true;
}

GnssNode::PositionCovariance GnssNode::positionCovariance(
    int fix_quality, double monotonic_time_s) const {
  if (fix_quality > 0 && latest_gst_.has_value() &&
      monotonic_time_s - latest_gst_time_s_ <= gst_timeout_s_ &&
      latest_gst_->latitude_sigma_m.has_value() &&
      latest_gst_->longitude_sigma_m.has_value() &&
      *latest_gst_->latitude_sigma_m > 0.0 &&
      *latest_gst_->longitude_sigma_m > 0.0) {
    const double east_sigma = *latest_gst_->longitude_sigma_m;
    const double north_sigma = *latest_gst_->latitude_sigma_m;
    const double up_sigma =
      latest_gst_->altitude_sigma_m.has_value() && *latest_gst_->altitude_sigma_m > 0.0
      ? *latest_gst_->altitude_sigma_m
      : std::max(east_sigma, north_sigma);
    return {
      east_sigma * east_sigma,
      north_sigma * north_sigma,
      up_sigma * up_sigma,
      true};
  }
  const double sigma = axisSigmaForFixQuality(
    fix_quality,
    {sigma_rtk_fixed_m_, sigma_rtk_float_m_, sigma_dgps_m_,
      sigma_spp_m_, sigma_no_fix_m_});
  return {sigma * sigma, sigma * sigma, sigma * sigma, false};
}

double GnssNode::headingVariance(const HeadingState & heading) const {
  if (!heading.initialized || !std::isfinite(heading.heading_age_s) ||
      heading.heading_age_s > heading_hold_timeout_s_) {
    return kUnobservedVariance;
  }
  const double sigma_deg = cog_heading_sigma_deg_ +
    heading_hold_growth_deg_per_s_ * heading.heading_age_s;
  const double sigma_rad = sigma_deg * kDegToRad;
  return sigma_rad * sigma_rad;
}

void GnssNode::configureReceiver(SerialPort & port) {
  RCLCPP_WARN(
    get_logger(),
    "configure_on_start=true: writing %zu receiver commands, including persistent settings if configured",
    startup_commands_.size());
  for (const auto & command : startup_commands_) {
    if (stopping_.load()) {
      return;
    }
    {
      // RTCM from the NTRIP thread must not be interleaved into a command.
      std::lock_guard<std::mutex> lock(port_mutex_);
      port.writeLine(command);
    }
    RCLCPP_INFO(get_logger(), "Receiver command sent: %s", command.c_str());
    if (waitForStop(static_cast<double>(startup_command_delay_ms_) / 1000.0)) {
      return;
    }
  }
}

void GnssNode::publishStatusLine() {
  const std::string ntrip_status = ntripStatusText();
  std::lock_guard<std::mutex> lock(state_mutex_);
  if (!latest_gga_.has_value()) {
    RCLCPP_INFO(
      get_logger(), "[FIX WAIT] [HDG NONE] [DATUM %s] [NMEA parsed=%zu rejected=%zu] [NTRIP %s]",
      projector_.initialized() ? "SET" : "WAIT", parsed_sentence_count_, rejected_sentence_count_,
      ntrip_status.c_str());
    return;
  }

  const double now_s = monotonicSeconds();
  latest_heading_ = heading_estimator_->state(now_s);
  const double position_std = std::sqrt(
    latest_position_covariance_.east_variance_m2 +
    latest_position_covariance_.north_variance_m2);
  const double hdop = latest_gga_->hdop.value_or(std::numeric_limits<double>::quiet_NaN());

  if (!latest_heading_.initialized) {
    RCLCPP_INFO(
      get_logger(),
      "[FIX %s sat=%d hdop=%.1f std=%.3fm cov=%s] [HDG NONE] [DATUM %s] "
      "[NMEA parsed=%zu rejected=%zu] [NTRIP %s]",
      fixName(latest_gga_->fix_quality), latest_gga_->satellites, hdop, position_std,
      latest_position_covariance_.from_gst ? "GST" : "FALLBACK",
      projector_.initialized() ? (datum_is_automatic_ ? "AUTO" : "FIXED") : "WAIT",
      parsed_sentence_count_, rejected_sentence_count_, ntrip_status.c_str());
    return;
  }

  RCLCPP_INFO(
    get_logger(),
    "[FIX %s sat=%d hdop=%.1f std=%.3fm cov=%s] [HDG %s %.1fdeg hold=%.1fs] "
    "[DATUM %s] [NMEA parsed=%zu rejected=%zu] [NTRIP %s]",
    fixName(latest_gga_->fix_quality), latest_gga_->satellites, hdop, position_std,
    latest_position_covariance_.from_gst ? "GST" : "FALLBACK",
    headingSourceName(latest_heading_.source), enuYawToCog(latest_heading_.yaw_rad),
    latest_heading_.using_cog ? 0.0 : latest_heading_.heading_age_s,
    projector_.initialized() ? (datum_is_automatic_ ? "AUTO" : "FIXED") : "WAIT",
    parsed_sentence_count_, rejected_sentence_count_, ntrip_status.c_str());
}

void GnssNode::startNtrip() {
  if (!ntrip_enabled_) {
    return;
  }
  if (source_ != "serial") {
    RCLCPP_WARN(
      get_logger(), "ntrip_enabled is ignored for source=%s: there is no receiver to correct",
      source_.c_str());
    return;
  }
  RCLCPP_INFO(
    get_logger(), "NTRIP enabled: %s:%d/%s, credentials from %s, GGA every %.1f s",
    ntrip_config_.host.c_str(), ntrip_config_.port, ntrip_config_.mountpoint.c_str(),
    ntrip_credentials_from_environment_ ? "environment" : "parameters",
    ntrip_config_.gga_interval_s);

  ntrip_client_ = std::make_unique<ntrip::Client>(
    ntrip_config_,
    [this](const std::uint8_t * data, std::size_t size) {forwardRtcm(data, size);},
    [this]() {return ggaForNtrip();},
    [this](ntrip::LogLevel level, const std::string & message) {
      switch (level) {
        case ntrip::LogLevel::kInfo:
          RCLCPP_INFO(get_logger(), "%s", message.c_str());
          break;
        case ntrip::LogLevel::kWarn:
          RCLCPP_WARN(get_logger(), "%s", message.c_str());
          break;
        case ntrip::LogLevel::kError:
          RCLCPP_ERROR(get_logger(), "%s", message.c_str());
          break;
      }
    });
  ntrip_client_->start();
}

void GnssNode::stopNtrip() {
  if (ntrip_client_) {
    ntrip_client_->stop();
    ntrip_client_.reset();
  }
}

void GnssNode::storeGgaForNtrip(const std::string & line, double monotonic_time_s) {
  auto normalized = ntrip::normalizeGgaForCaster(line);
  if (!normalized.has_value()) {
    return;
  }
  std::lock_guard<std::mutex> lock(ntrip_gga_mutex_);
  ntrip_gga_sentence_ = std::move(*normalized);
  ntrip_gga_time_s_ = monotonic_time_s;
}

std::optional<std::string> GnssNode::ggaForNtrip() const {
  std::lock_guard<std::mutex> lock(ntrip_gga_mutex_);
  if (ntrip_gga_sentence_.empty() ||
      monotonicSeconds() - ntrip_gga_time_s_ > ntrip_gga_max_age_s_) {
    return std::nullopt;
  }
  return ntrip_gga_sentence_;
}

void GnssNode::forwardRtcm(const std::uint8_t * data, std::size_t size) {
  std::lock_guard<std::mutex> lock(port_mutex_);
  if (active_port_ == nullptr) {
    rtcm_bytes_dropped_.fetch_add(size);
    return;
  }
  try {
    active_port_->writeAll(data, size);
    rtcm_bytes_forwarded_.fetch_add(size);
  } catch (const std::exception & error) {
    rtcm_bytes_dropped_.fetch_add(size);
    RCLCPP_WARN_THROTTLE(
      get_logger(), *get_clock(), 5000, "RTCM could not be written to the receiver: %s",
      error.what());
  }
}

std::string GnssNode::ntripStatusText() const {
  if (!ntrip_client_) {
    return "OFF";
  }
  const ntrip::Snapshot snapshot = ntrip_client_->snapshot();
  char text[192];
  if (snapshot.state == ntrip::State::kStreaming && snapshot.seconds_since_data < 0.0) {
    // Logged in, but this session has not delivered a single byte yet.
    std::snprintf(
      text, sizeof(text), "CONNECTED-NO-DATA gga=%llu",
      static_cast<unsigned long long>(snapshot.gga_sent));
  } else if (snapshot.state == ntrip::State::kStreaming) {
    std::snprintf(
      text, sizeof(text), "%s rx=%.1fkB tx=%.1fkB age=%.1fs gga=%llu",
      snapshot.seconds_since_data > kNtripStaleSeconds ? "NO-DATA" : "OK",
      static_cast<double>(snapshot.bytes_received) / 1024.0,
      static_cast<double>(rtcm_bytes_forwarded_.load()) / 1024.0,
      snapshot.seconds_since_data, static_cast<unsigned long long>(snapshot.gga_sent));
  } else if (snapshot.last_error.empty()) {
    std::snprintf(text, sizeof(text), "%s", ntrip::toString(snapshot.state));
  } else {
    std::snprintf(
      text, sizeof(text), "%s: %.150s", ntrip::toString(snapshot.state),
      snapshot.last_error.c_str());
  }
  return text;
}

double GnssNode::monotonicSeconds() {
  return std::chrono::duration<double>(
    std::chrono::steady_clock::now().time_since_epoch()).count();
}

const char * GnssNode::fixName(int fix_quality) noexcept {
  switch (fix_quality) {
    case 0: return "NO-FIX";
    case 1: return "SPP";
    case 2: return "DGPS";
    case 4: return "RTK-FIX";
    case 5: return "RTK-FLOAT";
    default: return "UNKNOWN";
  }
}

const char * GnssNode::headingSourceName(HeadingSource source) noexcept {
  switch (source) {
    case HeadingSource::kRmc: return "RMC";
    case HeadingSource::kVtg: return "VTG";
    case HeadingSource::kNone: return "NONE";
  }
  return "NONE";
}

}  // namespace gnss_cxx
