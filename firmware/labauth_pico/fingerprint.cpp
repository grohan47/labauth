#include "fingerprint.h"

#include <string.h>

#include "protocol.h"

namespace {

// Waveshare Sensor (F) command codes, from the official command manual.
constexpr uint16_t CMD_PING = 0x0001;
constexpr uint16_t CMD_SET_PARAM = 0x0002;
constexpr uint16_t CMD_GET_PARAM = 0x0003;
constexpr uint16_t CMD_GET_IMAGE = 0x0020;
constexpr uint16_t CMD_FINGER_DETECT = 0x0021;
constexpr uint16_t CMD_LED = 0x0024;
constexpr uint16_t CMD_STORE = 0x0040;
constexpr uint16_t CMD_DELETE_RANGE = 0x0044;
constexpr uint16_t CMD_GET_EMPTY_ID = 0x0045;
constexpr uint16_t CMD_GET_STATUS = 0x0046;
constexpr uint16_t CMD_GET_BROKEN_ID = 0x0047;
constexpr uint16_t CMD_GET_COUNT = 0x0048;
constexpr uint16_t CMD_GENERATE = 0x0060;
constexpr uint16_t CMD_MERGE = 0x0061;
constexpr uint16_t CMD_SEARCH = 0x0063;
constexpr uint16_t CMD_VERIFY = 0x0064;

constexpr uint8_t RESPONSE_BYTES = 26;

void put16(uint8_t* p, uint16_t value) {
  p[0] = (uint8_t)(value & 0xFF);
  p[1] = (uint8_t)(value >> 8);
}

uint16_t get16(const uint8_t* p) {
  return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}

uint16_t checksum(const uint8_t* packet) {
  uint16_t sum = 0;
  for (uint8_t i = 0; i < 24; ++i) {
    sum = (uint16_t)(sum + packet[i]);
  }
  return sum;
}

bool reached(uint32_t now, uint32_t deadline) {
  return (int32_t)(now - deadline) >= 0;
}

}  // namespace

void Fingerprint::begin() {
  pinMode(FP_IRQ_PIN, INPUT);  // Safe to leave wired; never used for decisions.

  Serial2.setTX(FP_TX_PIN);
  Serial2.setRX(FP_RX_PIN);
  Serial2.setFIFOSize(FP_UART_RX_BUFFER_BYTES);
  Serial2.begin(FP_BAUD);

  step_ = Step::Starting;
  bootAt_ = millis();
  linkReady_ = false;

  // The sensor may still be powered from before a Pico reboot. Send a
  // definite OFF after the link comes up, then let the mode decide.
  ledWanted_ = false;
  ledOn_ = false;
  ledDirty_ = true;
  ledRefreshAt_ = 0;
}

void Fingerprint::tick(uint32_t now) {
  if (step_ == Step::Off) {
    return;
  }

  if (step_ == Step::Starting) {
    if (reached(now, bootAt_ + FP_BOOT_DELAY_MS)) {
      startPing(now);
    }
    return;
  }

  if (step_ == Step::Fault) {
    if (reached(now, retryAt_)) {
      startPing(now);
    }
    return;
  }

  if (waiting_) {
    const Reply reply = pollReply(now);
    if (reply == Reply::Ok) {
      onReply(now);
    } else if (reply == Reply::Timeout || reply == Reply::BadFrame) {
      onTransportError(reply, now);
    }
    return;
  }

  if (maintainLed(now)) {
    return;
  }

  if (enrollFinish_) {
    completeEnrollment(now);
    return;
  }
  if (enrollCleanup_ && step_ == Step::Ready) {
    if (reached(now, enrollCleanupAt_)) {
      uint8_t data[4];
      put16(data, enrollProvisionalId_);
      put16(data + 2, enrollProvisionalId_);
      step_ = Step::EnrollCleanup;
      sendCommand(CMD_DELETE_RANGE, data, sizeof(data), now);
    }
    return;
  }

  switch (step_) {
    case Step::Ready:
      ensureAuto(now);
      break;

    case Step::WaitStart:
      // Entering POLL/CHECK/VERIFY while a finger is still on the sensor must
      // not consume it. Never bypass this gate just because time has passed.
      pollPresence(now);
      break;

    case Step::WaitFinger:
      if (!autoScan_ && autoVerifyId_ == 0 && reached(now, deadline_)) {
        // Continuous modes keep polling. Only a one-shot has a timeout.
        if (verifyRequest_) {
          hostEvent("FP VERIFY id=%u result=NOMATCH", verifyId_);
        } else {
          hostEvent("FP NOMATCH");
        }
        startCooldown(now, Outcome::NoMatch);
      } else {
        pollPresence(now);
      }
      break;

    case Step::WaitRelease:
      // A held finger cannot re-arm scanning, even after a long hold.
      pollPresence(now);
      break;

    case Step::Cooldown:
      if (reached(now, deadline_)) {
        step_ = Step::Ready;
        ensureAuto(now);
      }
      break;

    case Step::EnrollWaitRemove:
      if (!enrollLearning_ && reached(now, deadline_)) {
        sensorError("REMOVE_TIMEOUT", 0, now, false);
      } else {
        pollPresence(now);
      }
      break;

    case Step::EnrollWaitFinger:
      if (!enrollLearning_ && reached(now, deadline_)) {
        sensorError("FINGER_TIMEOUT", 0, now, false);
      } else {
        pollPresence(now);
      }
      break;

    default:
      // Every other step is waiting for a reply.
      break;
  }
}

// ---------------------------------------------------------------------------
// Mode / auto behaviour
// ---------------------------------------------------------------------------

