// ---------------------------------------------------------------------------
// LabAuth Pico firmware
//
// One MCU, two readers:
//   - Waveshare UART Fingerprint Sensor (F) on UART1, active now.
//   - PN532 on I2C0, reserved and stubbed until the hardware arrives.
//
// The Pico is a bridge, not the application. It reports template IDs and NFC
// UIDs. It does not know whether an event is a sign-in or sign-out; the
// backend resolves the credential and updates the database/screens.
//
// Everything is non-blocking. loop() services the host link, the fingerprint
// state machine and the NFC state machine every pass.
// ---------------------------------------------------------------------------

#include <Arduino.h>
#include <stdlib.h>
#include <string.h>

#include "config.h"
#include "fingerprint.h"
#include "nfc.h"
#include "protocol.h"
#include "types.h"

Fingerprint fp;
Nfc nfc;

Mode mode = Mode::Idle;
uint16_t verifyId = 0;
bool oneShotScan = false;
// Backend/UI overrides. Mode changes never reset these; reboot defaults to ON.
bool fpEnabled = true;
bool nfcEnabled = true;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

bool parseId(const char* text, uint16_t& id) {
  if (text == nullptr || *text == '\0') {
    return false;
  }
  char* end = nullptr;
  const unsigned long value = strtoul(text, &end, 10);
  if (end == text || *end != '\0') {
    return false;
  }
  if (value < FP_FIRST_ID || value > FP_LAST_ID) {
    return false;
  }
  id = (uint16_t)value;
  return true;
}

bool diagnosticsAllowed() {
  return mode == Mode::Maint || mode == Mode::Idle;
}

const char* fingerprintStatusName() {
  // Waiting for or capturing a finger is normal availability in polling mode.
  // Keep the driver's raw state/busy checks for command scheduling.
  return mode == Mode::Poll && fpEnabled && fp.pollingReady()
             ? "READY" : fp.stateName();
}

void sendStatus() {
  hostSendf(
      "STATUS mode=%s fp=%s nfc=%s led=%s verify=%u up=%lu fw=%d dropped=%lu polling=%s fp_enabled=%s nfc_enabled=%s enroll=%u learning=%s cleanup=%s fp_state=%s",
      modeName(mode), fingerprintStatusName(), nfc.stateName(),
      fp.ledWanted() ? "ON" : "OFF", verifyId, (unsigned long)millis(),
      LABAUTH_FW_VERSION, (unsigned long)hostDroppedLines(),
      mode == Mode::Poll ? "ON" : "OFF", fpEnabled ? "ON" : "OFF",
      nfcEnabled ? "ON" : "OFF", fp.enrollmentId(),
      fp.learning() ? "ON" : "OFF", fp.cleanupPending() ? "ON" : "OFF",
      fp.stateName());
}

void sendReady() {
  hostSendf("READY fw=%d mode=%s fp=%s nfc=%s fp_enabled=%s nfc_enabled=%s",
            LABAUTH_FW_VERSION, modeName(mode), fingerprintStatusName(), nfc.stateName(),
            fpEnabled ? "ON" : "OFF", nfcEnabled ? "ON" : "OFF");
}

void sendHelp() {
  hostSendf("HELP MODE IDLE|POLL|ENROLL|CHECK|VERIFY|MAINT");
  hostSendf("HELP ENROLL                 enroll one finger (MODE ENROLL)");
  hostSendf("HELP ENROLL FINISH          finish uncapped guided Auto Learn");
  hostSendf("HELP VERIFY <id>            arm 1:1 checks (MODE VERIFY)");
  hostSendf("HELP CANCEL                 abort the current operation");
  hostSendf("HELP STATUS                 mode and reader states");
  hostSendf("HELP FP SCAN|COUNT|LIST|HEALTH|PARAMS|PING");
  hostSendf("HELP FP EXISTS <id>         is this template slot registered?");
  hostSendf("HELP FP DELETE <id>         delete a template (MAINT/IDLE)");
  hostSendf("HELP FP LED ON|OFF");
  hostSendf("HELP FP ENABLE|DISABLE|STATUS  backend reader switch (any mode)");
  hostSendf("HELP NFC ENABLE|DISABLE       backend reader switch (any mode)");
  hostSendf("HELP NFC STATUS|READ|ON|OFF");
  hostSendf("HELP LED ON|OFF             same as FP LED");
  hostSendf("HELP PING | REBOOT | HELP");
}

void configureFingerprintMode() {
  if (!fpEnabled) {
    return;
  }
  switch (mode) {
    case Mode::Poll:
    case Mode::Check:
      fp.setModeActive(true);
      fp.setStartGate(true);
      fp.setAutoScan(true);
      break;
    case Mode::Enroll:
      fp.setModeActive(true);  // Wait for a fresh ENROLL command.
      break;
    case Mode::Verify:
      fp.setModeActive(true);
      fp.setStartGate(true);
      fp.setAutoVerify(verifyId);
      break;
    case Mode::Maint:
    case Mode::Idle:
      break;
  }
}

