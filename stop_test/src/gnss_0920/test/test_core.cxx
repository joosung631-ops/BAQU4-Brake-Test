#include <cmath>
#include <fstream>
#include <limits>
#include <string>
#include <variant>

#include <gtest/gtest.h>

#include "gnss_cxx/covariance.hxx"
#include "gnss_cxx/geodesy.hxx"
#include "gnss_cxx/heading.hxx"
#include "gnss_cxx/nmea.hxx"

namespace {

double angleError(double first, double second) {
  return std::abs(gnss_cxx::normalizeAngle(first - second));
}

TEST(Nmea, ValidatesChecksumAndRejectsCorruption) {
  const std::string valid = gnss_cxx::nmea::addChecksum(
    "GNGGA,120000.00,3714.34000000,N,12704.98000000,E,4,20,0.6,50.000,M,0.000,M,,");
  EXPECT_TRUE(gnss_cxx::nmea::validateChecksum(valid));
  EXPECT_TRUE(gnss_cxx::nmea::parseSentence(valid));

  std::string corrupt = valid;
  corrupt[10] = corrupt[10] == '0' ? '1' : '0';
  const auto parsed = gnss_cxx::nmea::parseSentence(corrupt);
  EXPECT_FALSE(parsed);
  EXPECT_EQ(parsed.error, gnss_cxx::nmea::ParseError::kChecksumMismatch);
  EXPECT_FALSE(gnss_cxx::nmea::parseSentence("$GNGGA,missing_checksum"));
}

TEST(Nmea, ParsesGgaAndHighPrecisionCoordinates) {
  const auto parsed = gnss_cxx::nmea::parseSentence(gnss_cxx::nmea::addChecksum(
    "GNGGA,120000.00,3714.34000000,N,12704.98000000,E,4,20,0.6,50.000,M,0.000,M,,"));
  ASSERT_TRUE(parsed);
  const auto * gga = std::get_if<gnss_cxx::nmea::Gga>(&*parsed.sentence);
  ASSERT_NE(gga, nullptr);
  ASSERT_TRUE(gga->latitude_deg.has_value());
  ASSERT_TRUE(gga->longitude_deg.has_value());
  EXPECT_NEAR(*gga->latitude_deg, 37.239, 1.0e-10);
  EXPECT_NEAR(*gga->longitude_deg, 127.083, 1.0e-10);
  EXPECT_EQ(gga->fix_quality, 4);
  EXPECT_EQ(gga->satellites, 20);
  EXPECT_EQ(gga->latitude_fraction_digits, 8);
  EXPECT_EQ(gga->longitude_fraction_digits, 8);
}

TEST(Nmea, ParsesRmcVtgAndGst) {
  const auto rmc_result = gnss_cxx::nmea::parseSentence(gnss_cxx::nmea::addChecksum(
    "GNRMC,120000.00,A,3714.34000000,N,12704.98000000,E,2.332,90.0,230826,,,A"));
  ASSERT_TRUE(rmc_result);
  const auto * rmc = std::get_if<gnss_cxx::nmea::Rmc>(&*rmc_result.sentence);
  ASSERT_NE(rmc, nullptr);
  EXPECT_TRUE(rmc->valid);
  ASSERT_TRUE(rmc->speed_mps.has_value());
  ASSERT_TRUE(rmc->cog_deg.has_value());
  EXPECT_NEAR(*rmc->speed_mps, 1.19968, 1.0e-4);
  EXPECT_DOUBLE_EQ(*rmc->cog_deg, 90.0);

  const auto vtg_result = gnss_cxx::nmea::parseSentence(gnss_cxx::nmea::addChecksum(
    "GNVTG,180.0,T,,M,2.332,N,4.320,K,A"));
  ASSERT_TRUE(vtg_result);
  const auto * vtg = std::get_if<gnss_cxx::nmea::Vtg>(&*vtg_result.sentence);
  ASSERT_NE(vtg, nullptr);
  ASSERT_TRUE(vtg->speed_mps.has_value());
  EXPECT_NEAR(*vtg->speed_mps, 1.2, 1.0e-12);

  const auto gst_result = gnss_cxx::nmea::parseSentence(gnss_cxx::nmea::addChecksum(
    "GNGST,120000.00,0.028,0.020,0.020,0.0,0.021,0.022,0.040"));
  ASSERT_TRUE(gst_result);
  const auto * gst = std::get_if<gnss_cxx::nmea::Gst>(&*gst_result.sentence);
  ASSERT_NE(gst, nullptr);
  ASSERT_TRUE(gst->latitude_sigma_m.has_value());
  ASSERT_TRUE(gst->longitude_sigma_m.has_value());
  EXPECT_DOUBLE_EQ(*gst->latitude_sigma_m, 0.021);
  EXPECT_DOUBLE_EQ(*gst->longitude_sigma_m, 0.022);
}

TEST(Nmea, AcceptsNoFixGgaWithoutCoordinates) {
  const auto parsed = gnss_cxx::nmea::parseSentence(gnss_cxx::nmea::addChecksum(
    "GNGGA,120000.00,,,,,0,0,99.9,,,,,,"));
  ASSERT_TRUE(parsed);
  const auto * gga = std::get_if<gnss_cxx::nmea::Gga>(&*parsed.sentence);
  ASSERT_NE(gga, nullptr);
  EXPECT_EQ(gga->fix_quality, 0);
  EXPECT_FALSE(gga->latitude_deg.has_value());
  EXPECT_FALSE(gga->longitude_deg.has_value());
}

TEST(Nmea, RejectsMalformedCoordinateAndUnsupportedSentence) {
  EXPECT_FALSE(gnss_cxx::nmea::coordinateToDegrees("3760.0", "N", true));
  EXPECT_FALSE(gnss_cxx::nmea::coordinateToDegrees("18100.0", "E", false));
  const auto unsupported = gnss_cxx::nmea::parseSentence(
    gnss_cxx::nmea::addChecksum("GNGSV,1,1,00"));
  EXPECT_FALSE(unsupported);
  EXPECT_EQ(unsupported.error, gnss_cxx::nmea::ParseError::kUnsupported);
}

TEST(Geodesy, RoundTripIsBelowOneCentimetre) {
  const gnss_cxx::LocalCartesian projector(37.239, 127.083, 50.0);
  const auto geodetic = projector.reverse(734.25, -512.75, 3.2);
  const auto enu = projector.forward(
    geodetic.latitude_deg, geodetic.longitude_deg, geodetic.altitude_m);
  EXPECT_NEAR(enu.east_m, 734.25, 0.01);
  EXPECT_NEAR(enu.north_m, -512.75, 0.01);
  EXPECT_NEAR(enu.up_m, 3.2, 1.0e-9);
}

TEST(Geodesy, CogToEnuYawCoversAllQuadrants) {
  EXPECT_LT(angleError(gnss_cxx::cogToEnuYaw(0.0), gnss_cxx::kPi / 2.0), 1.0e-12);
  EXPECT_LT(angleError(gnss_cxx::cogToEnuYaw(90.0), 0.0), 1.0e-12);
  EXPECT_LT(angleError(gnss_cxx::cogToEnuYaw(180.0), -gnss_cxx::kPi / 2.0), 1.0e-12);
  EXPECT_LT(angleError(gnss_cxx::cogToEnuYaw(270.0), gnss_cxx::kPi), 1.0e-12);
}

TEST(Geodesy, LeverArmIsRemovedInVehicleAxes) {
  const gnss_cxx::EnuPoint antenna{10.0, 20.0, 1.0};
  const auto east_facing = gnss_cxx::antennaToBaseLink(antenna, 0.0, 1.5, 0.2);
  EXPECT_NEAR(east_facing.east_m, 8.5, 1.0e-12);
  EXPECT_NEAR(east_facing.north_m, 19.8, 1.0e-12);
  const auto north_facing = gnss_cxx::antennaToBaseLink(
    antenna, gnss_cxx::kPi / 2.0, 1.5, 0.2);
  EXPECT_NEAR(north_facing.east_m, 10.2, 1.0e-12);
  EXPECT_NEAR(north_facing.north_m, 18.5, 1.0e-12);
}

TEST(Heading, UpdatesAboveThresholdAndHoldsBelowIt) {
  gnss_cxx::HeadingEstimator estimator(0.7, 0.5);
  estimator.observe(1.2, 90.0, 10.0, gnss_cxx::HeadingSource::kRmc);
  auto state = estimator.state(10.1);
  EXPECT_TRUE(state.initialized);
  EXPECT_TRUE(state.using_cog);
  EXPECT_NEAR(state.yaw_rad, 0.0, 1.0e-12);

  estimator.observe(0.2, 270.0, 10.2, gnss_cxx::HeadingSource::kRmc);
  state = estimator.state(10.3);
  EXPECT_TRUE(state.holding);
  EXPECT_NEAR(state.yaw_rad, 0.0, 1.0e-12);
  EXPECT_NEAR(state.speed_mps, 0.2, 1.0e-12);

  state = estimator.state(10.8);
  EXPECT_FALSE(state.speed_fresh);
  EXPECT_DOUBLE_EQ(state.speed_mps, 0.0);
  EXPECT_TRUE(state.holding);
}

TEST(Covariance, FixQualityValuesAreAxisSigmasSquaredOnce) {
  EXPECT_DOUBLE_EQ(gnss_cxx::axisVarianceForFixQuality(4), 0.0004);
  EXPECT_DOUBLE_EQ(gnss_cxx::axisVarianceForFixQuality(5), 0.09);
  EXPECT_DOUBLE_EQ(gnss_cxx::axisVarianceForFixQuality(2), 0.64);
  EXPECT_DOUBLE_EQ(gnss_cxx::axisVarianceForFixQuality(1), 2.25);
  EXPECT_DOUBLE_EQ(gnss_cxx::axisVarianceForFixQuality(0), 1.0e12);
  EXPECT_NEAR(
    std::sqrt(gnss_cxx::axisVarianceForFixQuality(1) * 2.0),
    1.5 * std::sqrt(2.0), 1.0e-12);
}

TEST(SampleData, EverySentenceHasAValidChecksumAndOneHundredEpochs) {
  const std::string path = std::string(GNSS_CXX_SOURCE_DIR) + "/data/sample.nmea";
  std::ifstream stream(path);
  ASSERT_TRUE(stream) << path;

  std::string line;
  int gga_count = 0;
  int rmc_count = 0;
  int vtg_count = 0;
  int gst_count = 0;
  double first_latitude = std::numeric_limits<double>::quiet_NaN();
  double first_longitude = std::numeric_limits<double>::quiet_NaN();
  while (std::getline(stream, line)) {
    if (line.empty() || line.front() == '#') {
      continue;
    }
    ASSERT_TRUE(gnss_cxx::nmea::validateChecksum(line)) << line;
    const auto parsed = gnss_cxx::nmea::parseSentence(line);
    ASSERT_TRUE(parsed) << line;
    if (const auto * gga = std::get_if<gnss_cxx::nmea::Gga>(&*parsed.sentence)) {
      ++gga_count;
      EXPECT_EQ(gga->fix_quality, 4);
      if (gga_count == 1) {
        first_latitude = *gga->latitude_deg;
        first_longitude = *gga->longitude_deg;
      }
    } else if (const auto * rmc = std::get_if<gnss_cxx::nmea::Rmc>(&*parsed.sentence)) {
      ++rmc_count;
      ASSERT_TRUE(rmc->speed_mps.has_value());
      EXPECT_GT(*rmc->speed_mps, 0.7);
    } else if (std::holds_alternative<gnss_cxx::nmea::Vtg>(*parsed.sentence)) {
      ++vtg_count;
    } else if (std::holds_alternative<gnss_cxx::nmea::Gst>(*parsed.sentence)) {
      ++gst_count;
    }
  }
  EXPECT_EQ(gga_count, 100);
  EXPECT_EQ(rmc_count, 100);
  EXPECT_EQ(vtg_count, 100);
  EXPECT_EQ(gst_count, 100);
  EXPECT_NEAR(first_latitude, 37.239, 1.0e-10);
  EXPECT_NEAR(first_longitude, 127.083, 1.0e-10);
}

}  // namespace
