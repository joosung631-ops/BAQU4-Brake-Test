#include "gnss_cxx/ntrip_client.hxx"

#include <algorithm>
#include <array>
#include <cctype>
#include <cerrno>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <utility>

#include <fcntl.h>
#include <netdb.h>
#include <poll.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#include "gnss_cxx/nmea.hxx"

namespace gnss_cxx::ntrip {
namespace {

using SteadyClock = std::chrono::steady_clock;

// A caster reply larger than this without a terminator is not a valid reply.
constexpr std::size_t kMaxHeaderBytes = 8192;
constexpr std::size_t kMaxSourcetableBytes = 65536;
constexpr int kPollSliceMs = 200;
constexpr double kGgaWaitPollSeconds = 0.5;
constexpr std::uint64_t kFailureLogPeriod = 10;
constexpr char kAuthenticationRejected[] =
  "authentication rejected (check ntrip_username / ntrip_password; the same account may "
  "also still be logged in from a previous session)";

std::int64_t nowNs() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
    SteadyClock::now().time_since_epoch()).count();
}

double secondsSince(SteadyClock::time_point start) {
  return std::chrono::duration<double>(SteadyClock::now() - start).count();
}

bool startsWith(std::string_view text, std::string_view prefix) {
  return text.size() >= prefix.size() && text.substr(0, prefix.size()) == prefix;
}

std::string toLower(std::string_view text) {
  std::string result(text);
  std::transform(result.begin(), result.end(), result.begin(), [](unsigned char character) {
      return static_cast<char>(std::tolower(character));
    });
  return result;
}

std::string_view trim(std::string_view text) {
  while (!text.empty() && std::isspace(static_cast<unsigned char>(text.front())) != 0) {
    text.remove_prefix(1);
  }
  while (!text.empty() && std::isspace(static_cast<unsigned char>(text.back())) != 0) {
    text.remove_suffix(1);
  }
  return text;
}

int httpStatusCode(std::string_view status_line) {
  const std::size_t space = status_line.find(' ');
  if (space == std::string_view::npos || space + 4 > status_line.size()) {
    return -1;
  }
  int code = 0;
  for (std::size_t index = space + 1; index < space + 4; ++index) {
    const char character = status_line[index];
    if (character < '0' || character > '9') {
      return -1;
    }
    code = code * 10 + (character - '0');
  }
  return code;
}

class SocketGuard {
 public:
  explicit SocketGuard(int descriptor) : descriptor_(descriptor) {}
  ~SocketGuard() {
    if (descriptor_ >= 0) {
      ::close(descriptor_);
    }
  }
  SocketGuard(const SocketGuard &) = delete;
  SocketGuard & operator=(const SocketGuard &) = delete;

 private:
  int descriptor_;
};

}  // namespace

