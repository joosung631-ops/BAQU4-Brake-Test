#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <functional>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

#include <arpa/inet.h>
#include <netinet/in.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

#include <gtest/gtest.h>

#include "gnss_cxx/nmea.hxx"
#include "gnss_cxx/ntrip_client.hxx"

namespace {

using gnss_cxx::ntrip::Client;
using gnss_cxx::ntrip::Config;
using gnss_cxx::ntrip::LogLevel;
using gnss_cxx::ntrip::ResponseStatus;
using gnss_cxx::ntrip::State;

const char kReceiverGga[] =
  "GNGGA,120000.00,3717.83551131,N,12650.13593011,E,1,20,0.6,31.536,M,0.000,M,,";

bool waitUntil(const std::function<bool()> & condition, double seconds = 3.0) {
  const auto deadline =
    std::chrono::steady_clock::now() + std::chrono::duration<double>(seconds);
  while (std::chrono::steady_clock::now() < deadline) {
    if (condition()) {
      return true;
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
  return condition();
}

// Minimal loopback caster: accepts connections one after another, records the
// request and every line the client uploads, answers with a fixed reply.
class MockCaster {
 public:
  MockCaster(std::string reply, std::string payload, bool close_after_payload)
  : reply_(std::move(reply)), payload_(std::move(payload)),
    close_after_payload_(close_after_payload) {
    listener_ = ::socket(AF_INET, SOCK_STREAM, 0);
    const int enable = 1;
    ::setsockopt(listener_, SOL_SOCKET, SO_REUSEADDR, &enable, sizeof(enable));
    sockaddr_in address{};
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    address.sin_port = 0;
    ::bind(listener_, reinterpret_cast<sockaddr *>(&address), sizeof(address));
    ::listen(listener_, 4);
    socklen_t length = sizeof(address);
    ::getsockname(listener_, reinterpret_cast<sockaddr *>(&address), &length);
    port_ = ntohs(address.sin_port);
    thread_ = std::thread(&MockCaster::serve, this);
  }

  ~MockCaster() {
    stop_.store(true);
    if (thread_.joinable()) {
      thread_.join();
    }
    ::close(listener_);
  }

  int port() const {return port_;}
  int accepted() const {return accepted_.load();}

  std::string request() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return request_;
  }

  std::vector<std::string> uploadedLines() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return uploaded_lines_;
  }

 private:
  void serve() {
    while (!stop_.load()) {
      pollfd waiter{listener_, POLLIN, 0};
      if (::poll(&waiter, 1, 50) <= 0) {
        continue;
      }
      const int client = ::accept(listener_, nullptr, nullptr);
      if (client < 0) {
        continue;
      }
      accepted_.fetch_add(1);
      handle(client);
      ::close(client);
    }
  }

  void handle(int client) {
    std::string received;
    bool replied = false;
    bool payload_sent = false;
    char buffer[1024];
    while (!stop_.load()) {
      pollfd waiter{client, POLLIN, 0};
      const int ready = ::poll(&waiter, 1, 20);
      if (ready > 0) {
        const ssize_t count = ::recv(client, buffer, sizeof(buffer), 0);
        if (count <= 0) {
          return;
        }
        received.append(buffer, static_cast<std::size_t>(count));
      }
      if (!replied) {
        const std::size_t end = received.find("\r\n\r\n");
        if (end == std::string::npos) {
          continue;
        }
        {
          std::lock_guard<std::mutex> lock(mutex_);
          request_ = received.substr(0, end + 4);
        }
        received.erase(0, end + 4);
        ::send(client, reply_.data(), reply_.size(), MSG_NOSIGNAL);
        replied = true;
        if (reply_.rfind("ICY 200", 0) != 0) {
          return;  // refusal: a real caster closes the connection
        }
      }
      std::size_t newline;
      while ((newline = received.find("\r\n")) != std::string::npos) {
        {
          std::lock_guard<std::mutex> lock(mutex_);
          uploaded_lines_.push_back(received.substr(0, newline));
        }
        received.erase(0, newline + 2);
        if (!payload_sent) {
          // Like a VRS caster: stay silent until the first GGA arrives.
          ::send(client, payload_.data(), payload_.size(), MSG_NOSIGNAL);
          payload_sent = true;
          if (close_after_payload_) {
            return;
          }
        }
      }
    }
  }

  std::string reply_;
  std::string payload_;
  bool close_after_payload_;
  int listener_{-1};
  int port_{0};
  std::thread thread_;
  std::atomic<bool> stop_{false};
  std::atomic<int> accepted_{0};
  mutable std::mutex mutex_;
  std::string request_;
  std::vector<std::string> uploaded_lines_;
};

struct Harness {
  std::mutex mutex;
  std::string rtcm;
  std::vector<std::string> errors;
  std::atomic<bool> have_position{true};

