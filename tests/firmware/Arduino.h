#pragma once

// Minimal host shim: the production firmware and protocol run unchanged.
#include <cstddef>
#include <cstdint>
#include <cassert>
#include <deque>
#include <string>
#include <vector>

inline uint32_t testMillis = 0;
inline uint32_t millis() { return testMillis; }
inline void delay(uint32_t ms) { testMillis += ms; }

constexpr int LOW = 0, HIGH = 1, INPUT = 2;
inline int testPinLevels[30] = {};
inline int testPinModes[30] = {};
inline void pinMode(uint8_t pin, int mode) { testPinModes[pin] = mode; }
inline void testSetPin(uint8_t pin, int level) {
  testPinLevels[pin] = level;
}

struct TestSerial {
  std::deque<uint8_t> rx;
  std::vector<uint8_t> tx;
  explicit operator bool() const { return true; }
  uint8_t txPin = 255, rxPin = 255;
  void setTX(uint8_t pin) { txPin = pin; }
  void setRX(uint8_t pin) { rxPin = pin; }
  void setFIFOSize(size_t) {}
  void begin(uint32_t) {}
  int available() const { return rx.size(); }
  int availableForWrite() const { return 4096; }
  int read() {
    if (rx.empty()) return -1;
    const int value = rx.front();
    rx.pop_front();
    return value;
  }
  size_t write(const uint8_t* data, size_t length) {
    tx.insert(tx.end(), data, data + length);
    return length;
  }
};

inline TestSerial Serial, Serial2;
struct TestPico {
  void wdt_begin(uint32_t) {}
  void wdt_reset() {}
  void reboot() {}
};
inline TestPico rp2040;