std::string base64Encode(std::string_view input) {
  constexpr char alphabet[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  std::string output;
  output.reserve(((input.size() + 2) / 3) * 4);
  std::size_t index = 0;
  while (index + 2 < input.size()) {
    const std::uint32_t block =
      (static_cast<std::uint32_t>(static_cast<unsigned char>(input[index])) << 16) |
      (static_cast<std::uint32_t>(static_cast<unsigned char>(input[index + 1])) << 8) |
      static_cast<std::uint32_t>(static_cast<unsigned char>(input[index + 2]));
    output.push_back(alphabet[(block >> 18) & 0x3f]);
    output.push_back(alphabet[(block >> 12) & 0x3f]);
    output.push_back(alphabet[(block >> 6) & 0x3f]);
    output.push_back(alphabet[block & 0x3f]);
    index += 3;
  }
  const std::size_t remaining = input.size() - index;
  if (remaining == 1) {
    const std::uint32_t block =
      static_cast<std::uint32_t>(static_cast<unsigned char>(input[index])) << 16;
    output.push_back(alphabet[(block >> 18) & 0x3f]);
    output.push_back(alphabet[(block >> 12) & 0x3f]);
    output.append("==");
  } else if (remaining == 2) {
    const std::uint32_t block =
      (static_cast<std::uint32_t>(static_cast<unsigned char>(input[index])) << 16) |
      (static_cast<std::uint32_t>(static_cast<unsigned char>(input[index + 1])) << 8);
    output.push_back(alphabet[(block >> 18) & 0x3f]);
    output.push_back(alphabet[(block >> 12) & 0x3f]);
    output.push_back(alphabet[(block >> 6) & 0x3f]);
    output.push_back('=');
  }
  return output;
}

std::string buildRequest(const Config & config) {
  std::string_view mountpoint = config.mountpoint;
  while (!mountpoint.empty() && mountpoint.front() == '/') {
    mountpoint.remove_prefix(1);
  }
  // NTRIP v1 form, the same one RTKLIB sends: HTTP/1.0 keeps the caster from
  // answering with chunked transfer encoding.
  std::string request;
  request.append("GET /").append(mountpoint).append(" HTTP/1.0\r\n");
  request.append("User-Agent: ").append(config.user_agent).append("\r\n");
  if (!config.username.empty()) {
    request.append("Authorization: Basic ")
    .append(base64Encode(config.username + ":" + config.password))
    .append("\r\n");
  } else {
    request.append("Accept: */*\r\n");
  }
  request.append("\r\n");
  return request;
}

Response parseResponse(std::string_view buffer) {
  Response response;
  const std::size_t line_end = buffer.find("\r\n");
  if (line_end == std::string_view::npos) {
    if (buffer.size() > kMaxHeaderBytes) {
      response.status = ResponseStatus::kError;
      response.status_line = "caster reply has no line ending";
    }
    return response;
  }
  response.status_line = std::string(buffer.substr(0, line_end));

  if (startsWith(buffer, "ICY 200")) {
    // NTRIP v1: the stream follows the status line. A VRS caster stays silent
    // until it receives a GGA, so the reply must be accepted right here.
    response.status = ResponseStatus::kOk;
    response.header_length = line_end + 2;
    return response;
  }
  if (startsWith(buffer, "SOURCETABLE 200")) {
    response.status = ResponseStatus::kSourcetable;
    response.header_length = line_end + 2;
    return response;
  }
  if (startsWith(buffer, "HTTP/")) {
    const std::size_t header_end = buffer.find("\r\n\r\n");
    if (header_end == std::string_view::npos) {
      if (buffer.size() > kMaxHeaderBytes) {
        response.status = ResponseStatus::kError;
        response.status_line = "caster HTTP header is not terminated";
      }
      return response;
    }
    response.header_length = header_end + 4;
    const std::string header = toLower(buffer.substr(0, header_end));
    const int code = httpStatusCode(response.status_line);
    if (code == 401) {
      response.status = ResponseStatus::kUnauthorized;
    } else if (code != 200) {
      response.status = ResponseStatus::kError;
    } else if (header.find("gnss/sourcetable") != std::string::npos) {
      response.status = ResponseStatus::kSourcetable;
    } else {
      response.status = ResponseStatus::kOk;
      response.chunked = header.find("transfer-encoding: chunked") != std::string::npos;
    }
    return response;
  }
  response.status = response.status_line.find("401") != std::string::npos
    ? ResponseStatus::kUnauthorized : ResponseStatus::kError;
  response.header_length = line_end + 2;
  return response;
}

std::vector<std::string> sourcetableMountpoints(std::string_view table) {
  std::vector<std::string> mountpoints;
  std::size_t position = 0;
  while (position < table.size()) {
    std::size_t line_end = table.find('\n', position);
    if (line_end == std::string_view::npos) {
      line_end = table.size();
    }
    const std::string_view line = trim(table.substr(position, line_end - position));
    if (startsWith(line, "STR;")) {
      const std::string_view rest = line.substr(4);
      const std::size_t separator = rest.find(';');
      const std::string_view name =
        separator == std::string_view::npos ? rest : rest.substr(0, separator);
      if (!name.empty()) {
        mountpoints.emplace_back(name);
      }
    }
    position = line_end + 1;
  }
  return mountpoints;
}

std::optional<std::string> normalizeGgaForCaster(std::string_view sentence) {
  sentence = trim(sentence);
  if (!nmea::validateChecksum(sentence)) {
    return std::nullopt;
  }
  const std::size_t star = sentence.find('*');
  const std::size_t comma = sentence.find(',');
  // "$" + two talker characters + "GGA"
  constexpr std::size_t address_length = 6;
  if (star == std::string_view::npos || comma != address_length ||
      sentence.substr(3, 3) != "GGA") {
    return std::nullopt;
  }
  std::string payload("GPGGA");
  payload.append(sentence.substr(comma, star - comma));
  return nmea::addChecksum(payload);
}

const char * toString(State state) noexcept {
  switch (state) {
    case State::kStopped: return "STOPPED";
    case State::kWaitingForGga: return "WAIT-FIX";
    case State::kConnecting: return "CONNECTING";
    case State::kStreaming: return "STREAMING";
    case State::kBackoff: return "RETRY";
  }
  return "STOPPED";
}

Client::Client(Config config, RtcmSink sink, GgaSource gga_source, Logger logger)
: config_(std::move(config)), sink_(std::move(sink)),
  gga_source_(std::move(gga_source)), logger_(std::move(logger)) {}

Client::~Client() {
  stop();
}

void Client::start() {
  if (thread_.joinable()) {
    return;
  }
  {
    std::lock_guard<std::mutex> lock(stop_mutex_);
    stop_requested_.store(false);
  }
  thread_ = std::thread(&Client::run, this);
}

void Client::stop() {
  {
    // Set under the mutex so a thread about to wait cannot miss the wake-up.
    std::lock_guard<std::mutex> lock(stop_mutex_);
    stop_requested_.store(true);
  }
  stop_condition_.notify_all();
  if (thread_.joinable()) {
    thread_.join();
  }
  setState(State::kStopped);
}

Snapshot Client::snapshot() const {
  Snapshot result;
  result.state = state_.load();
  result.bytes_received = bytes_received_.load();
  result.gga_sent = gga_sent_.load();
  result.connections = connections_.load();
  const std::int64_t last_data = last_data_ns_.load();
  if (last_data > 0) {
    result.seconds_since_data = static_cast<double>(nowNs() - last_data) * 1.0e-9;
  }
  std::lock_guard<std::mutex> lock(error_mutex_);
  result.last_error = last_error_;
  return result;
}

bool Client::waitOrStop(double seconds) {
  std::unique_lock<std::mutex> lock(stop_mutex_);
  return stop_condition_.wait_for(
    lock, std::chrono::duration<double>(seconds), [this]() {return stop_requested_.load();});
}

bool Client::stopRequested() const noexcept {
  return stop_requested_.load();
}

void Client::setState(State state) noexcept {
  state_.store(state);
}

void Client::setError(const std::string & message) {
  std::lock_guard<std::mutex> lock(error_mutex_);
  last_error_ = message;
}

void Client::log(LogLevel level, const std::string & message) const {
  if (logger_) {
    logger_(level, message);
  }
}

void Client::run() {
  while (!stopRequested()) {
    const bool streamed = session();
    if (stopRequested()) {
      break;
    }
    if (streamed) {
      consecutive_failures_ = 0;
    }
    setState(State::kBackoff);
    if (waitOrStop(config_.reconnect_delay_s)) {
      break;
    }
  }
  setState(State::kStopped);
}

// Returns true when the session reached the streaming stage at least once.
bool Client::session() {
  // A VRS caster sends nothing until it knows where the rover is, so there is
  // no point in connecting before the receiver has a position.
  setState(State::kWaitingForGga);
  std::optional<std::string> gga = gga_source_ ? gga_source_() : std::nullopt;
  while (!gga.has_value()) {
    if (waitOrStop(kGgaWaitPollSeconds)) {
      return false;
    }
    gga = gga_source_ ? gga_source_() : std::nullopt;
  }

  auto fail = [this](const std::string & message) {
      setError(message);
      ++consecutive_failures_;
      if (consecutive_failures_ == 1 || consecutive_failures_ % kFailureLogPeriod == 0) {
        log(
          LogLevel::kError,
          "NTRIP " + message + " (failures=" + std::to_string(consecutive_failures_) + ")");
      }
      return false;
    };

  setState(State::kConnecting);
  std::string connect_error;
  const int descriptor = connectSocket(connect_error);
  if (descriptor < 0) {
    return fail(connect_error);
  }
  const SocketGuard guard(descriptor);
  if (stopRequested()) {
    return false;
  }

  if (!sendAll(descriptor, buildRequest(config_))) {
    return fail("request could not be sent");
  }

  // Read the caster reply.
  std::string header;
  Response response;
  const auto reply_start = SteadyClock::now();
  std::array<char, 2048> buffer{};
  while (response.status == ResponseStatus::kIncomplete) {
    if (stopRequested()) {
      return false;
    }
    if (secondsSince(reply_start) > config_.connect_timeout_s) {
      return fail("caster did not reply in time");
    }
    pollfd entry{descriptor, POLLIN, 0};
    const int ready = ::poll(&entry, 1, kPollSliceMs);
    if (ready < 0 && errno != EINTR) {
      return fail(std::string("poll failed: ") + std::strerror(errno));
    }
    if (ready <= 0) {
      continue;
    }
    const ssize_t count = ::recv(descriptor, buffer.data(), buffer.size(), 0);
    if (count == 0) {
      // Some casters send only the status line and close, so the header never
      // becomes complete; do not report that as a network problem.
      if (header.find(" 401") != std::string::npos) {
        return fail(kAuthenticationRejected);
      }
      return fail("caster closed the connection during the handshake");
    }
    if (count < 0) {
      if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK) {
        continue;
      }
      return fail(std::string("recv failed: ") + std::strerror(errno));
    }
    header.append(buffer.data(), static_cast<std::size_t>(count));
    response = parseResponse(header);
  }

  if (response.status == ResponseStatus::kUnauthorized) {
    return fail(kAuthenticationRejected);
  }
  if (response.status == ResponseStatus::kSourcetable) {
    // The table usually spans several TCP segments; read on until the caster
    // finishes so the operator sees every mountpoint name.
    while (!stopRequested() && header.size() < kMaxSourcetableBytes &&
      header.find("ENDSOURCETABLE") == std::string::npos &&
      secondsSince(reply_start) <= config_.connect_timeout_s)
    {
      pollfd entry{descriptor, POLLIN, 0};
      if (::poll(&entry, 1, kPollSliceMs) <= 0) {
        continue;
      }
      const ssize_t count = ::recv(descriptor, buffer.data(), buffer.size(), 0);
      if (count <= 0) {
        break;
      }
      header.append(buffer.data(), static_cast<std::size_t>(count));
    }
    std::string available;
    for (const auto & name : sourcetableMountpoints(header)) {
      available.append(available.empty() ? "" : ", ").append(name);
    }
    return fail(
      "mountpoint '" + config_.mountpoint + "' not found; caster offers: " +
      (available.empty() ? std::string("(none listed)") : available));
  }
  if (response.status != ResponseStatus::kOk) {
    return fail("caster refused the request: " + response.status_line);
  }
  if (response.chunked) {
    return fail("caster uses chunked transfer encoding, which is not supported");
  }

  connections_.fetch_add(1);
  setState(State::kStreaming);
  setError("");
  last_data_ns_.store(0);
  log(
    LogLevel::kInfo,
    "NTRIP connected to " + config_.host + ":" + std::to_string(config_.port) + "/" +
    config_.mountpoint + " (" + response.status_line + ")");

  if (!sendAll(descriptor, *gga + "\r\n")) {
    fail("initial GGA could not be sent");
    return true;
  }
  gga_sent_.fetch_add(1);
  auto last_gga = SteadyClock::now();
  auto last_data = SteadyClock::now();

  bool stream_started = false;
  if (header.size() > response.header_length) {
    forward(
      reinterpret_cast<const std::uint8_t *>(header.data()) + response.header_length,
      header.size() - response.header_length, stream_started);
  }

  while (!stopRequested()) {
    pollfd entry{descriptor, POLLIN, 0};
    const int ready = ::poll(&entry, 1, kPollSliceMs);
    if (ready < 0 && errno != EINTR) {
      fail(std::string("poll failed: ") + std::strerror(errno));
      return true;
    }
    if (ready > 0) {
      const ssize_t count = ::recv(descriptor, buffer.data(), buffer.size(), 0);
      if (count == 0) {
        fail("caster closed the connection");
        return true;
      }
      if (count < 0) {
        if (errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK) {
          fail(std::string("recv failed: ") + std::strerror(errno));
          return true;
        }
      } else {
        last_data = SteadyClock::now();
        forward(
          reinterpret_cast<const std::uint8_t *>(buffer.data()),
          static_cast<std::size_t>(count), stream_started);
      }
    }

    if (secondsSince(last_gga) >= config_.gga_interval_s) {
      last_gga = SteadyClock::now();
      gga = gga_source_ ? gga_source_() : std::nullopt;
      if (gga.has_value()) {
        if (!sendAll(descriptor, *gga + "\r\n")) {
          fail("GGA could not be sent");
          return true;
        }
        gga_sent_.fetch_add(1);
      }
    }
    if (secondsSince(last_data) > config_.data_timeout_s) {
      char message[64];
      std::snprintf(
        message, sizeof(message), "no correction data for %.1f s", config_.data_timeout_s);
      fail(message);
      return true;
    }
  }
  return true;
}