void Fingerprint::setModeActive(bool active) {
  active_ = active;
  // The operation arms the LED when capture is actually available. Merely
  // entering ENROLL (before ENROLL is sent) or VERIFY (before an ID) is not armed.
  requestLed(false);
  if (!active) {
    autoScan_ = false;
    autoVerifyId_ = 0;
    gateOnStart_ = false;
    enrollPending_ = false;
  }
}

void Fingerprint::setStartGate(bool require) {
  gateOnStart_ = require;
}

void Fingerprint::setAutoScan(bool enabled) {
  autoScan_ = enabled;
  if (enabled) {
    autoVerifyId_ = 0;
  }
}

void Fingerprint::setAutoVerify(uint16_t id) {
  autoVerifyId_ = id;
  if (id != 0) {
    autoScan_ = false;
  }
}

void Fingerprint::cancel() {
  const bool wasEnroll = enrolling();
  abandonEnrollment();
  enrollPending_ = false;
  requestLed(false);
  if (step_ == Step::Off || step_ == Step::Starting) {
    return;
  }
  // A maintenance LED refresh is harmless; let it finish instead of turning a
  // no-op mode change into a visible cancel/fault.
  if (step_ == Step::Led && ledNext_ == Step::Ready) {
    if (wasEnroll) {
      hostEvent("FP ENROLL_ABORTED");
    }
    return;
  }

  const bool wasBusy = busy();
  if (!wasBusy && !waiting_) {
    return;
  }

  if (wasEnroll) {
    hostEvent("FP ENROLL_ABORTED");
  } else if (wasBusy) {
    hostEvent("FP CANCELLED");
  }

  enrollId_ = 0;
  enrollSample_ = 0;
  enrollRetries_ = 0;
  listId_ = 0;
  paramType_ = 0;
  ledNext_ = Step::Ready;
  ledResume_ = false;

  if (waiting_) {
    // The sensor is strictly one command at a time. Abandoning a command and
    // immediately sending another can make it ignore the new command or answer
    // the old one. Force a PING resync instead of guessing.
    waiting_ = false;
    replyCount_ = 0;
    while (Serial2.available() > 0) {
      Serial2.read();
    }
    linkReady_ = false;
    ledOn_ = false;
    ledDirty_ = true;
    ledRefreshAt_ = 0;
    step_ = Step::Fault;
    retryAt_ = millis() + FP_LINK_RETRY_MS;
    return;
  }

  // No command is in flight, so it is safe to stop immediately.
  step_ = linkReady_ ? Step::Ready : Step::Fault;
  if (step_ == Step::Fault) {
    retryAt_ = millis() + FP_LINK_RETRY_MS;
  }
}

bool Fingerprint::startScan() {
  if (!linkReady_ || step_ != Step::Ready) {
    return false;
  }
  startScanNow(millis());
  return true;
}

bool Fingerprint::startEnroll() {
  if (!linkReady_ || enrolling()) {
    return false;
  }
  if (step_ == Step::Ready) {
    startEnrollNow(millis());
    return true;
  }
  // MODE ENROLL updates the LED asynchronously. If ENROLL arrives while that
  // one harmless LED command is in flight, queue it instead of making the
  // backend retry.
  if (step_ == Step::Led && ledNext_ == Step::Ready) {
    enrollPending_ = true;
    return true;
  }
  return false;
}

bool Fingerprint::finishEnroll() {
  if (!enrollLearning_ || enrollCleanup_ || enrollProvisionalId_ == 0) {
    return false;
  }
  enrollFinish_ = true;
  requestLed(false);
  return true;
}

bool Fingerprint::startVerify(uint16_t id) {
  if (!linkReady_ || step_ != Step::Ready || id < FP_FIRST_ID ||
      id > FP_LAST_ID) {
    return false;
  }
  startVerifyNow(id, millis());
  return true;
}

bool Fingerprint::startList() {
  if (!linkReady_ || step_ != Step::Ready) {
    return false;
  }
  uint8_t data[4];
  put16(data, FP_FIRST_ID);
  put16(data + 2, FP_LAST_ID);
  step_ = Step::ListCount;
  return sendCommand(CMD_GET_COUNT, data, sizeof(data), millis());
}

bool Fingerprint::startCount() {
  if (!linkReady_ || step_ != Step::Ready) {
    return false;
  }
  uint8_t data[4];
  put16(data, FP_FIRST_ID);
  put16(data + 2, FP_LAST_ID);
  step_ = Step::Count;
  return sendCommand(CMD_GET_COUNT, data, sizeof(data), millis());
}

bool Fingerprint::startHealth() {
  if (!linkReady_ || step_ != Step::Ready) {
    return false;
  }
  step_ = Step::HealthPing;
  return sendCommand(CMD_PING, nullptr, 0, millis());
}

bool Fingerprint::startParams() {
  if (!linkReady_ || step_ != Step::Ready) {
    return false;
  }
  paramType_ = 0;
  step_ = Step::Params;
  return sendCommand(CMD_GET_PARAM, &paramType_, 1, millis());
}

bool Fingerprint::startDelete(uint16_t id) {
  if (!linkReady_ || step_ != Step::Ready || id < FP_FIRST_ID ||
      id > FP_LAST_ID) {
    return false;
  }
  deleteId_ = id;
  uint8_t data[4];
  put16(data, id);
  put16(data + 2, id);
  step_ = Step::Delete;
  return sendCommand(CMD_DELETE_RANGE, data, sizeof(data), millis());
}

bool Fingerprint::startExists(uint16_t id) {
  if (!linkReady_ || step_ != Step::Ready || id < FP_FIRST_ID ||
      id > FP_LAST_ID) {
    return false;
  }
  existsId_ = id;
  uint8_t data[2];
  put16(data, id);
  step_ = Step::Exists;
  return sendCommand(CMD_GET_STATUS, data, sizeof(data), millis());
}

