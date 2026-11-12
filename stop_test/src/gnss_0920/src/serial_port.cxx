#include "gnss_cxx/serial_port.hxx"

#include <cerrno>
#include <stdexcept>
#include <system_error>
#include <utility>

#include <fcntl.h>
#include <poll.h>
#include <termios.h>
#include <unistd.h>

namespace gnss_cxx {
namespace {

speed_t baudConstant(int baudrate) {
  switch (baudrate) {
    case 9600: return B9600;
    case 19200: return B19200;
    case 38400: return B38400;
    case 57600: return B57600;
    case 115200: return B115200;
#ifdef B230400
    case 230400: return B230400;
#endif
#ifdef B460800
    case 460800: return B460800;
#endif
#ifdef B921600
    case 921600: return B921600;
#endif
    default: throw std::invalid_argument("unsupported serial baudrate");
  }
}

void throwSystemError(const char * operation) {
  throw std::system_error(errno, std::generic_category(), operation);
}

}  // namespace

SerialPort::SerialPort(const std::string & device, int baudrate) {
  open(device, baudrate);
}

SerialPort::~SerialPort() {
  close();
}

SerialPort::SerialPort(SerialPort && other) noexcept
: fd_(std::exchange(other.fd_, -1)) {}

SerialPort & SerialPort::operator=(SerialPort && other) noexcept {
  if (this != &other) {
    close();
    fd_ = std::exchange(other.fd_, -1);
  }
  return *this;
}

void SerialPort::open(const std::string & device, int baudrate) {
  close();
  const speed_t baud = baudConstant(baudrate);
  const int descriptor = ::open(device.c_str(), O_RDWR | O_NOCTTY | O_CLOEXEC);
  if (descriptor < 0) {
    throwSystemError("open serial device");
  }

  termios settings{};
  if (::tcgetattr(descriptor, &settings) != 0) {
    const int saved_errno = errno;
    ::close(descriptor);
    errno = saved_errno;
    throwSystemError("tcgetattr");
  }

  ::cfmakeraw(&settings);
  settings.c_cflag |= static_cast<tcflag_t>(CLOCAL | CREAD);
#ifdef CRTSCTS
  settings.c_cflag &= static_cast<tcflag_t>(~CRTSCTS);
#endif
  settings.c_cc[VMIN] = 1;
  settings.c_cc[VTIME] = 0;
  if (::cfsetispeed(&settings, baud) != 0 || ::cfsetospeed(&settings, baud) != 0 ||
      ::tcsetattr(descriptor, TCSANOW, &settings) != 0) {
    const int saved_errno = errno;
    ::close(descriptor);
    errno = saved_errno;
    throwSystemError("configure serial device");
  }
  if (::tcflush(descriptor, TCIFLUSH) != 0) {
    const int saved_errno = errno;
    ::close(descriptor);
    errno = saved_errno;
    throwSystemError("flush serial device");
  }
  fd_ = descriptor;
}

void SerialPort::close() noexcept {
  if (fd_ >= 0) {
    ::close(fd_);
    fd_ = -1;
  }
}

bool SerialPort::isOpen() const noexcept {
  return fd_ >= 0;
}

bool SerialPort::waitReadable(std::chrono::milliseconds timeout) const {
  if (!isOpen()) {
    throw std::logic_error("serial device is not open");
  }
  pollfd descriptor{};
  descriptor.fd = fd_;
  descriptor.events = POLLIN;
  int result;
  do {
    result = ::poll(&descriptor, 1, static_cast<int>(timeout.count()));
  } while (result < 0 && errno == EINTR);
  if (result < 0) {
    throwSystemError("poll serial device");
  }
  if (result == 0) {
    return false;
  }
  if ((descriptor.revents & (POLLERR | POLLHUP | POLLNVAL)) != 0) {
    throw std::runtime_error("serial device disconnected");
  }
  return (descriptor.revents & POLLIN) != 0;
}

std::size_t SerialPort::readSome(std::uint8_t * destination, std::size_t capacity) {
  if (!isOpen()) {
    throw std::logic_error("serial device is not open");
  }
  if (destination == nullptr || capacity == 0) {
    throw std::invalid_argument("invalid serial read buffer");
  }
  ssize_t result;
  do {
    result = ::read(fd_, destination, capacity);
  } while (result < 0 && errno == EINTR);
  if (result < 0) {
    throwSystemError("read serial device");
  }
  if (result == 0) {
    throw std::runtime_error("serial device reached end of stream");
  }
  return static_cast<std::size_t>(result);
}

void SerialPort::writeAll(const void * data, std::size_t size) {
  if (!isOpen()) {
    throw std::logic_error("serial device is not open");
  }
  const auto * bytes = static_cast<const std::uint8_t *>(data);
  std::size_t written = 0;
  while (written < size) {
    ssize_t result;
    do {
      result = ::write(fd_, bytes + written, size - written);
    } while (result < 0 && errno == EINTR);
    if (result < 0) {
      throwSystemError("write serial device");
    }
    if (result == 0) {
      throw std::runtime_error("serial write made no progress");
    }
    written += static_cast<std::size_t>(result);
  }
  if (::tcdrain(fd_) != 0) {
    throwSystemError("drain serial device");
  }
}

void SerialPort::writeLine(const std::string & line) {
  writeAll(line.data(), line.size());
  constexpr char terminator[] = "\r\n";
  writeAll(terminator, sizeof(terminator) - 1);
}

}  // namespace gnss_cxx
