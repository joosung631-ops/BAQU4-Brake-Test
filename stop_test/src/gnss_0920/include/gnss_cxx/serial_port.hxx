#pragma once

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <string>

namespace gnss_cxx {

class SerialPort {
 public:
  SerialPort() = default;
  SerialPort(const std::string & device, int baudrate);
  ~SerialPort();

  SerialPort(const SerialPort &) = delete;
  SerialPort & operator=(const SerialPort &) = delete;
  SerialPort(SerialPort && other) noexcept;
  SerialPort & operator=(SerialPort && other) noexcept;

  void open(const std::string & device, int baudrate);
  void close() noexcept;
  [[nodiscard]] bool isOpen() const noexcept;
  [[nodiscard]] bool waitReadable(std::chrono::milliseconds timeout) const;
  std::size_t readSome(std::uint8_t * destination, std::size_t capacity);
  void writeAll(const void * data, std::size_t size);
  void writeLine(const std::string & line);

 private:
  int fd_{-1};
};

}  // namespace gnss_cxx