bool Fingerprint::startPing() {
  if (waiting_ || (step_ != Step::Ready && step_ != Step::Fault)) {
    return false;
  }
  return startPing(millis());
}

bool Fingerprint::setLedCommand(bool on, uint32_t now) {
  if (active_ && !on) {
    return false;
  }
  ledWanted_ = on;
  ledDirty_ = true;
  ledRefreshAt_ = 0;

  if (step_ == Step::Ready && linkReady_) {
    uint8_t data[2] = {(uint8_t)(on ? 1 : 0), 0};
    ledTarget_ = on;
    ledNext_ = Step::Ready;
    ledResume_ = true;
    step_ = Step::Led;
    if (!sendCommand(CMD_LED, data, sizeof(data), now)) {
      step_ = Step::Ready;
      return false;
    }
  }
  return true;
}

bool Fingerprint::busy() const {
  return enrollCleanup_ || (step_ != Step::Off && step_ != Step::Ready &&
         step_ != Step::Starting && step_ != Step::Fault);
}

bool Fingerprint::enrolling() const {
  return enrollPending_ || enrollProvisionalId_ != 0 || isEnrollStep(step_) ||
         (step_ == Step::Led && isEnrollStep(ledNext_));
}

ReaderState Fingerprint::state() const {
  switch (step_) {
    case Step::Off:
      return ReaderState::Off;
    case Step::Starting:
      return ReaderState::Starting;
    case Step::Fault:
      return ReaderState::Fault;
    case Step::Ready:
      return ReaderState::Ready;
    default:
      return ReaderState::Busy;
  }
}

// ---------------------------------------------------------------------------
// State transitions
// ---------------------------------------------------------------------------

bool Fingerprint::startPing(uint32_t now) {
  if (waiting_) {
    return false;
  }
  step_ = Step::Ping;
  if (!sendCommand(CMD_PING, nullptr, 0, now)) {
    step_ = Step::Fault;
    retryAt_ = now + FP_LINK_RETRY_MS;
    return false;
  }
  return true;
}

void Fingerprint::startScanNow(uint32_t now) {
  verifyRequest_ = false;
  step_ = Step::WaitFinger;
  startWithLed(Step::WaitFinger, now);
}

void Fingerprint::startVerifyNow(uint16_t id, uint32_t now) {
  verifyRequest_ = true;
  verifyId_ = id;
  step_ = Step::WaitFinger;
  startWithLed(Step::WaitFinger, now);
}

void Fingerprint::startEnrollNow(uint32_t now) {
  verifyRequest_ = false;
  enrollId_ = 0;
  enrollSample_ = 0;
  enrollRetries_ = 0;
  enrollLearning_ = enrollFinish_ = false;
  learnCaptures_ = learnMatches_ = learnUpdates_ = 0;
  learnRetryCenter_ = false;
  startWithLed(Step::EnrollAutoLearn, now);
}

void Fingerprint::startWithLed(Step next, uint32_t now) {
  requestLed(true);
  // Re-assert the LED before a credential operation. If it was refreshed
  // recently, skip the extra command and go straight to work.
  if (ledWanted_ &&
      (ledDirty_ || !ledOn_ || (now - ledRefreshAt_) >= 1000)) {
    uint8_t data[2] = {1, 0};
    ledNext_ = next;
    ledResume_ = false;
    ledTarget_ = true;
    step_ = Step::Led;
    if (!sendCommand(CMD_LED, data, sizeof(data), now)) {
      step_ = next;
      beginStep(now);
    }
    return;
  }

  step_ = next;
  beginStep(now);
}

void Fingerprint::beginStep(uint32_t now) {
  switch (step_) {
    case Step::EnrollAutoLearn: {
      const uint8_t type = 4;
      sendCommand(CMD_GET_PARAM, &type, 1, now);
      break;
    }
    case Step::WaitFinger:
      deadline_ = now + FP_FINGER_TIMEOUT_MS;
      beginPresenceWait(Step::WaitFinger, now);
      break;

    case Step::EnrollFreeId: {
      uint8_t data[4];
      put16(data, FP_FIRST_ID);
      put16(data + 2, FP_LAST_ID);
      sendCommand(CMD_GET_EMPTY_ID, data, sizeof(data), now);
      break;
    }

    default:
      break;
  }
}

void Fingerprint::sendFingerDetect(uint32_t now) {
  sendCommand(CMD_FINGER_DETECT, nullptr, 0, now);
}

void Fingerprint::beginPresenceWait(Step next, uint32_t now) {
  step_ = next;
  presenceCount_ = 0;
  nextPresenceAt_ = now;
}

void Fingerprint::pollPresence(uint32_t now) {
  if (reached(now, nextPresenceAt_)) {
    sendFingerDetect(now);
  }
}

