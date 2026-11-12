#include "gnss_cxx/nmea.hxx"

#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <iomanip>
#include <limits>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace gnss_cxx::nmea {
namespace {

std::string_view trim(std::string_view value) {
  while (!value.empty() &&
      (value.front() == ' ' || value.front() == '\t' ||
      value.front() == '\r' || value.front() == '\n')) {
    value.remove_prefix(1);
  }
  while (!value.empty() &&
      (value.back() == ' ' || value.back() == '\t' ||
      value.back() == '\r' || value.back() == '\n')) {
    value.remove_suffix(1);
  }
  return value;
}

int hexValue(char character) {
  if (character >= '0' && character <= '9') {
    return character - '0';
  }
  if (character >= 'A' && character <= 'F') {
    return character - 'A' + 10;
  }
  if (character >= 'a' && character <= 'f') {
    return character - 'a' + 10;
  }
  return -1;
}

std::vector<std::string_view> splitFields(std::string_view payload) {
  std::vector<std::string_view> fields;
  std::size_t begin = 0;
  while (true) {
    const std::size_t comma = payload.find(',', begin);
    if (comma == std::string_view::npos) {
      fields.emplace_back(payload.substr(begin));
      break;
    }
    fields.emplace_back(payload.substr(begin, comma - begin));
    begin = comma + 1;
  }
  return fields;
}

std::optional<double> parseDouble(std::string_view field) {
  if (field.empty()) {
    return std::nullopt;
  }
  const std::string text(field);
  char * end = nullptr;
  errno = 0;
  const double value = std::strtod(text.c_str(), &end);
  if (errno == ERANGE || end != text.c_str() + text.size() || !std::isfinite(value)) {
    return std::nullopt;
  }
  return value;
}

std::optional<int> parseInt(std::string_view field) {
  if (field.empty()) {
    return std::nullopt;
  }
  const std::string text(field);
  char * end = nullptr;
  errno = 0;
  const long value = std::strtol(text.c_str(), &end, 10);
  if (errno == ERANGE || end != text.c_str() + text.size() ||
      value < std::numeric_limits<int>::min() ||
      value > std::numeric_limits<int>::max()) {
    return std::nullopt;
  }
  return static_cast<int>(value);
}

bool fieldIsEmptyOrValidDouble(std::string_view field, const std::optional<double> & parsed) {
  return field.empty() || parsed.has_value();
}

std::optional<double> nonNegativeDouble(std::string_view field) {
  const auto value = parseDouble(field);
  if (value.has_value() && *value < 0.0) {
    return std::nullopt;
  }
  return value;
}

ParseResult malformed() {
  return {std::nullopt, ParseError::kMalformed};
}

ParseResult parseGga(const std::vector<std::string_view> & fields) {
  if (fields.size() < 10) {
    return malformed();
  }

  Gga gga;
  gga.utc = std::string(fields[1]);
  const auto fix_quality = parseInt(fields[6]);
  const auto satellites = parseInt(fields[7]);
  gga.hdop = nonNegativeDouble(fields[8]);
  gga.altitude_m = parseDouble(fields[9]);
  if (!fix_quality.has_value() || !satellites.has_value() ||
      *fix_quality < 0 || *satellites < 0 ||
      !fieldIsEmptyOrValidDouble(fields[8], gga.hdop) ||
      !fieldIsEmptyOrValidDouble(fields[9], gga.altitude_m)) {
    return malformed();
  }
  gga.fix_quality = *fix_quality;
  gga.satellites = *satellites;

  if (fields.size() > 11) {
    gga.geoid_separation_m = parseDouble(fields[11]);
    if (!fieldIsEmptyOrValidDouble(fields[11], gga.geoid_separation_m)) {
      return malformed();
    }
  }

  if (!fields[2].empty() || !fields[3].empty()) {
    gga.latitude_deg = coordinateToDegrees(fields[2], fields[3], true);
    if (!gga.latitude_deg.has_value()) {
      return malformed();
    }
  }
  if (!fields[4].empty() || !fields[5].empty()) {
    gga.longitude_deg = coordinateToDegrees(fields[4], fields[5], false);
    if (!gga.longitude_deg.has_value()) {
      return malformed();
    }
  }
  if (gga.latitude_deg.has_value() != gga.longitude_deg.has_value()) {
    return malformed();
  }
  gga.latitude_fraction_digits = coordinateFractionDigits(fields[2]);
  gga.longitude_fraction_digits = coordinateFractionDigits(fields[4]);
  return {Sentence{std::move(gga)}, ParseError::kNone};
}

ParseResult parseRmc(const std::vector<std::string_view> & fields) {
  if (fields.size() < 9 || (fields[2] != "A" && fields[2] != "V")) {
    return malformed();
  }

  Rmc rmc;
  rmc.utc = std::string(fields[1]);
  rmc.valid = fields[2] == "A";
  if (!fields[3].empty() || !fields[4].empty()) {
    rmc.latitude_deg = coordinateToDegrees(fields[3], fields[4], true);
    if (!rmc.latitude_deg.has_value()) {
      return malformed();
    }
  }
  if (!fields[5].empty() || !fields[6].empty()) {
    rmc.longitude_deg = coordinateToDegrees(fields[5], fields[6], false);
    if (!rmc.longitude_deg.has_value()) {
      return malformed();
    }
  }
  if (rmc.latitude_deg.has_value() != rmc.longitude_deg.has_value()) {
    return malformed();
  }

  const auto speed_knots = nonNegativeDouble(fields[7]);
  if (!fieldIsEmptyOrValidDouble(fields[7], speed_knots)) {
    return malformed();
  }
  if (speed_knots.has_value()) {
    constexpr double knots_to_mps = 0.5144444444444445;
    rmc.speed_mps = *speed_knots * knots_to_mps;
  }

  rmc.cog_deg = parseDouble(fields[8]);
  if (!fieldIsEmptyOrValidDouble(fields[8], rmc.cog_deg)) {
    return malformed();
  }
  if (rmc.cog_deg.has_value()) {
    *rmc.cog_deg = std::fmod(*rmc.cog_deg, 360.0);
    if (*rmc.cog_deg < 0.0) {
      *rmc.cog_deg += 360.0;
    }
  }
  return {Sentence{std::move(rmc)}, ParseError::kNone};
}

ParseResult parseVtg(const std::vector<std::string_view> & fields) {
  if (fields.size() < 9) {
    return malformed();
  }

  Vtg vtg;
  if (fields.size() > 9 && !fields[9].empty()) {
    vtg.valid = fields[9] != "N" && fields[9] != "V";
  }
  vtg.cog_deg = parseDouble(fields[1]);
  if (!fieldIsEmptyOrValidDouble(fields[1], vtg.cog_deg)) {
    return malformed();
  }
  if (vtg.cog_deg.has_value()) {
    *vtg.cog_deg = std::fmod(*vtg.cog_deg, 360.0);
    if (*vtg.cog_deg < 0.0) {
      *vtg.cog_deg += 360.0;
    }
  }

  const auto speed_kmh = nonNegativeDouble(fields[7]);
  const auto speed_knots = nonNegativeDouble(fields[5]);
  if (!fieldIsEmptyOrValidDouble(fields[7], speed_kmh) ||
      !fieldIsEmptyOrValidDouble(fields[5], speed_knots)) {
    return malformed();
  }
  if (speed_kmh.has_value()) {
    vtg.speed_mps = *speed_kmh / 3.6;
  } else if (speed_knots.has_value()) {
    constexpr double knots_to_mps = 0.5144444444444445;
    vtg.speed_mps = *speed_knots * knots_to_mps;
  }
  return {Sentence{std::move(vtg)}, ParseError::kNone};
}

ParseResult parseGst(const std::vector<std::string_view> & fields) {
  if (fields.size() < 9) {
    return malformed();
  }
  Gst gst;
  gst.utc = std::string(fields[1]);
  gst.rms_m = nonNegativeDouble(fields[2]);
  gst.latitude_sigma_m = nonNegativeDouble(fields[6]);
  gst.longitude_sigma_m = nonNegativeDouble(fields[7]);
  gst.altitude_sigma_m = nonNegativeDouble(fields[8]);
  if (!fieldIsEmptyOrValidDouble(fields[2], gst.rms_m) ||
      !fieldIsEmptyOrValidDouble(fields[6], gst.latitude_sigma_m) ||
      !fieldIsEmptyOrValidDouble(fields[7], gst.longitude_sigma_m) ||
      !fieldIsEmptyOrValidDouble(fields[8], gst.altitude_sigma_m)) {
    return malformed();
  }
  return {Sentence{std::move(gst)}, ParseError::kNone};
}

}  // namespace