void setFingerprintEnabled(bool enabled) {
  if (fpEnabled == enabled) {
    return;  // Repeated ENABLE must not cancel/restart an operation.
  }
  fpEnabled = enabled;
  if (enabled) {
    configureFingerprintMode();
  } else {
    fp.cancel();  // DISABLE may explicitly abort enrollment in any mode.
    fp.setModeActive(false);  // Clears auto scanning and requests LED OFF.
    oneShotScan = false;
  }
}

void setNfcEnabled(bool enabled) {
  if (nfcEnabled == enabled) {
    return;
  }
  nfcEnabled = enabled;
  nfc.setEnabled(false);
  nfc.cancel();
  if (enabled && mode == Mode::Poll) {
    nfc.setEnabled(true);
  }
}

bool setMode(Mode next, bool announce) {
  // Retrying MODE ENROLL must not abort an enrollment already in progress.
  if (mode == Mode::Enroll && next == Mode::Enroll) {
    if (announce) {
      hostOk("MODE ENROLL");
      sendStatus();
    }
    return true;
  }
  // Enrollment owns both readers until it finishes or is explicitly cancelled.
  if (mode == Mode::Enroll && fp.enrolling()) {
    hostErr("MODE enrollment-active");
    return false;
  }

  // Abort whatever the fingerprint reader is doing before changing ownership.
  fp.cancel();
  fp.setAutoScan(false);
  fp.setAutoVerify(0);
  fp.setStartGate(false);
  fp.setModeActive(false);
  nfc.setEnabled(false);
  nfc.cancel();  // Also discard any one-shot read from the previous mode.

  mode = next;
  verifyId = 0;
  oneShotScan = false;

  configureFingerprintMode();
  if (mode == Mode::Poll && nfcEnabled) {
    nfc.setEnabled(true);
  }

  if (announce) {
    hostOk("MODE %s", modeName(mode));
    sendStatus();
  }
  return true;
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

void handleMode(int argc, char** argv) {
  if (argc < 2) {
    hostErr("ARG mode");
    return;
  }

  if (!strcmp(argv[1], "IDLE")) {
    setMode(Mode::Idle, true);
  } else if (!strcmp(argv[1], "POLL")) {
    setMode(Mode::Poll, true);
  } else if (!strcmp(argv[1], "ENROLL")) {
    setMode(Mode::Enroll, true);
  } else if (!strcmp(argv[1], "CHECK")) {
    setMode(Mode::Check, true);
  } else if (!strcmp(argv[1], "MAINT")) {
    setMode(Mode::Maint, true);
  } else if (!strcmp(argv[1], "VERIFY")) {
    if (!setMode(Mode::Verify, true)) {
      return;
    }
    // Optional convenience: "MODE VERIFY 41".
    if (argc >= 3) {
      uint16_t id = 0;
      if (parseId(argv[2], id)) {
        verifyId = id;
        if (fpEnabled) {
          fp.setAutoVerify(id);
        }
        hostOk("VERIFY id=%u", id);
      } else {
        hostErr("ARG id");
      }
    }
  } else {
    hostErr("ARG mode");
  }
}

void handleFp(int argc, char** argv) {
  if (argc < 2) {
    hostErr("ARG fp");
    return;
  }

  if (!strcmp(argv[1], "ENABLE") || !strcmp(argv[1], "DISABLE")) {
    if (argc != 2) {
      hostErr("ARG fp-switch");
      return;
    }
    setFingerprintEnabled(!strcmp(argv[1], "ENABLE"));
    hostOk("FP %s", argv[1]);
    sendStatus();
    return;
  }

  if (!strcmp(argv[1], "STATUS")) {
    hostSendf("FP state=%s enabled=%s led=%s enroll=%u learning=%s cleanup=%s",
              fingerprintStatusName(), fpEnabled ? "ON" : "OFF",
              fp.ledWanted() ? "ON" : "OFF", fp.enrollmentId(),
              fp.learning() ? "ON" : "OFF", fp.cleanupPending() ? "ON" : "OFF");
    return;
  }

  if (!fpEnabled) {
    hostErr("FP DISABLED");
    return;
  }

  if (!strcmp(argv[1], "PING")) {
    if (fp.startPing()) {
      hostOk("FP PING");
    } else {
      hostErr("FP BUSY");
    }
    return;
  }

  if (!strcmp(argv[1], "LED")) {
    if (argc < 3) {
      hostErr("ARG led");
      return;
    }
    const bool on = !strcmp(argv[2], "ON");
    if (!on && !strcmp(argv[2], "OFF")) {
      if (mode != Mode::Maint && mode != Mode::Idle) {
        hostErr("MODE led-forced");
        return;
      }
    } else if (on) {
      // allowed in any mode
    } else {
      hostErr("ARG led");
      return;
    }

    if (fp.setLedCommand(on, millis())) {
      hostOk("FP LED %s", on ? "ON" : "OFF");
    } else {
      hostErr("FP BUSY");
    }
    return;
  }

  if (!diagnosticsAllowed()) {
    hostErr("MODE diagnostics-only");
    return;
  }

  if (fp.busy()) {
    hostErr("FP BUSY");
    return;
  }

  if (!strcmp(argv[1], "SCAN")) {
    fp.setStartGate(false);  // Explicit one-shot: report what is on the sensor.
    fp.setModeActive(true);
    if (fp.startScan()) {
      oneShotScan = true;
      hostOk("FP SCAN");
    } else {
      fp.setModeActive(false);
      hostErr("FP NOT_READY");
    }
    return;
  }

  if (!strcmp(argv[1], "COUNT")) {
    if (fp.startCount()) {
      hostOk("FP COUNT");
    } else {
      hostErr("FP NOT_READY");
    }
    return;
  }

  if (!strcmp(argv[1], "LIST")) {
    if (fp.startList()) {
      hostOk("FP LIST");
    } else {
      hostErr("FP NOT_READY");
    }
    return;
  }

  if (!strcmp(argv[1], "HEALTH")) {
    if (fp.startHealth()) {
      hostOk("FP HEALTH");
    } else {
      hostErr("FP NOT_READY");
    }
    return;
  }

  if (!strcmp(argv[1], "PARAMS")) {
    if (fp.startParams()) {
      hostOk("FP PARAMS");
    } else {
      hostErr("FP NOT_READY");
    }
    return;
  }

  if (!strcmp(argv[1], "DELETE")) {
    uint16_t id = 0;
    if (argc < 3 || !parseId(argv[2], id)) {
      hostErr("ARG id");
      return;
    }
    if (fp.startDelete(id)) {
      hostOk("FP DELETE id=%u", id);
    } else {
      hostErr("FP NOT_READY");
    }
    return;
  }

  if (!strcmp(argv[1], "EXISTS")) {
    uint16_t id = 0;
    if (argc < 3 || !parseId(argv[2], id)) {
      hostErr("ARG id");
      return;
    }
    if (fp.startExists(id)) {
      hostOk("FP EXISTS id=%u", id);
    } else {
      hostErr("FP NOT_READY");
    }
    return;
  }

  hostErr("FP unknown");
}

void handleNfc(int argc, char** argv) {
  if (argc < 2) {
    hostErr("ARG nfc");
    return;
  }

  if (!strcmp(argv[1], "ENABLE") || !strcmp(argv[1], "DISABLE")) {
    if (argc != 2) {
      hostErr("ARG nfc-switch");
      return;
    }
    setNfcEnabled(!strcmp(argv[1], "ENABLE"));
    hostOk("NFC %s", argv[1]);
    sendStatus();
    return;
  }

  if (!strcmp(argv[1], "STATUS")) {
    hostSendf("NFC state=%s enabled=%s", nfc.stateName(),
              nfcEnabled ? "ON" : "OFF");
    return;
  }

  if (!nfcEnabled) {
    hostErr("NFC DISABLED");
    return;
  }

  if (!diagnosticsAllowed()) {
    hostErr("MODE diagnostics-only");
    return;
  }

  if (!strcmp(argv[1], "READ")) {
    if (nfc.readOnce()) {
      hostOk("NFC READ");
    }
    return;
  }

  if (!strcmp(argv[1], "ON")) {
    nfc.setEnabled(true);
    if (nfc.state() == ReaderState::Absent) {
      hostErr("NFC ABSENT");
    } else {
      hostOk("NFC ON");
    }
    return;
  }

  if (!strcmp(argv[1], "OFF")) {
    nfc.setEnabled(false);
    hostOk("NFC OFF");
    return;
  }

  hostErr("NFC unknown");
}

void onCommand(char* line) {
  char* argv[5] = {};
  int argc = 0;
  char* save = nullptr;
  for (char* token = strtok_r(line, " ", &save);
       token != nullptr && argc < 5;
       token = strtok_r(nullptr, " ", &save)) {
    argv[argc++] = token;
  }

  if (argc == 0) {
    return;
  }

  if (!strcmp(argv[0], "HELP")) {
    sendHelp();
    return;
  }

  if (!strcmp(argv[0], "PING")) {
    hostOk("PONG up=%lu", (unsigned long)millis());
    return;
  }

  if (!strcmp(argv[0], "STATUS")) {
    sendStatus();
    return;
  }

  if (!strcmp(argv[0], "MODE")) {
    handleMode(argc, argv);
    return;
  }

  if (!strcmp(argv[0], "ENROLL")) {
    if (!fpEnabled) {
      hostErr("FP DISABLED");
      return;
    }
    if (mode != Mode::Enroll) {
      hostErr("MODE not-enroll");
      return;
    }
    if (argc == 2 && !strcmp(argv[1], "FINISH")) {
      if (fp.finishEnroll()) {
        hostOk("ENROLL FINISH");
      } else {
        hostErr("FP NOT_LEARNING");
      }
      return;
    }
    if (argc != 1) {
      hostErr("ARG enroll");
      return;
    }
    if (!fp.startEnroll()) {
      hostErr("FP BUSY");
      return;
    }
    hostOk("ENROLL");
    return;
  }

  if (!strcmp(argv[0], "VERIFY")) {
    if (!fpEnabled) {
      hostErr("FP DISABLED");
      return;
    }
    if (mode != Mode::Verify) {
      hostErr("MODE not-verify");
      return;
    }
    uint16_t id = 0;
    if (argc < 2 || !parseId(argv[1], id)) {
      hostErr("ARG id");
      return;
    }
    // Takes effect on the next verify cycle. Do not cancel here: that would
    // drop the start-gate that prevents a finger left on the sensor from
    // immediately verifying against the newly armed ID.
    verifyId = id;
    fp.setAutoVerify(id);
    hostOk("VERIFY id=%u", id);
    return;
  }

  if (!strcmp(argv[0], "CANCEL")) {
    fp.cancel();
    nfc.cancel();
    if (oneShotScan) {
      oneShotScan = false;
      fp.setModeActive(false);
    }
    hostOk("CANCEL");
    return;
  }

  if (!strcmp(argv[0], "FP")) {
    handleFp(argc, argv);
    return;
  }

  if (!strcmp(argv[0], "NFC")) {
    handleNfc(argc, argv);
    return;
  }

  if (!strcmp(argv[0], "LED")) {
    if (argc < 2) {
      hostErr("ARG led");
      return;
    }
    const bool on = !strcmp(argv[1], "ON");
    if (on && !fpEnabled) {
      hostErr("FP DISABLED");
      return;
    }
    if (!on && !strcmp(argv[1], "OFF")) {
      if (fpEnabled && mode != Mode::Maint && mode != Mode::Idle) {
        hostErr("MODE led-forced");
        return;
      }
    } else if (on) {
      // allowed in any mode
    } else {
      hostErr("ARG led");
      return;
    }

    if (fp.setLedCommand(on, millis())) {
      hostOk("LED %s", on ? "ON" : "OFF");
    } else {
      hostErr("FP BUSY");
    }
    return;
  }

  if (!strcmp(argv[0], "REBOOT")) {
    hostOk("REBOOT");
    hostFlush();
    delay(50);
    rp2040.reboot();
    return;
  }

  hostErr("CMD unknown");
}

// ---------------------------------------------------------------------------
// Arduino entry points
// ---------------------------------------------------------------------------

void setup() {
  hostBegin(onCommand);
  fp.begin();
  nfc.begin();
  setMode(Mode::Idle, false);

  hostSendf("LABAUTH PICO fw=%d", LABAUTH_FW_VERSION);
  hostSendf("FP UART1 TX=GP%d RX=GP%d baud=%lu", FP_TX_PIN, FP_RX_PIN,
            (unsigned long)FP_BAUD);
  hostSendf("FP presence=UART interval=%lu confirmations=%u IRQ=GP%d unused",
            (unsigned long)FP_PRESENCE_INTERVAL_MS,
            (unsigned)FP_PRESENCE_CONFIRMATIONS, FP_IRQ_PIN);
#if ENABLE_PN532
  hostSendf("NFC I2C0 SDA=GP%d SCL=GP%d addr=0x%02X", NFC_SDA_PIN,
            NFC_SCL_PIN, (unsigned)NFC_I2C_ADDRESS);
#else
  hostSendf("NFC disabled (ENABLE_PN532=0)");
#endif
  hostSendf("Type HELP for commands.");
  sendReady();

  rp2040.wdt_begin(WDT_TIMEOUT_MS);
}

void loop() {
  rp2040.wdt_reset();
  const uint32_t now = millis();

  hostPoll();
  if (hostTakeReconnected()) {
    sendReady();
  }

  fp.tick(now);
  if (nfcEnabled) {
    nfc.tick(now);
  }

  // A one-shot diagnostic scan borrows the LED and active state only for the
  // duration of the scan.
  if (oneShotScan && !fp.busy()) {
    oneShotScan = false;
    fp.setModeActive(false);
  }

  hostFlush();
}
