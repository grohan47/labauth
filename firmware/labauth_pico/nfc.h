#pragma once

#include <Arduino.h>

#include "types.h"

// ---------------------------------------------------------------------------
// PN532 NFC reader (future)
//
// The first implementation only reports ABSENT. The interface is deliberately
// the same shape as Fingerprint so the real PN532 state machine can drop in
// without touching the top-level modes or the host protocol.
//
// Planned I2C state machine (inside tick()):
//   Starting -> FirmwareCheck -> Configure -> Ready
//   Ready + enabled -> Poll -> UID -> Release -> Cooldown -> Poll
//   any transport error -> Fault -> retry
//
// Each tick() may perform at most one short I2C transfer. Do not call a
// blocking "read a whole response" helper, because that would starve the
// fingerprint reader and the host link.
// ---------------------------------------------------------------------------

class Nfc {
 public:
  void begin();
  void tick(uint32_t now);
  void setEnabled(bool enabled);
  bool readOnce();
  void cancel();
  // The future driver must discard pending results on cancel. The top-level
  // DISABLE switch also suspends tick() until re-enabled.

  bool busy() const;
  ReaderState state() const;
  const char* stateName() const { return readerStateName(state()); }

 private:
  ReaderState state_ = ReaderState::Off;
  bool enabled_ = false;
  bool oneShot_ = false;
  bool absentReported_ = false;
  uint32_t nextActionAt_ = 0;
};