void Fingerprint::onPresenceReply(uint32_t now) {
  if (enrollFinish_) {
    return;  // Drain an in-flight presence query without starting another capture.
  }
  // A slow reply must not revive an expired placement/removal prompt.
  if (!enrollLearning_ && step_ == Step::EnrollWaitRemove && reached(now, deadline_)) {
    sensorError("REMOVE_TIMEOUT", 0, now, false);
    return;
  }
  if (!enrollLearning_ && step_ == Step::EnrollWaitFinger && reached(now, deadline_)) {
    sensorError("FINGER_TIMEOUT", 0, now, false);
    return;
  }
  if (step_ == Step::WaitFinger && !autoScan_ && autoVerifyId_ == 0 &&
      reached(now, deadline_)) {
    if (verifyRequest_) {
      hostEvent("FP VERIFY id=%u result=NOMATCH", verifyId_);
    } else {
      hostEvent("FP NOMATCH");
    }
    startCooldown(now, Outcome::NoMatch);
    return;
  }
  const uint16_t ret = retCode();
  if (ret != 0) {
    // A failed query is not proof of removal. Re-arm through the start gate.
    gateOnStart_ = autoScan_ || autoVerifyId_ != 0;
    sensorError("FINGER_DETECT", ret, now, false);
    return;
  }
  if (!hasData(1) || data8(0) > 1) {
    onTransportError(Reply::BadFrame, now);
    return;
  }

  const bool wantPresent = step_ == Step::WaitFinger ||
                           step_ == Step::EnrollWaitFinger;
  presenceCount_ = (data8(0) != 0) == wantPresent ? presenceCount_ + 1 : 0;
  nextPresenceAt_ = now + FP_PRESENCE_INTERVAL_MS;
  if (presenceCount_ < FP_PRESENCE_CONFIRMATIONS) {
    return;
  }

  switch (step_) {
    case Step::WaitStart:
      step_ = Step::Ready;
      ensureAuto(now);
      break;
    case Step::WaitFinger:
      step_ = Step::Capture;
      sendCommand(CMD_GET_IMAGE, nullptr, 0, now);
      break;
    case Step::WaitRelease:
      startCooldown(now, outcome_);
      break;
    case Step::EnrollWaitRemove:
      beginPresenceWait(Step::EnrollWaitFinger, now);
      deadline_ = now + FP_FINGER_TIMEOUT_MS;
      requestLed(true);
      if (enrollLearning_) {
        hostEvent("FP PROGRESS phase=PLACE stage=LEARN id=%u hint=%s",
                  enrollId_, enrollmentHint());
      } else {
        hostEvent("FP PROGRESS phase=PLACE step=%u/%u hint=CENTER_OVERLAP",
                  enrollSample_ + 1, FP_ENROLL_SAMPLES);
      }
      break;
    case Step::EnrollWaitFinger:
      step_ = Step::EnrollCapture;
      sendCommand(CMD_GET_IMAGE, nullptr, 0, now);
      break;
    default:
      break;
  }
}

void Fingerprint::startWaitRelease(uint32_t now, Outcome outcome) {
  outcome_ = outcome;
  beginPresenceWait(Step::WaitRelease, now);
  requestLed(false);
}

void Fingerprint::startCooldown(uint32_t now, Outcome outcome) {
  outcome_ = outcome;
  step_ = Step::Cooldown;
  requestLed(false);
  deadline_ = now + (outcome == Outcome::Match ? FP_SUCCESS_COOLDOWN_MS
                                               : FP_FAIL_COOLDOWN_MS);
}

void Fingerprint::finishOp(uint32_t now) {
  step_ = Step::Ready;
  enrollId_ = 0;
  enrollSample_ = 0;
  enrollRetries_ = 0;
  if (!autoScan_ && autoVerifyId_ == 0) {
    requestLed(false);
  }
  ensureAuto(now);
}

void Fingerprint::ensureAuto(uint32_t now) {
  if (!active_ || !linkReady_ || step_ != Step::Ready) {
    return;
  }
  // Do not consume the start gate before an auto target exists. MODE VERIFY
  // arms the gate first and receives VERIFY <id> afterwards.
  if (!autoScan_ && autoVerifyId_ == 0) {
    return;
  }
  if (gateOnStart_) {
    gateOnStart_ = false;
    beginPresenceWait(Step::WaitStart, now);
    requestLed(false);
    return;
  }
  if (autoScan_) {
    startScanNow(now);
  } else {
    startVerifyNow(autoVerifyId_, now);
  }
}

void Fingerprint::requestLed(bool on) {
  if (ledWanted_ != on) {
    ledWanted_ = on;
    ledDirty_ = true;
    ledRefreshAt_ = 0;
  }
}

bool Fingerprint::maintainLed(uint32_t now) {
  if (!linkReady_) {
    return false;
  }
  switch (step_) {
    case Step::Ready:
    case Step::WaitStart:
    case Step::WaitFinger:
    case Step::WaitRelease:
    case Step::Cooldown:
    case Step::EnrollWaitRemove:
    case Step::EnrollWaitFinger:
      break;
    default:
      return false;
  }

  bool need = false;
  if (ledDirty_) {
    // Retry an unsettled/rejected command once a second, not every loop.
    need = ledRefreshAt_ == 0 || (now - ledRefreshAt_) >= 1000;
  } else if (ledWanted_) {
    need = (now - ledRefreshAt_) >= FP_LED_REFRESH_MS;
  } else {
    // Turning off only matters if it is known on.
    need = ledOn_ && (now - ledRefreshAt_) >= 1000;
  }
  if (!need) {
    return false;
  }

  uint8_t data[2] = {(uint8_t)(ledWanted_ ? 1 : 0), 0};
  ledTarget_ = ledWanted_;
  ledNext_ = step_;
  ledResume_ = true;
  step_ = Step::Led;
  if (!sendCommand(CMD_LED, data, sizeof(data), now)) {
    step_ = ledNext_;
    return false;
  }
  return true;
}

void Fingerprint::sensorError(const char* what, uint16_t code, uint32_t now,
                              bool waitRelease) {
  if (code != 0) {
    hostErr("FP 0x%02X %s", code, what);
  } else {
    hostErr("FP %s", what);
  }

  outcome_ = Outcome::Error;
  if (enrolling()) {
    abandonEnrollment();
    hostEvent("FP ENROLL_ABORTED");
    finishOp(now);
    return;
  }
  if (waitRelease && linkReady_) {
    startWaitRelease(now, Outcome::Error);
  } else if (linkReady_ && (autoScan_ || autoVerifyId_ != 0)) {
    // In a repeating mode, do not retry a failing command in a tight loop.
    startCooldown(now, Outcome::Error);
  } else {
    finishOp(now);
  }
}

