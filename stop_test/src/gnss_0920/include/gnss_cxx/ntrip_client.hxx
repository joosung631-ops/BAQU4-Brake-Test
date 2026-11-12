#pragma once

#include <atomic>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <mutex>
#include <optional>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

// NTRIP v1 client used to feed RTK corrections (RTCM) to the receiver. Like
// nmea/geodesy this file is ROS-independent so it can be unit tested alone.
namespace gnss_cxx::ntrip {

struct Config {
  std::string host;
  int port{2101};
  std::string mountpoint;
  std::string username;
  std::string password;
  double gga_interval_s{5.0};
  double connect_timeout_s{5.0};
  double data_timeout_s{10.0};
  double reconnect_delay_s{5.0};
  std::string user_agent{"NTRIP baqu4-gnss/0.1"};
};

enum class ResponseStatus {
  kIncomplete,
  kOk,
  kSourcetable,
  kUnauthorized,
  kError,
};

struct Response {
  ResponseStatus status{ResponseStatus::kIncomplete};
  // Number of leading bytes that belong to the caster reply, not to the stream.
  std::size_t header_length{0};
  bool chunked{false};
  std::string status_line;
};

[[nodiscard]] std::string base64Encode(std::string_view input);
[[nodiscard]] std::string buildRequest(const Config & config);
[[nodiscard]] Response parseResponse(std::string_view buffer);
[[nodiscard]] std::vector<std::string> sourcetableMountpoints(std::string_view table);

// VRS casters need the rover position as a GGA sentence. Any talker ($GNGGA,
// $GBGGA, ...) is rewritten to $GPGGA, which every caster accepts, and the
// checksum is recomputed. Returns nullopt unless the input is a valid GGA.
[[nodiscard]] std::optional<std::string> normalizeGgaForCaster(std::string_view sentence);

enum class State {
  kStopped,
  kWaitingForGga,
  kConnecting,
  kStreaming,
  kBackoff,
};

[[nodiscard]] const char * toString(State state) noexcept;

enum class LogLevel {
  kInfo,
  kWarn,
  kError,
};

struct Snapshot {
  State state{State::kStopped};
  std::uint64_t bytes_received{0};
  std::uint64_t gga_sent{0};
  std::uint64_t connections{0};
  // Negative until the current session has delivered its first byte.
  double seconds_since_data{-1.0};
  std::string last_error;
};

class Client {
 public:
  // Called on the client thread with raw correction bytes. Must not throw.
  using RtcmSink = std::function<void(const std::uint8_t *, std::size_t)>;
  // Called on the client thread. Returns a complete GGA sentence without line
  // ending, or nullopt while no usable position exists.
  using GgaSource = std::function<std::optional<std::string>()>;
  using Logger = std::function<void(LogLevel, const std::string &)>;

  Client(Config config, RtcmSink sink, GgaSource gga_source, Logger logger);
  ~Client();

  Client(const Client &) = delete;
  Client & operator=(const Client &) = delete;

  void start();
  void stop();
  [[nodiscard]] Snapshot snapshot() const;

 private:
  void run();
  bool session();
  bool waitOrStop(double seconds);
  bool stopRequested() const noexcept;
  void setState(State state) noexcept;
  void setError(const std::string & message);
  void log(LogLevel level, const std::string & message) const;
  void forward(const std::uint8_t * data, std::size_t size, bool & stream_started);

  // Returns a connected descriptor, or -1 with the reason in `error`.
  int connectSocket(std::string & error);
  bool sendAll(int descriptor, std::string_view data);

  Config config_;
  RtcmSink sink_;
  GgaSource gga_source_;
  Logger logger_;

  std::thread thread_;
  mutable std::mutex stop_mutex_;
  std::condition_variable stop_condition_;
  std::atomic<bool> stop_requested_{false};

  std::atomic<State> state_{State::kStopped};
  std::atomic<std::uint64_t> bytes_received_{0};
  std::atomic<std::uint64_t> gga_sent_{0};
  std::atomic<std::uint64_t> connections_{0};
  std::atomic<std::int64_t> last_data_ns_{0};
  std::uint64_t consecutive_failures_{0};

  mutable std::mutex error_mutex_;
  std::string last_error_;
};

}  // namespace gnss_cxx::ntrip
