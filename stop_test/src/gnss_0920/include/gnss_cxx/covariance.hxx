#pragma once

namespace gnss_cxx {

struct FixQualitySigmas {
  double rtk_fixed_m{0.02};
  double rtk_float_m{0.3};
  double dgps_m{0.8};
  double spp_m{1.5};
  double no_fix_m{1.0e6};
};

inline double axisSigmaForFixQuality(
    int fix_quality, const FixQualitySigmas & sigmas = {}) noexcept {
  switch (fix_quality) {
    case 4: return sigmas.rtk_fixed_m;
    case 5: return sigmas.rtk_float_m;
    case 2: return sigmas.dgps_m;
    case 1: return sigmas.spp_m;
    default: return sigmas.no_fix_m;
  }
}

inline double axisVarianceForFixQuality(
    int fix_quality, const FixQualitySigmas & sigmas = {}) noexcept {
  const double sigma = axisSigmaForFixQuality(fix_quality, sigmas);
  return sigma * sigma;
}

}  // namespace gnss_cxx

