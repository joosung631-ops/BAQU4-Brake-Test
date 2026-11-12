#pragma once

#include <algorithm>
#include <cmath>
#include <limits>
#include <optional>
#include <stdexcept>

#include "gnss_cxx/geodesy.hxx"

namespace gnss_cxx {

enum class HeadingSource {
  kNone,
  kRmc,
  kVtg,
};

struct HeadingState {
  bool initialized{false};
  bool speed_fresh{false};
  bool using_cog{false};
  bool holding{false};
  double yaw_rad{0.0};
  double speed_mps{0.0};
  double heading_age_s{std::numeric_limits<double>::infinity()};
  HeadingSource source{HeadingSource::kNone};
};

// Holds the last reliable COG yaw below the configured speed threshold. Time
// is supplied by the caller so the class remains ROS-independent and fully
// deterministic in tests.
class HeadingEstimator {
 public:
  HeadingEstimator(double min_speed_for_cog_mps = 0.7, double course_timeout_s = 0.5)
  : min_speed_for_cog_mps_(min_speed_for_cog_mps), course_timeout_s_(course_timeout_s) {
    if (!(min_speed_for_cog_mps_ >= 0.0) || !(course_timeout_s_ > 0.0) ||
        !std::isfinite(min_speed_for_cog_mps_) || !std::isfinite(course_timeout_s_)) {
      throw std::invalid_argument("invalid heading estimator parameters");
    }
  }

  void observe(
      double speed_mps, const std::optional<double> & cog_deg,
      double monotonic_time_s, HeadingSource source) {
    if (!std::isfinite(speed_mps) || speed_mps < 0.0 ||
        !std::isfinite(monotonic_time_s)) {
      return;
    }

    last_speed_mps_ = speed_mps;
    last_course_time_s_ = monotonic_time_s;
    have_speed_ = true;

    if (speed_mps < min_speed_for_cog_mps_ || !cog_deg.has_value() ||
        !std::isfinite(*cog_deg)) {
      return;
    }

    yaw_rad_ = cogToEnuYaw(*cog_deg);
    last_heading_time_s_ = monotonic_time_s;
    source_ = source;
    initialized_ = true;
  }

  [[nodiscard]] HeadingState state(double monotonic_time_s) const {
    HeadingState result;
    result.initialized = initialized_;
    result.yaw_rad = yaw_rad_;
    result.source = source_;

    const double course_age = have_speed_
        ? std::max(0.0, monotonic_time_s - last_course_time_s_)
        : std::numeric_limits<double>::infinity();
    result.speed_fresh = have_speed_ && course_age <= course_timeout_s_;
    result.speed_mps = result.speed_fresh ? last_speed_mps_ : 0.0;

    if (initialized_) {
      result.heading_age_s = std::max(0.0, monotonic_time_s - last_heading_time_s_);
    }
    result.using_cog = initialized_ && result.speed_fresh &&
        result.speed_mps >= min_speed_for_cog_mps_ &&
        result.heading_age_s <= course_timeout_s_;
    result.holding = initialized_ && !result.using_cog;
    return result;
  }

  [[nodiscard]] double minSpeedForCogMps() const noexcept {
    return min_speed_for_cog_mps_;
  }

 private:
  double min_speed_for_cog_mps_{0.7};
  double course_timeout_s_{0.5};
  bool initialized_{false};
  bool have_speed_{false};
  double yaw_rad_{0.0};
  double last_speed_mps_{0.0};
  double last_course_time_s_{0.0};
  double last_heading_time_s_{0.0};
  HeadingSource source_{HeadingSource::kNone};
};

}  // namespace gnss_cxx

