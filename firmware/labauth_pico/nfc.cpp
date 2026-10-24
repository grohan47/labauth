#include "nfc.h"

#include "config.h"
#include "protocol.h"

void Nfc::begin() {
#if ENABLE_PN532
  // Future:
  //   Wire.setSDA(NFC_SDA_PIN);
  //   Wire.setSCL(NFC_SCL_PIN);
  //   Wire.setClock(NFC_I2C_HZ);
  //   Wire.setTimeout(NFC_I2C_TIMEOUT_MS, true);
  //   Wire.begin();
  // Then enter FirmwareCheck, not Ready: an ACK is not proof of a PN532.
  // Until that code exists, report ABSENT rather than pretending to start.
  state_ = ReaderState::Absent;
  nextActionAt_ = millis();
#else
  state_ = ReaderState::Absent;
#endif
}

void Nfc::tick(uint32_t now) {
#if ENABLE_PN532
  // Real implementation goes here. Keep every step non-blocking.
  //
  // The PN532 I2C protocol requires reading a status byte before the response
  // payload. A practical shape is:
  //
  //   Step::CheckFirmware: send GetFirmwareVersion, await reply
  //   Step::Configure:     SAMConfiguration, RFConfiguration
  //   Step::Ready:         if enabled or oneShot, send InListPassiveTarget
  //   Step::WaitCard:      poll the status byte / response in small steps
  //   Step::WaitRelease:   require NFC_RELEASE_MS without the same UID
  //   Step::Cooldown:      short after a UID, longer after an error
  //
  // Emit:
  //   hostEvent("NFC READY version=%u.%u", major, minor);
  //   hostEvent("NFC UID uid=04A10B2C3D4E5F");
  //   hostErr("NFC ...");
  (void)now;
#else
  (void)now;
  state_ = ReaderState::Absent;
  enabled_ = false;
  oneShot_ = false;
#endif
}

void Nfc::setEnabled(bool enabled) {
#if ENABLE_PN532
  enabled_ = enabled;
  if (enabled) {
    oneShot_ = false;
    nextActionAt_ = millis();
  }
#else
  (void)enabled;
  enabled_ = false;
  state_ = ReaderState::Absent;
  if (enabled && !absentReported_) {
    absentReported_ = true;
    hostEvent("NFC ABSENT");
  }
  if (!enabled) {
    absentReported_ = false;
  }
#endif
}

bool Nfc::readOnce() {
#if ENABLE_PN532
  if (state_ != ReaderState::Ready) {
    hostErr("NFC NOT_READY");
    return false;
  }
  oneShot_ = true;
  nextActionAt_ = millis();
  return true;
#else
  hostErr("NFC ABSENT");
  return false;
#endif
}

void Nfc::cancel() {
  oneShot_ = false;
}

bool Nfc::busy() const {
#if ENABLE_PN532
  return state_ == ReaderState::Busy || oneShot_;
#else
  return false;
#endif
}

ReaderState Nfc::state() const {
  return state_;
}