void Fingerprint::enrollRetry(uint32_t now) {
  ++enrollRetries_;
  if (enrollLearning_) learnRetryCenter_ = true;
  hostEvent("FP PROGRESS phase=RETRY stage=%s reason=BAD_QUALITY retry=%lu hint=%s",
            enrollLearning_ ? "LEARN" : "BASE", (unsigned long)enrollRetries_,
            enrollLearning_ ? "MOVE_TOWARD_CENTER" : "CENTER_OVERLAP");
  enrollWaitRemove(now);
}

void Fingerprint::enrollWaitRemove(uint32_t now) {
  beginPresenceWait(Step::EnrollWaitRemove, now);
  requestLed(false);
  deadline_ = now + FP_ENROLL_REMOVE_TIMEOUT_MS;
}

void Fingerprint::abandonEnrollment() {
  enrollLearning_ = false;
  enrollFinish_ = false;
  if (enrollProvisionalId_ != 0) {
    enrollCleanup_ = true;
    enrollCleanupAt_ = millis();
  }
  requestLed(false);
}

void Fingerprint::completeEnrollment(uint32_t now) {
  const uint16_t id = enrollId_;
  enrollFinish_ = enrollLearning_ = false;
  enrollProvisionalId_ = 0;  // Explicit finish commits the provisional template.
  lastId_ = id;
  hostEvent("FP ENROLLED id=%u captures=%lu matches=%lu updates=%lu", id,
            (unsigned long)(FP_ENROLL_SAMPLES + learnCaptures_),
            (unsigned long)learnMatches_, (unsigned long)learnUpdates_);
  finishOp(now);
}

const char* Fingerprint::enrollmentHint() const {
  if (learnRetryCenter_) return "MOVE_TOWARD_CENTER";
  // These are cycling UI suggestions, not coverage feedback from the sensor.
  static const char* hints[] = {"CENTER", "SLIGHT_LEFT", "SLIGHT_RIGHT",
                                "TIP_WITH_OVERLAP", "BASE_WITH_OVERLAP",
                                "ROTATE_SLIGHTLY"};
  return hints[learnMatches_ % (sizeof(hints) / sizeof(hints[0]))];
}

bool Fingerprint::isEnrollStep(Step step) const {
  switch (step) {
    case Step::EnrollAutoLearn:
    case Step::EnrollEnableLearn:
    case Step::EnrollCheckLearn:
    case Step::EnrollFreeId:
    case Step::EnrollWaitRemove:
    case Step::EnrollWaitFinger:
    case Step::EnrollCapture:
    case Step::EnrollGenerate:
    case Step::EnrollMerge:
    case Step::EnrollStore:
    case Step::EnrollLearnVerify:
    case Step::EnrollCleanup:
      return true;
    default:
      return false;
  }
}

// ---------------------------------------------------------------------------
// Reply handling
// ---------------------------------------------------------------------------