void Client::forward(const std::uint8_t * data, std::size_t size, bool & stream_started) {
  if (!stream_started) {
    // Some casters put an empty line between "ICY 200 OK" and the stream.
    while (size > 0 && (*data == '\r' || *data == '\n')) {
      ++data;
      --size;
    }
    if (size == 0) {
      return;
    }
    stream_started = true;
  }
  bytes_received_.fetch_add(size);
  last_data_ns_.store(nowNs());
  if (sink_) {
    sink_(data, size);
  }
}

int Client::connectSocket(std::string & error) {
  addrinfo hints{};
  hints.ai_family = AF_UNSPEC;
  hints.ai_socktype = SOCK_STREAM;
  addrinfo * results = nullptr;
  const std::string service = std::to_string(config_.port);
  // getaddrinfo cannot be interrupted; gnss.xml bounds it through RES_OPTIONS.
  const int lookup = ::getaddrinfo(config_.host.c_str(), service.c_str(), &hints, &results);
  if (lookup != 0 || results == nullptr) {
    error = "cannot resolve " + config_.host + " (" + ::gai_strerror(lookup) +
      "): no internet or no DNS";
    return -1;
  }
  error = "cannot connect to " + config_.host + ":" + service;

  int connected = -1;
  for (const addrinfo * entry = results; entry != nullptr && connected < 0; entry = entry->ai_next) {
    if (stopRequested()) {
      break;
    }
    const int descriptor =
      ::socket(entry->ai_family, entry->ai_socktype | SOCK_CLOEXEC, entry->ai_protocol);
    if (descriptor < 0) {
      continue;
    }
    const int flags = ::fcntl(descriptor, F_GETFL, 0);
    if (flags < 0 || ::fcntl(descriptor, F_SETFL, flags | O_NONBLOCK) != 0) {
      ::close(descriptor);
      continue;
    }

    int result = ::connect(descriptor, entry->ai_addr, entry->ai_addrlen);
    if (result != 0 && errno == EINPROGRESS) {
      const auto start = SteadyClock::now();
      result = -1;
      while (!stopRequested() && secondsSince(start) <= config_.connect_timeout_s) {
        pollfd waiter{descriptor, POLLOUT, 0};
        const int ready = ::poll(&waiter, 1, kPollSliceMs);
        if (ready < 0 && errno != EINTR) {
          break;
        }
        if (ready > 0) {
          int socket_error = 0;
          socklen_t length = sizeof(socket_error);
          if (::getsockopt(descriptor, SOL_SOCKET, SO_ERROR, &socket_error, &length) == 0 &&
              socket_error == 0) {
            result = 0;
          }
          break;
        }
      }
    }
    if (result == 0) {
      connected = descriptor;
    } else {
      ::close(descriptor);
    }
  }
  ::freeaddrinfo(results);
  return connected;
}

bool Client::sendAll(int descriptor, std::string_view data) {
  const auto start = SteadyClock::now();
  std::size_t sent = 0;
  while (sent < data.size()) {
    if (stopRequested() || secondsSince(start) > config_.connect_timeout_s) {
      return false;
    }
    const ssize_t count =
      ::send(descriptor, data.data() + sent, data.size() - sent, MSG_NOSIGNAL);
    if (count > 0) {
      sent += static_cast<std::size_t>(count);
      continue;
    }
    if (count < 0 && (errno == EINTR)) {
      continue;
    }
    if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
      pollfd waiter{descriptor, POLLOUT, 0};
      ::poll(&waiter, 1, kPollSliceMs);
      continue;
    }
    return false;
  }
  return true;
}

}  // namespace gnss_cxx::ntrip