std::uint8_t payloadChecksum(std::string_view payload) {
  std::uint8_t checksum = 0;
  for (const unsigned char character : payload) {
    checksum ^= character;
  }
  return checksum;
}

std::string addChecksum(std::string_view payload) {
  if (!payload.empty() && payload.front() == '$') {
    payload.remove_prefix(1);
  }
  const std::size_t star = payload.find('*');
  if (star != std::string_view::npos) {
    payload = payload.substr(0, star);
  }
  std::ostringstream stream;
  stream << '$' << payload << '*' << std::uppercase << std::hex
         << std::setw(2) << std::setfill('0')
         << static_cast<unsigned int>(payloadChecksum(payload));
  return stream.str();
}

bool validateChecksum(std::string_view line) {
  line = trim(line);
  if (line.size() < 5 || line.front() != '$') {
    return false;
  }
  const std::size_t star = line.find('*');
  if (star == std::string_view::npos || star + 3 != line.size()) {
    return false;
  }
  const int high = hexValue(line[star + 1]);
  const int low = hexValue(line[star + 2]);
  if (high < 0 || low < 0) {
    return false;
  }
  const auto expected = static_cast<std::uint8_t>((high << 4) | low);
  return payloadChecksum(line.substr(1, star - 1)) == expected;
}

