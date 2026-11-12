#pragma once

#include <cmath>
#include <stdexcept>

namespace gnss_cxx {

constexpr double kPi = 3.141592653589793238462643383279502884;
constexpr double kDegToRad = kPi / 180.0;
constexpr double kRadToDeg = 180.0 / kPi;

inline double normalizeAngle(double angle_rad) {
  if (!std::isfinite(angle_rad)) {
    return angle_rad;
  }
  angle_rad = std::fmod(angle_rad + kPi, 2.0 * kPi);
  if (angle_rad < 0.0) {
    angle_rad += 2.0 * kPi;
  }
  return angle_rad - kPi;
}

// NMEA course-over-ground is clockwise from true north. ROS ENU yaw is
// counter-clockwise from east.
inline double cogToEnuYaw(double cog_deg) {
  return normalizeAngle((90.0 - cog_deg) * kDegToRad);
}

inline double enuYawToCog(double yaw_rad) {
  double cog_deg = 90.0 - normalizeAngle(yaw_rad) * kRadToDeg;
  cog_deg = std::fmod(cog_deg, 360.0);
  return cog_deg < 0.0 ? cog_deg + 360.0 : cog_deg;
}

struct EnuPoint {
  double east_m{0.0};
  double north_m{0.0};
  double up_m{0.0};
};

struct GeodeticPoint {
  double latitude_deg{0.0};
  double longitude_deg{0.0};
  double altitude_m{0.0};
};

// WGS84 local tangent-plane approximation. It is intentionally small and
// dependency-free; the intended operating area is below 5 km from the datum.
class LocalCartesian {
 public:
  LocalCartesian() = default;

  LocalCartesian(double latitude_deg, double longitude_deg, double altitude_m) {
    reset(latitude_deg, longitude_deg, altitude_m);
  }

  void reset(double latitude_deg, double longitude_deg, double altitude_m) {
    if (!std::isfinite(latitude_deg) || !std::isfinite(longitude_deg) ||
        !std::isfinite(altitude_m) || latitude_deg < -90.0 || latitude_deg > 90.0 ||
        longitude_deg < -180.0 || longitude_deg > 180.0) {
      throw std::invalid_argument("invalid WGS84 datum");
    }

    latitude_deg_ = latitude_deg;
    longitude_deg_ = longitude_deg;
    altitude_m_ = altitude_m;
    latitude_rad_ = latitude_deg * kDegToRad;
    longitude_rad_ = longitude_deg * kDegToRad;

    constexpr double a = 6378137.0;
    constexpr double inverse_flattening = 298.257223563;
    constexpr double flattening = 1.0 / inverse_flattening;
    constexpr double eccentricity_squared = flattening * (2.0 - flattening);

    const double sin_latitude = std::sin(latitude_rad_);
    const double w = std::sqrt(1.0 - eccentricity_squared * sin_latitude * sin_latitude);
    meridional_radius_m_ =
        a * (1.0 - eccentricity_squared) / (w * w * w);
    prime_vertical_radius_m_ = a / w;
    east_scale_m_per_rad_ = prime_vertical_radius_m_ * std::cos(latitude_rad_);
    initialized_ = true;
  }

  [[nodiscard]] bool initialized() const noexcept { return initialized_; }
  [[nodiscard]] double datumLatitudeDeg() const noexcept { return latitude_deg_; }
  [[nodiscard]] double datumLongitudeDeg() const noexcept { return longitude_deg_; }
  [[nodiscard]] double datumAltitudeM() const noexcept { return altitude_m_; }

  [[nodiscard]] EnuPoint forward(
      double latitude_deg, double longitude_deg, double altitude_m) const {
    requireInitialized();
    if (!std::isfinite(latitude_deg) || !std::isfinite(longitude_deg) ||
        !std::isfinite(altitude_m)) {
      throw std::invalid_argument("non-finite WGS84 point");
    }

    const double latitude_rad = latitude_deg * kDegToRad;
    const double longitude_rad = longitude_deg * kDegToRad;
    const double delta_longitude = normalizeAngle(longitude_rad - longitude_rad_);
    return {
        delta_longitude * east_scale_m_per_rad_,
        (latitude_rad - latitude_rad_) * meridional_radius_m_,
        altitude_m - altitude_m_};
  }

  [[nodiscard]] GeodeticPoint reverse(
      double east_m, double north_m, double up_m) const {
    requireInitialized();
    if (!std::isfinite(east_m) || !std::isfinite(north_m) || !std::isfinite(up_m)) {
      throw std::invalid_argument("non-finite ENU point");
    }

    double longitude_rad = longitude_rad_ + east_m / east_scale_m_per_rad_;
    longitude_rad = normalizeAngle(longitude_rad);
    return {
        (latitude_rad_ + north_m / meridional_radius_m_) * kRadToDeg,
        longitude_rad * kRadToDeg,
        altitude_m_ + up_m};
  }

 private:
  void requireInitialized() const {
    if (!initialized_) {
      throw std::logic_error("LocalCartesian datum has not been initialized");
    }
  }

  bool initialized_{false};
  double latitude_deg_{0.0};
  double longitude_deg_{0.0};
  double altitude_m_{0.0};
  double latitude_rad_{0.0};
  double longitude_rad_{0.0};
  double meridional_radius_m_{0.0};
  double prime_vertical_radius_m_{0.0};
  double east_scale_m_per_rad_{0.0};
};

inline EnuPoint antennaToBaseLink(
    const EnuPoint & antenna_position, double yaw_rad,
    double antenna_offset_x_m, double antenna_offset_y_m) {
  const double cos_yaw = std::cos(yaw_rad);
  const double sin_yaw = std::sin(yaw_rad);
  return {
      antenna_position.east_m -
          (antenna_offset_x_m * cos_yaw - antenna_offset_y_m * sin_yaw),
      antenna_position.north_m -
          (antenna_offset_x_m * sin_yaw + antenna_offset_y_m * cos_yaw),
      antenna_position.up_m};
}

}  // namespace gnss_cxx

