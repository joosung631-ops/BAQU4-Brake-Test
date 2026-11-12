#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <variant>

namespace gnss_cxx::nmea {

struct Gga {
  std::string utc;
  std::optional<double> latitude_deg;
  std::optional<double> longitude_deg;
  std::optional<double> altitude_m;
  std::optional<double> geoid_separation_m;
  int fix_quality{0};
  int satellites{0};
  std::optional<double> hdop;
  int latitude_fraction_digits{0};
  int longitude_fraction_digits{0};
};

struct Rmc {
  std::string utc;
  bool valid{false};
  std::optional<double> latitude_deg;
  std::optional<double> longitude_deg;
  std::optional<double> speed_mps;
  std::optional<double> cog_deg;
};

struct Vtg {
  bool valid{true};
  std::optional<double> speed_mps;
  std::optional<double> cog_deg;
};

struct Gst {
  std::string utc;
  std::optional<double> rms_m;
  std::optional<double> latitude_sigma_m;
  std::optional<double> longitude_sigma_m;
  std::optional<double> altitude_sigma_m;
};

using Sentence = std::variant<Gga, Rmc, Vtg, Gst>;

enum class ParseError {
  kNone,
  kEmpty,
  kMissingStart,
  kMissingChecksum,
  kBadChecksumText,
  kChecksumMismatch,
  kUnsupported,
  kMalformed,
};

struct ParseResult {
  std::optional<Sentence> sentence;
  ParseError error{ParseError::kNone};

  explicit operator bool() const noexcept { return sentence.has_value(); }
};

[[nodiscard]] ParseResult parseSentence(std::string_view line);
[[nodiscard]] bool validateChecksum(std::string_view line);
[[nodiscard]] std::uint8_t payloadChecksum(std::string_view payload);
[[nodiscard]] std::string addChecksum(std::string_view payload);
[[nodiscard]] std::optional<double> coordinateToDegrees(
    std::string_view coordinate, std::string_view hemisphere, bool latitude);
[[nodiscard]] int coordinateFractionDigits(std::string_view coordinate);
[[nodiscard]] const char * toString(ParseError error) noexcept;

}  // namespace gnss_cxx::nmea

