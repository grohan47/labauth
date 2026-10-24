#pragma once

#include <stdint.h>

// Top-level operating mode. The Pico stays dumb inside each mode: it reports
// credential IDs; the backend decides what those IDs mean.
enum class Mode : uint8_t {
  Idle,    // Readers off, LED off.
  Poll,    // Normal operation: fingerprint + NFC active.
  Enroll,  // Fingerprint enrollment; NFC paused.
  Check,   // Fingerprint identification for display; NFC paused.
  Verify,  // 1:1 fingerprint verification against a selected template ID.
  Maint,   // Diagnostics and incident response; readers idle, LED off by default.
};

inline const char* modeName(Mode mode) {
  switch (mode) {
    case Mode::Idle: return "IDLE";
    case Mode::Poll: return "POLL";
    case Mode::Enroll: return "ENROLL";
    case Mode::Check: return "CHECK";
    case Mode::Verify: return "VERIFY";
    case Mode::Maint: return "MAINT";
  }
  return "UNKNOWN";
}

enum class ReaderState : uint8_t {
  Off,
  Starting,
  Ready,
  Busy,
  Fault,
  Absent,
};

inline const char* readerStateName(ReaderState state) {
  switch (state) {
    case ReaderState::Off: return "OFF";
    case ReaderState::Starting: return "STARTING";
    case ReaderState::Ready: return "READY";
    case ReaderState::Busy: return "BUSY";
    case ReaderState::Fault: return "FAULT";
    case ReaderState::Absent: return "ABSENT";
  }
  return "UNKNOWN";
}