void Fingerprint::onReply(uint32_t now) {
  if (sentCommand_ == CMD_FINGER_DETECT && step_ != Step::HealthFinger) {
    onPresenceReply(now);
    return;
  }
  const uint16_t ret = retCode();

  switch (step_) {
    case Step::EnrollAutoLearn:
    case Step::EnrollCheckLearn: {
      if (ret != 0 || !hasData(4)) {
        sensorError("AUTOLEARN_READ", ret, now, false);
        break;
      }
      const uint32_t value = (uint32_t)data16(0) | ((uint32_t)data16(2) << 16);
      if (value == 1) {
        hostEvent("FP PROGRESS phase=AUTOLEARN enabled=1");
        step_ = Step::EnrollFreeId;
        beginStep(now);
      } else if (value == 0 && step_ == Step::EnrollAutoLearn) {
        const uint8_t data[5] = {4, 1, 0, 0, 0};
        step_ = Step::EnrollEnableLearn;
        sendCommand(CMD_SET_PARAM, data, sizeof(data), now);
      } else {
        sensorError("AUTOLEARN_NOT_ENABLED", 0, now, false);
      }
      break;
    }

    case Step::EnrollEnableLearn:
      if (ret == 0) {
        const uint8_t type = 4;
        step_ = Step::EnrollCheckLearn;
        sendCommand(CMD_GET_PARAM, &type, 1, now);
      } else {
        sensorError("AUTOLEARN_SET", ret, now, false);
      }
      break;

    case Step::Led: {
      if (ret == 0) {
        ledOn_ = ledTarget_;
        ledDirty_ = ledOn_ != ledWanted_;
      } else {
        ledDirty_ = true;  // Retry at the 1 s throttle in maintainLed().
      }
      // A cancellation/mode change may change the target while UART is busy.
      ledRefreshAt_ = ret == 0 && ledDirty_ ? 0 : now;
      const Step next = ledNext_;
      const bool resume = ledResume_;
      ledNext_ = Step::Ready;
      ledResume_ = false;
      step_ = next;
      if (step_ == Step::Ready) {
        if (enrollPending_) {
          enrollPending_ = false;
          startEnrollNow(now);
        } else {
          ensureAuto(now);
        }
      } else if (!resume) {
        beginStep(now);
      }
      break;
    }

    case Step::Ping:
      if (ret == 0) {
        linkReady_ = true;
        ledOn_ = false;  // Unknown after a fault; re-assert in the next op.
        ledDirty_ = true;
        ledRefreshAt_ = 0;
        hostEvent("FP READY");
        step_ = Step::Ready;
        // Service a pending LED OFF before re-arming after link recovery.
      } else {
        linkReady_ = false;
        hostErr("FP PING 0x%02X", ret);
        step_ = Step::Fault;
        retryAt_ = now + FP_LINK_RETRY_MS;
      }
      break;

    case Step::Capture:
      if (ret == 0) {
        uint8_t data[2] = {0, 0};  // RamBuffer 0.
        step_ = Step::Generate;
        sendCommand(CMD_GENERATE, data, sizeof(data), now);
      } else if (ret == 0x23 || ret == 0x28) {
        // Touch was detected but no usable finger reached the imager. Require
        // removal before trying again, rather than hammering GET_IMAGE.
        startWaitRelease(now, Outcome::NoMatch);
      } else if (ret == 0x19) {
        sensorError("BAD_QUALITY", ret, now, true);
      } else {
        sensorError("GET_IMAGE", ret, now, true);
      }
      break;

    case Step::Generate:
      if (ret == 0) {
        if (verifyRequest_) {
          uint8_t data[4];
          put16(data, verifyId_);
          put16(data + 2, 0);
          step_ = Step::VerifyCheck;
          sendCommand(CMD_VERIFY, data, sizeof(data), now);
        } else {
          uint8_t data[6];
          put16(data, 0);
          put16(data + 2, FP_FIRST_ID);
          put16(data + 4, FP_LAST_ID);
          step_ = Step::Search;
          sendCommand(CMD_SEARCH, data, sizeof(data), now);
        }
      } else if (ret == 0x19) {
        sensorError("BAD_QUALITY", ret, now, true);
      } else {
        sensorError("GENERATE", ret, now, true);
      }
      break;

    case Step::Search:
      if (ret == 0 && hasData(2)) {
        const uint16_t id = data16(0);
        if (id == 0) {
          hostEvent("FP NOMATCH");
          startWaitRelease(now, Outcome::NoMatch);
        } else {
          lastId_ = id;
          hostEvent("FP MATCH id=%u", id);
          startWaitRelease(now, Outcome::Match);
        }
      } else if (ret == 0x11 || ret == 0x14) {
        hostEvent("FP NOMATCH");
        startWaitRelease(now, Outcome::NoMatch);
      } else {
        sensorError("SEARCH", ret, now, true);
      }
      break;

    case Step::VerifyCheck:
      if (ret == 0) {
        hostEvent("FP VERIFY id=%u result=MATCH", verifyId_);
        startWaitRelease(now, Outcome::Match);
      } else if (ret == 0x10) {
        hostEvent("FP VERIFY id=%u result=NOMATCH", verifyId_);
        startWaitRelease(now, Outcome::NoMatch);
      } else if (ret == 0x12) {
        hostErr("FP 0x12 NO_TEMPLATE");
        startWaitRelease(now, Outcome::Error);
      } else {
        sensorError("VERIFY", ret, now, true);
      }
      break;

    case Step::EnrollFreeId:
      if (ret == 0 && hasData(2)) {
        const uint16_t id = data16(0);
        if (id < FP_FIRST_ID || id > FP_LAST_ID) {
          sensorError("NO_FREE_ID", 0x15, now, false);
          break;
        }
        enrollId_ = id;
        enrollSample_ = 0;
        enrollRetries_ = 0;
        hostEvent("FP PROGRESS phase=FREE_ID id=%u", id);
        beginPresenceWait(Step::EnrollWaitRemove, now);
        requestLed(false);
        deadline_ = now + FP_ENROLL_REMOVE_TIMEOUT_MS;
      } else if (ret == 0x15) {
        sensorError("NO_FREE_ID", ret, now, false);
      } else {
        sensorError("GET_EMPTY_ID", ret, now, false);
      }
      break;

    case Step::EnrollCapture:
      if (ret == 0) {
        uint8_t data[2] = {(uint8_t)(enrollLearning_ ? 0 : enrollSample_), 0};
        step_ = Step::EnrollGenerate;
        sendCommand(CMD_GENERATE, data, sizeof(data), now);
      } else if (ret == 0x23 || ret == 0x28) {
        enrollWaitRemove(now);
        hostEvent("FP PROGRESS phase=REMOVE reason=NO_IMAGE");
      } else if (ret == 0x19) {
        enrollRetry(now);
      } else {
        sensorError("GET_IMAGE", ret, now, true);
      }
      break;

    case Step::EnrollGenerate:
      if (ret == 0 && enrollLearning_) {
        ++learnCaptures_;
        uint8_t data[4];
        put16(data, enrollId_);
        put16(data + 2, 0);
        step_ = Step::EnrollLearnVerify;
        sendCommand(CMD_VERIFY, data, sizeof(data), now);
      } else if (ret == 0) {
        ++enrollSample_;
        enrollRetries_ = 0;
        if (enrollSample_ < FP_ENROLL_SAMPLES) {
          enrollWaitRemove(now);
          hostEvent("FP PROGRESS phase=REMOVE step=%u/%u", enrollSample_,
                    FP_ENROLL_SAMPLES);
        } else {
          uint8_t data[3] = {0, 0, FP_ENROLL_SAMPLES};
          step_ = Step::EnrollMerge;
          sendCommand(CMD_MERGE, data, sizeof(data), now);
        }
      } else if (ret == 0x19) {
        enrollRetry(now);
      } else {
        sensorError("GENERATE", ret, now, true);
      }
      break;

    case Step::EnrollMerge:
      if (ret == 0) {
        uint8_t data[4];
        put16(data, enrollId_);
        put16(data + 2, 0);
        // Mark before sending STORE: a lost reply may still mean it was saved.
        enrollProvisionalId_ = enrollId_;
        step_ = Step::EnrollStore;
        sendCommand(CMD_STORE, data, sizeof(data), now);
      } else if (ret == 0x1A) {
        enrollSample_ = 0;
        enrollRetries_ = 0;
        hostEvent("FP PROGRESS phase=RETRY reason=MERGE_FAIL hint=CENTER_OVERLAP");
        enrollWaitRemove(now);
      } else {
        sensorError("MERGE", ret, now, true);
      }
      break;

    case Step::EnrollStore:
      if (ret == 0) {
        enrollLearning_ = true;
        hostEvent("FP PROGRESS phase=LEARN_READY id=%u finish=ENROLL_FINISH",
                  enrollId_);
        enrollWaitRemove(now);
      } else if (ret == 0x18) {
        enrollProvisionalId_ = 0;  // STORE rejected; never delete the existing ID.
        const uint16_t existing = hasData(2) ? data16(0) : 0;
        hostEvent("FP DUPLICATE id=%u", existing);
        finishOp(now);
      } else {
        sensorError("STORE", ret, now, false);
      }
      break;

    case Step::EnrollLearnVerify:
      if (ret == 0 && hasData(3) && data16(0) == enrollId_) {
        ++learnMatches_;
        learnRetryCenter_ = false;
        const uint8_t update = data8(2);
        if (update != 0) ++learnUpdates_;
        hostEvent("FP LEARN id=%u result=MATCH update=%u captures=%lu matches=%lu",
                  enrollId_, update, (unsigned long)learnCaptures_,
                  (unsigned long)learnMatches_);
        enrollWaitRemove(now);
      } else if (ret == 0x10) {
        learnRetryCenter_ = true;
        hostEvent("FP LEARN id=%u result=NOMATCH captures=%lu hint=MOVE_TOWARD_CENTER",
                  enrollId_, (unsigned long)learnCaptures_);
        enrollWaitRemove(now);
      } else {
        sensorError("LEARN_VERIFY", ret, now, false);
      }
      break;

    case Step::EnrollCleanup:
      if (ret == 0 || ret == 0x12) {
        hostEvent("FP ENROLL_CLEANED id=%u", enrollProvisionalId_);
        enrollProvisionalId_ = 0;
        enrollCleanup_ = false;
        finishOp(now);
      } else {
        hostErr("FP ENROLL_CLEANUP id=%u code=0x%02X", enrollProvisionalId_, ret);
        step_ = Step::Ready;
        enrollCleanupAt_ = now + FP_LINK_RETRY_MS;
      }
      break;

    case Step::ListCount:
      if (ret == 0 && hasData(2)) {
        hostEvent("FP COUNT count=%u", data16(0));
        listId_ = FP_FIRST_ID;
        step_ = Step::ListStatus;
        uint8_t data[2];
        put16(data, listId_);
        sendCommand(CMD_GET_STATUS, data, sizeof(data), now);
      } else {
        sensorError("COUNT", ret, now, false);
      }
      break;

    case Step::ListStatus:
      if (ret == 0 && hasData(1)) {
        if (data8(0) != 0) {
          hostEvent("FP SLOT id=%u", listId_);
        }
        if (listId_ >= FP_LAST_ID) {
          hostEvent("FP LIST_END");
          finishOp(now);
        } else {
          ++listId_;
          uint8_t data[2];
          put16(data, listId_);
          sendCommand(CMD_GET_STATUS, data, sizeof(data), now);
        }
      } else {
        sensorError("GET_STATUS", ret, now, false);
      }
      break;

    case Step::Count:
      if (ret == 0 && hasData(2)) {
        hostEvent("FP COUNT count=%u", data16(0));
        finishOp(now);
      } else {
        sensorError("COUNT", ret, now, false);
      }
      break;

    case Step::Params:
    case Step::HealthParam:
      if (ret == 0 && hasData(4)) {
        const uint32_t value =
            (uint32_t)data16(0) | ((uint32_t)data16(2) << 16);
        hostEvent("FP PARAM type=%u value=%lu", paramType_,
                  (unsigned long)value);
        ++paramType_;
        if (paramType_ < 5) {
          sendCommand(CMD_GET_PARAM, &paramType_, 1, now);
        } else if (step_ == Step::Params) {
          finishOp(now);
        } else {
          uint8_t data[4];
          put16(data, FP_FIRST_ID);
          put16(data + 2, FP_LAST_ID);
          step_ = Step::HealthCount;
          sendCommand(CMD_GET_COUNT, data, sizeof(data), now);
        }
      } else {
        sensorError("GET_PARAM", ret, now, false);
      }
      break;

    case Step::HealthPing:
      if (ret == 0) {
        step_ = Step::HealthFinger;
        sendFingerDetect(now);
      } else {
        sensorError("HEALTH_PING", ret, now, false);
      }
      break;

    case Step::HealthFinger:
      if (ret == 0 && hasData(1)) {
        hostEvent("FP PRESENT present=%u", data8(0));
        paramType_ = 0;
        step_ = Step::HealthParam;
        sendCommand(CMD_GET_PARAM, &paramType_, 1, now);
      } else {
        sensorError("FINGER_DETECT", ret, now, false);
      }
      break;

    case Step::HealthCount:
      if (ret == 0 && hasData(2)) {
        hostEvent("FP COUNT count=%u", data16(0));
        uint8_t data[4];
        put16(data, FP_FIRST_ID);
        put16(data + 2, FP_LAST_ID);
        step_ = Step::HealthBroken;
        sendCommand(CMD_GET_BROKEN_ID, data, sizeof(data), now);
      } else {
        sensorError("COUNT", ret, now, false);
      }
      break;

    case Step::HealthBroken:
      if (ret == 0 && hasData(4)) {
        hostEvent("FP HEALTH broken=%u first=%u tx=%lu timeouts=%lu badframes=%lu",
                  data16(0), data16(2), (unsigned long)transactions_,
                  (unsigned long)timeouts_, (unsigned long)badFrames_);
        finishOp(now);
      } else if (ret == 0x16) {
        hostEvent("FP HEALTH broken=0 first=0 tx=%lu timeouts=%lu badframes=%lu",
                  (unsigned long)transactions_, (unsigned long)timeouts_,
                  (unsigned long)badFrames_);
        finishOp(now);
      } else {
        sensorError("GET_BROKEN_ID", ret, now, false);
      }
      break;

    case Step::Delete:
      if (ret == 0) {
        hostEvent("FP DELETED id=%u", deleteId_);
        finishOp(now);
      } else if (ret == 0x12) {
        hostErr("FP 0x12 NO_TEMPLATE");
        finishOp(now);
      } else {
        sensorError("DELETE", ret, now, false);
      }
      break;

    case Step::Exists:
      if (ret == 0 && hasData(1)) {
        hostEvent("FP EXISTS id=%u registered=%u", existsId_, data8(0));
        finishOp(now);
      } else {
        sensorError("GET_STATUS", ret, now, false);
      }
      break;

    default:
      break;
  }
}