  Config config(int port) const {
    Config result;
    result.host = "127.0.0.1";
    result.port = port;
    result.mountpoint = "VRS-RTCM32";
    result.username = "user";
    result.password = "pass";
    result.gga_interval_s = 0.15;
    result.connect_timeout_s = 1.0;
    result.data_timeout_s = 1.0;
    result.reconnect_delay_s = 0.05;
    return result;
  }

  Client::RtcmSink sink() {
    return [this](const std::uint8_t * data, std::size_t size) {
             std::lock_guard<std::mutex> lock(mutex);
             rtcm.append(reinterpret_cast<const char *>(data), size);
           };
  }

  Client::GgaSource ggaSource() {
    return [this]() -> std::optional<std::string> {
             if (!have_position.load()) {
               return std::nullopt;
             }
             return gnss_cxx::ntrip::normalizeGgaForCaster(
               gnss_cxx::nmea::addChecksum(kReceiverGga));
           };
  }

  Client::Logger logger() {
    return [this](LogLevel level, const std::string & message) {
             if (level == LogLevel::kError) {
               std::lock_guard<std::mutex> lock(mutex);
               errors.push_back(message);
             }
           };
  }

  std::string received() {
    std::lock_guard<std::mutex> lock(mutex);
    return rtcm;
  }
};

TEST(NtripBase64, MatchesRfc4648Vectors) {
  EXPECT_EQ(gnss_cxx::ntrip::base64Encode(""), "");
  EXPECT_EQ(gnss_cxx::ntrip::base64Encode("f"), "Zg==");
  EXPECT_EQ(gnss_cxx::ntrip::base64Encode("fo"), "Zm8=");
  EXPECT_EQ(gnss_cxx::ntrip::base64Encode("foo"), "Zm9v");
  EXPECT_EQ(gnss_cxx::ntrip::base64Encode("foobar"), "Zm9vYmFy");
  EXPECT_EQ(gnss_cxx::ntrip::base64Encode("user:pass"), "dXNlcjpwYXNz");
  EXPECT_EQ(gnss_cxx::ntrip::base64Encode(std::string("\xff\xfe\xfd", 3)), "//79");
}

TEST(NtripRequest, IsAnNtripV1RequestWithBasicAuthentication) {
  Config config;
  config.mountpoint = "/VRS-RTCM32";
  config.username = "user";
  config.password = "pass";
  EXPECT_EQ(
    gnss_cxx::ntrip::buildRequest(config),
    "GET /VRS-RTCM32 HTTP/1.0\r\n"
    "User-Agent: NTRIP baqu4-gnss/0.1\r\n"
    "Authorization: Basic dXNlcjpwYXNz\r\n"
    "\r\n");
}

TEST(NtripResponse, AcceptsIcyReplyBeforeAnyPayloadArrives) {
  const auto bare = gnss_cxx::ntrip::parseResponse("ICY 200 OK\r\n");
  EXPECT_EQ(bare.status, ResponseStatus::kOk);
  EXPECT_EQ(bare.header_length, 12u);

  // RTCM is binary: build it with an explicit length so the NUL byte survives.
  const std::string payload("\xd3\x00\x13", 3);
  const std::string with_payload = std::string("ICY 200 OK\r\n") + payload;
  const auto streaming = gnss_cxx::ntrip::parseResponse(with_payload);
  EXPECT_EQ(streaming.status, ResponseStatus::kOk);
  EXPECT_EQ(with_payload.substr(streaming.header_length), payload);

  EXPECT_EQ(gnss_cxx::ntrip::parseResponse("ICY 200").status, ResponseStatus::kIncomplete);
}

TEST(NtripResponse, ClassifiesRefusals) {
  EXPECT_EQ(
    gnss_cxx::ntrip::parseResponse("SOURCETABLE 200 OK\r\nServer: x\r\n").status,
    ResponseStatus::kSourcetable);
  EXPECT_EQ(
    gnss_cxx::ntrip::parseResponse("HTTP/1.1 401 Unauthorized\r\nServer: x\r\n\r\n").status,
    ResponseStatus::kUnauthorized);
  EXPECT_EQ(
    gnss_cxx::ntrip::parseResponse("HTTP/1.0 404 Not Found\r\n\r\n").status,
    ResponseStatus::kError);
  EXPECT_EQ(
    gnss_cxx::ntrip::parseResponse("ERROR - Bad Password 401\r\n").status,
    ResponseStatus::kUnauthorized);
  EXPECT_EQ(
    gnss_cxx::ntrip::parseResponse("HTTP/1.1 200 OK\r\nServer: x\r\n").status,
    ResponseStatus::kIncomplete);
  EXPECT_EQ(
    gnss_cxx::ntrip::parseResponse(std::string(9000, 'x')).status, ResponseStatus::kError);
}

TEST(NtripResponse, RecognisesHttpStreamSourcetableAndChunking) {
  const auto plain = gnss_cxx::ntrip::parseResponse(
    "HTTP/1.1 200 OK\r\nContent-Type: gnss/data\r\n\r\nDATA");
  EXPECT_EQ(plain.status, ResponseStatus::kOk);
  EXPECT_FALSE(plain.chunked);
  EXPECT_EQ(plain.header_length, 44u);

  const auto chunked = gnss_cxx::ntrip::parseResponse(
    "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n");
  EXPECT_EQ(chunked.status, ResponseStatus::kOk);
  EXPECT_TRUE(chunked.chunked);

  EXPECT_EQ(
    gnss_cxx::ntrip::parseResponse(
      "HTTP/1.1 200 OK\r\nContent-Type: gnss/sourcetable\r\n\r\n").status,
    ResponseStatus::kSourcetable);
}

TEST(NtripSourcetable, ListsMountpointNames) {
  const auto names = gnss_cxx::ntrip::sourcetableMountpoints(
    "SOURCETABLE 200 OK\r\nServer: x\r\n\r\n"
    "STR;VRS-RTCM31;VRS-RTCM31;RTCM31;;2;GNSS;NGII;KOR;0;0;1;1;x;none;B;N;0;\r\n"
    "CAS;ignored\r\n"
    "STR;VRS-RTCM32;VRS-RTCM32;RTCM32;;2;GNSS;NGII;KOR;0;0;1;1;x;none;B;N;0;\r\n"
    "ENDSOURCETABLE\r\n");
  ASSERT_EQ(names.size(), 2u);
  EXPECT_EQ(names[0], "VRS-RTCM31");
  EXPECT_EQ(names[1], "VRS-RTCM32");
}

TEST(NtripGga, RewritesTalkerToGpAndKeepsAValidChecksum) {
  const std::string receiver = gnss_cxx::nmea::addChecksum(kReceiverGga);
  const auto normalized = gnss_cxx::ntrip::normalizeGgaForCaster(receiver + "\r\n");
  ASSERT_TRUE(normalized.has_value());
  EXPECT_EQ(normalized->rfind("$GPGGA,120000.00,3717.83551131,N,", 0), 0u);
  EXPECT_TRUE(gnss_cxx::nmea::validateChecksum(*normalized));
  EXPECT_EQ(normalized->find('\r'), std::string::npos);

  const auto parsed = gnss_cxx::nmea::parseSentence(*normalized);
  ASSERT_TRUE(parsed);
  const auto * gga = std::get_if<gnss_cxx::nmea::Gga>(&*parsed.sentence);
  ASSERT_NE(gga, nullptr);
  EXPECT_NEAR(*gga->latitude_deg, 37.2972585218, 1.0e-9);

  std::string corrupted = receiver;
  corrupted[10] = corrupted[10] == '1' ? '2' : '1';
  EXPECT_FALSE(gnss_cxx::ntrip::normalizeGgaForCaster(corrupted).has_value());
  EXPECT_FALSE(
    gnss_cxx::ntrip::normalizeGgaForCaster(
      gnss_cxx::nmea::addChecksum("GNRMC,120000.00,A,3717.8,N,12650.1,E,1.0,90.0,230826,,,A"))
    .has_value());
}

TEST(NtripClient, UploadsGgaThenForwardsExactlyTheCorrectionBytes) {
  const std::string rtcm = std::string("\xd3\x00\x04", 3) + "ABCD" + std::string("\x00\x0d\x0a", 3);
  MockCaster caster("ICY 200 OK\r\n", "\r\n" + rtcm, /*close_after_payload=*/false);
  Harness harness;
  Client client(
    harness.config(caster.port()), harness.sink(), harness.ggaSource(), harness.logger());
  client.start();

  ASSERT_TRUE(waitUntil([&]() {return harness.received().size() >= rtcm.size();}));
  // The blank line after the ICY reply is dropped; payload bytes are untouched,
  // including CR/LF that happen to be part of the binary stream.
  EXPECT_EQ(harness.received(), rtcm);

  const std::string request = caster.request();
  EXPECT_EQ(request.rfind("GET /VRS-RTCM32 HTTP/1.0\r\n", 0), 0u);
  EXPECT_NE(request.find("User-Agent: NTRIP "), std::string::npos);
  EXPECT_NE(request.find("Authorization: Basic dXNlcjpwYXNz\r\n"), std::string::npos);

  ASSERT_TRUE(waitUntil([&]() {return caster.uploadedLines().size() >= 3;}));
  for (const auto & line : caster.uploadedLines()) {
    EXPECT_EQ(line.rfind("$GPGGA,", 0), 0u) << line;
    EXPECT_TRUE(gnss_cxx::nmea::validateChecksum(line)) << line;
  }

  const auto snapshot = client.snapshot();
  EXPECT_EQ(snapshot.state, State::kStreaming);
  EXPECT_EQ(snapshot.bytes_received, rtcm.size());
  EXPECT_GE(snapshot.gga_sent, 3u);
  EXPECT_TRUE(snapshot.last_error.empty());

  client.stop();
  EXPECT_EQ(client.snapshot().state, State::kStopped);
}

TEST(NtripClient, DoesNotConnectUntilThePositionIsKnown) {
  MockCaster caster("ICY 200 OK\r\n", "X", false);
  Harness harness;
  harness.have_position.store(false);
  Client client(
    harness.config(caster.port()), harness.sink(), harness.ggaSource(), harness.logger());
  client.start();

  std::this_thread::sleep_for(std::chrono::milliseconds(300));
  EXPECT_EQ(caster.accepted(), 0);
  EXPECT_EQ(client.snapshot().state, State::kWaitingForGga);

  harness.have_position.store(true);
  EXPECT_TRUE(waitUntil([&]() {return harness.received() == "X";}));
  client.stop();
}

TEST(NtripClient, ReconnectsAfterTheCasterDropsTheLink) {
  MockCaster caster("ICY 200 OK\r\n", "X", /*close_after_payload=*/true);
  Harness harness;
  Client client(
    harness.config(caster.port()), harness.sink(), harness.ggaSource(), harness.logger());
  client.start();
  EXPECT_TRUE(waitUntil([&]() {return caster.accepted() >= 3;}));
  EXPECT_TRUE(waitUntil([&]() {return harness.received().size() >= 3;}));
  client.stop();
  EXPECT_GE(client.snapshot().connections, 3u);
}

TEST(NtripClient, ReportsRejectedCredentials) {
  MockCaster caster("HTTP/1.1 401 Unauthorized\r\n\r\n", "", false);
  Harness harness;
  Client client(
    harness.config(caster.port()), harness.sink(), harness.ggaSource(), harness.logger());
  client.start();
  ASSERT_TRUE(
    waitUntil([&]() {return client.snapshot().last_error.find("authentication") == 0;}));
  EXPECT_TRUE(harness.received().empty());
  client.stop();
  std::lock_guard<std::mutex> lock(harness.mutex);
  ASSERT_FALSE(harness.errors.empty());
  EXPECT_NE(harness.errors.front().find("authentication rejected"), std::string::npos);
  EXPECT_EQ(harness.errors.front().find("pass"), harness.errors.front().find("password"));
}

TEST(NtripClient, ReportsRejectedCredentialsWhenTheCasterOnlySendsAStatusLine) {
  // No blank line after the status line, then the connection is closed.
  MockCaster caster("HTTP/1.0 401 Unauthorized\r\n", "", false);
  Harness harness;
  Client client(
    harness.config(caster.port()), harness.sink(), harness.ggaSource(), harness.logger());
  client.start();
  EXPECT_TRUE(
    waitUntil([&]() {return client.snapshot().last_error.find("authentication") == 0;}));
  client.stop();
}

TEST(NtripClient, ReportsNoDataAgeWhileTheCasterAcceptsButStaysSilent) {
  MockCaster caster("ICY 200 OK\r\n", "", /*close_after_payload=*/false);
  Harness harness;
  Client client(
    harness.config(caster.port()), harness.sink(), harness.ggaSource(), harness.logger());
  client.start();
  ASSERT_TRUE(waitUntil([&]() {return client.snapshot().state == State::kStreaming;}));
  const auto snapshot = client.snapshot();
  // A logged-in session without a single correction byte must be tellable
  // apart from a working one, or RTK silently does nothing while looking fine.
  EXPECT_LT(snapshot.seconds_since_data, 0.0);
  EXPECT_EQ(snapshot.bytes_received, 0u);
  client.stop();
}

TEST(NtripClient, TellsDnsFailureApartFromConnectFailure) {
  Harness harness;
  Config unresolvable = harness.config(2101);
  unresolvable.host = "caster.invalid";  // RFC 6761: never resolves
  Client dns_client(unresolvable, harness.sink(), harness.ggaSource(), harness.logger());
  dns_client.start();
  EXPECT_TRUE(
    waitUntil([&]() {return dns_client.snapshot().last_error.find("cannot resolve") == 0;}, 8.0));
  dns_client.stop();

  Client tcp_client(harness.config(1), harness.sink(), harness.ggaSource(), harness.logger());
  tcp_client.start();
  EXPECT_TRUE(
    waitUntil([&]() {return tcp_client.snapshot().last_error.find("cannot connect") == 0;}));
  tcp_client.stop();
}

TEST(NtripClient, NamesTheAvailableMountpointsWhenTheRequestedOneIsMissing) {
  MockCaster caster(
    "SOURCETABLE 200 OK\r\n\r\nSTR;VRS-RTCM31;a;b\r\nSTR;VRS-RTCM34;a;b\r\nENDSOURCETABLE\r\n",
    "", false);
  Harness harness;
  Client client(
    harness.config(caster.port()), harness.sink(), harness.ggaSource(), harness.logger());
  client.start();
  ASSERT_TRUE(
    waitUntil([&]() {return client.snapshot().last_error.find("VRS-RTCM34") != std::string::npos;}));
  EXPECT_NE(client.snapshot().last_error.find("VRS-RTCM31"), std::string::npos);
  client.stop();
}

TEST(NtripClient, StopsPromptlyWhileTheCasterIsUnreachable) {
  Harness harness;
  Config config = harness.config(1);  // nothing listens on port 1
  Client client(config, harness.sink(), harness.ggaSource(), harness.logger());
  client.start();
  std::this_thread::sleep_for(std::chrono::milliseconds(150));
  const auto begin = std::chrono::steady_clock::now();
  client.stop();
  EXPECT_LT(
    std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count(), 1.0);
}

// Keeps the DNS test bounded on a machine without internet (the vehicle PC):
// without this an unreachable name server costs 5 s x 2 attempts per server.
class ResolverEnvironment : public ::testing::Environment {
 public:
  void SetUp() override {
    ::setenv("RES_OPTIONS", "timeout:1 attempts:1", 1);
  }
};

const ::testing::Environment * const kResolverEnvironment =
  ::testing::AddGlobalTestEnvironment(new ResolverEnvironment);

}  // namespace