std::optional<double> coordinateToDegrees(
    std::string_view coordinate, std::string_view hemisphere, bool latitude) {
  if (coordinate.empty() || hemisphere.size() != 1) {
    return std::nullopt;
  }
  const auto raw = parseDouble(coordinate);
  if (!raw.has_value() || *raw < 0.0) {
    return std::nullopt;
  }

  const double degrees = std::floor(*raw / 100.0);
  const double minutes = *raw - degrees * 100.0;
  const double maximum_degrees = latitude ? 90.0 : 180.0;
  if (minutes < 0.0 || minutes >= 60.0 || degrees > maximum_degrees ||
      (degrees == maximum_degrees && minutes > 0.0)) {
    return std::nullopt;
  }

  double decimal_degrees = degrees + minutes / 60.0;
  const char hemi = hemisphere.front();
  if ((latitude && hemi == 'S') || (!latitude && hemi == 'W')) {
    decimal_degrees = -decimal_degrees;
  } else if ((latitude && hemi != 'N') || (!latitude && hemi != 'E')) {
    return std::nullopt;
  }
  return decimal_degrees;
}

int coordinateFractionDigits(std::string_view coordinate) {
  const std::size_t point = coordinate.find('.');
  if (point == std::string_view::npos) {
    return 0;
  }
  int digits = 0;
  for (std::size_t index = point + 1; index < coordinate.size(); ++index) {
    if (coordinate[index] < '0' || coordinate[index] > '9') {
      break;
    }
    ++digits;
  }
  return digits;
}

ParseResult parseSentence(std::string_view line) {
  line = trim(line);
  if (line.empty()) {
    return {std::nullopt, ParseError::kEmpty};
  }
  if (line.front() != '$') {
    return {std::nullopt, ParseError::kMissingStart};
  }
  const std::size_t star = line.find('*');
  if (star == std::string_view::npos) {
    return {std::nullopt, ParseError::kMissingChecksum};
  }
  if (star + 3 != line.size() || hexValue(line[star + 1]) < 0 ||
      hexValue(line[star + 2]) < 0) {
    return {std::nullopt, ParseError::kBadChecksumText};
  }
  if (!validateChecksum(line)) {
    return {std::nullopt, ParseError::kChecksumMismatch};
  }

  const auto fields = splitFields(line.substr(1, star - 1));
  if (fields.empty() || fields.front().size() < 5) {
    return malformed();
  }
  const std::string_view type = fields.front().substr(fields.front().size() - 3);
  if (type == "GGA") {
    return parseGga(fields);
  }
  if (type == "RMC") {
    return parseRmc(fields);
  }
  if (type == "VTG") {
    return parseVtg(fields);
  }
  if (type == "GST") {
    return parseGst(fields);
  }
  return {std::nullopt, ParseError::kUnsupported};
}

const char * toString(ParseError error) noexcept {
  switch (error) {
    case ParseError::kNone: return "none";
    case ParseError::kEmpty: return "empty";
    case ParseError::kMissingStart: return "missing '$'";
    case ParseError::kMissingChecksum: return "missing checksum";
    case ParseError::kBadChecksumText: return "bad checksum text";
    case ParseError::kChecksumMismatch: return "checksum mismatch";
    case ParseError::kUnsupported: return "unsupported sentence";
    case ParseError::kMalformed: return "malformed sentence";
  }
  return "unknown";
}

}  // namespace gnss_cxx::nmea