// ---------------------------------------------------------------------------
// Transport
// ---------------------------------------------------------------------------

bool Fingerprint::sendCommand(uint16_t command, const uint8_t* data,
                              uint8_t length, uint32_t now) {
  if (waiting_) {
    return false;
  }
  if (length > 16) {
    return false;
  }

  while (Serial2.available() > 0) {
    Serial2.read();
  }

  uint8_t packet[RESPONSE_BYTES] = {0x55, 0xAA, 0x00, FP_DEVICE_ID};
  put16(packet + 4, command);
  put16(packet + 6, length);
  if (length > 0) {
    memcpy(packet + 8, data, length);
  }
  put16(packet + 24, checksum(packet));

  Serial2.write(packet, sizeof(packet));

  sentCommand_ = command;
  waiting_ = true;
  replyCount_ = 0;
  replyDeadline_ = now + FP_REPLY_TIMEOUT_MS;
  ++transactions_;
  return true;
}

Fingerprint::Reply Fingerprint::pollReply(uint32_t now) {
  while (Serial2.available() > 0) {
    const int value = Serial2.read();
    if (value < 0) {
      break;
    }
    const uint8_t byte = (uint8_t)value;

    if (replyCount_ == 0) {
      if (byte == 0xAA) {
        reply_[replyCount_++] = byte;
      }
    } else if (replyCount_ == 1) {
      if (byte == 0x55) {
        reply_[replyCount_++] = byte;
      } else if (byte == 0xAA) {
        reply_[0] = 0xAA;  // Restart sync on a new 0xAA.
      } else {
        replyCount_ = 0;
      }
    } else {
      reply_[replyCount_++] = byte;
      if (replyCount_ == RESPONSE_BYTES) {
        waiting_ = false;
        if (validReply()) {
          return Reply::Ok;
        }
        ++badFrames_;
        return Reply::BadFrame;
      }
    }
  }

  if (reached(now, replyDeadline_)) {
    waiting_ = false;
    ++timeouts_;
    return Reply::Timeout;
  }
  return Reply::Pending;
}

bool Fingerprint::validReply() const {
  if (reply_[0] != 0xAA || reply_[1] != 0x55) {
    return false;
  }
  if (reply_[3] != 0x00) {  // Destination: host.
    return false;
  }
  if (get16(reply_ + 4) != sentCommand_) {
    return false;
  }
  const uint16_t length = get16(reply_ + 6);
  if (length < 2 || length > 16 || (8u + length) > 24u) {
    return false;
  }
  if (get16(reply_ + 24) != checksum(reply_)) {
    return false;
  }
  if (FP_DEVICE_ID != 0 && reply_[2] != FP_DEVICE_ID) {
    return false;
  }
  return true;
}

void Fingerprint::onTransportError(Reply kind, uint32_t now) {
  const bool wasEnroll = enrolling();
  abandonEnrollment();
  requestLed(false);
  gateOnStart_ = autoScan_ || autoVerifyId_ != 0;
  enrollPending_ = false;
  if (kind == Reply::Timeout) {
    hostErr("FP TIMEOUT");
  } else {
    hostErr("FP BADFRAME");
  }

  if (wasEnroll) {
    hostEvent("FP ENROLL_ABORTED");
  }

  waiting_ = false;
  replyCount_ = 0;
  while (Serial2.available() > 0) {
    Serial2.read();
  }

  linkReady_ = false;
  ledOn_ = false;
  ledDirty_ = true;
  ledRefreshAt_ = 0;
  step_ = Step::Fault;
  retryAt_ = now + FP_LINK_RETRY_MS;
  hostEvent("FP FAULT");
}

uint16_t Fingerprint::retCode() const {
  return get16(reply_ + 8);
}

uint16_t Fingerprint::replyLength() const {
  return get16(reply_ + 6);
}

bool Fingerprint::hasData(uint8_t bytes) const {
  return replyLength() >= (uint16_t)(bytes + 2);
}

uint8_t Fingerprint::data8(uint8_t index) const {
  return reply_[10 + index];
}

uint16_t Fingerprint::data16(uint8_t index) const {
  return get16(reply_ + 10 + index);
}
