#pragma once

#include <Arduino.h>

#include "types.h"

// ---------------------------------------------------------------------------
// Waveshare UART Fingerprint Sensor (F)
//
// Non-blocking driver + state machine. tick() never waits for a whole
// operation: it reads whatever bytes are available, sends at most one command,
// and returns. Scheduled UART queries confirm finger placement/removal;
// capture/matching also use UART. IRQ is not read and has no interrupt handler.
// This lets the PN532 and the host link run concurrently.
//
// State flow for a 1:N scan:
//   LED ON -> WAIT_FINGER -> GET_IMAGE -> GENERATE -> SEARCH
//          -> WAIT_RELEASE -> COOLDOWN -> READY
//
// State flow for enrollment:
//   LED ON -> FREE_ID -> (WAIT_REMOVE -> WAIT_FINGER -> GET_IMAGE -> GENERATE)
//          x3 -> MERGE -> STORE -> (REMOVE -> CAPTURE -> GENERATE -> VERIFY)*
//          -> ENROLL FINISH -> READY. CANCEL removes the provisional template.
// ---------------------------------------------------------------------------

class Fingerprint {
 public:
  void begin();
  void tick(uint32_t now);

  // Mode support -----------------------------------------------------------
  void setModeActive(bool active);   // Enable reader operations; disable forces LED off.
  void setStartGate(bool require);   // Require finger removal before a mode scans.
  void setAutoScan(bool enabled);    // Repeating 1:N scan (POLL / CHECK).
  void setAutoVerify(uint16_t id);   // Repeating 1:1 scan (VERIFY).
  void cancel();                     // Abort the current operation.

  // Commands ---------------------------------------------------------------
  bool startScan();
  bool startEnroll();
  bool finishEnroll();              // Finish guided learning after current UART work.
  bool startVerify(uint16_t id);
  bool startList();
  bool startCount();
  bool startHealth();
  bool startParams();
  bool startDelete(uint16_t id);
  bool startExists(uint16_t id);
  bool startPing();
  bool setLedCommand(bool on, uint32_t now);

  // Introspection ----------------------------------------------------------
  bool busy() const;
  bool enrolling() const;  // Includes queued enrollment and its LED command.
  bool ledWanted() const { return ledWanted_; }
  ReaderState state() const;
  const char* stateName() const { return readerStateName(state()); }
  bool pollingReady() const {
    return linkReady_ && active_ && autoScan_ && !enrolling() && !enrollCleanup_;
  }
  uint16_t lastId() const { return lastId_; }
  uint16_t enrollmentId() const { return enrollId_ ? enrollId_ : enrollProvisionalId_; }
  bool learning() const { return enrollLearning_; }
  bool cleanupPending() const { return enrollCleanup_; }

 private:
  enum class Step : uint8_t {
    Off,
    Starting,
    Ready,
    Fault,
    Led,
    Ping,

    // 1:N scan or 1:1 verify.
    WaitStart,
    WaitFinger,
    Capture,
    Generate,
    Search,
    VerifyCheck,
    WaitRelease,
    Cooldown,

    // Enrollment.
    EnrollAutoLearn,
    EnrollEnableLearn,
    EnrollCheckLearn,
    EnrollFreeId,
    EnrollWaitRemove,
    EnrollWaitFinger,
    EnrollCapture,
    EnrollGenerate,
    EnrollMerge,
    EnrollStore,
    EnrollLearnVerify,
    EnrollCleanup,

    // Diagnostics.
    ListCount,
    ListStatus,
    Count,
    Params,
    HealthPing,
    HealthFinger,
    HealthParam,
    HealthCount,
    HealthBroken,
    Delete,
    Exists,
  };

  enum class Reply : uint8_t { Pending, Ok, Timeout, BadFrame };
  enum class Outcome : uint8_t { None, Match, NoMatch, Error };

  // Transport --------------------------------------------------------------
  bool sendCommand(uint16_t command, const uint8_t* data, uint8_t length,
                   uint32_t now);
  Reply pollReply(uint32_t now);
  bool validReply() const;
  void onReply(uint32_t now);
  void onTransportError(Reply kind, uint32_t now);

  // State helpers ----------------------------------------------------------
  bool startPing(uint32_t now);
  void startScanNow(uint32_t now);
  void startVerifyNow(uint16_t id, uint32_t now);
  void startEnrollNow(uint32_t now);
  void startWithLed(Step next, uint32_t now);
  void beginStep(uint32_t now);
  void beginPresenceWait(Step next, uint32_t now);
  void pollPresence(uint32_t now);
  void onPresenceReply(uint32_t now);
  void sendFingerDetect(uint32_t now);
  void startWaitRelease(uint32_t now, Outcome outcome);
  void startCooldown(uint32_t now, Outcome outcome);
  void finishOp(uint32_t now);
  void ensureAuto(uint32_t now);
  bool maintainLed(uint32_t now);
  void requestLed(bool on);
  void sensorError(const char* what, uint16_t code, uint32_t now,
                   bool waitRelease);
  void enrollRetry(uint32_t now);
  void enrollWaitRemove(uint32_t now);
  void abandonEnrollment();
  void completeEnrollment(uint32_t now);
  const char* enrollmentHint() const;
  bool isEnrollStep(Step step) const;

  // Reply helpers ----------------------------------------------------------
  uint16_t retCode() const;
  uint16_t replyLength() const;
  bool hasData(uint8_t bytes) const;
  uint8_t data8(uint8_t index) const;
  uint16_t data16(uint8_t index) const;

  // Transport state --------------------------------------------------------
  Step step_ = Step::Off;
  uint8_t reply_[26] = {};
  uint8_t replyCount_ = 0;
  bool waiting_ = false;
  uint16_t sentCommand_ = 0;
  uint32_t replyDeadline_ = 0;

  uint32_t bootAt_ = 0;
  uint32_t retryAt_ = 0;
  uint32_t deadline_ = 0;
  uint32_t ledRefreshAt_ = 0;
  uint32_t nextPresenceAt_ = 0;
  uint8_t presenceCount_ = 0;

  bool linkReady_ = false;
  bool active_ = false;
  bool gateOnStart_ = false;
  bool autoScan_ = false;
  uint16_t autoVerifyId_ = 0;

  bool ledWanted_ = false;
  bool ledOn_ = false;
  bool ledDirty_ = false;
  bool ledTarget_ = false;
  Step ledNext_ = Step::Ready;
  bool ledResume_ = false;  // LED maintenance must not restart operation timers.

  bool verifyRequest_ = false;
  uint16_t verifyId_ = 0;
  uint16_t lastId_ = 0;

  bool enrollPending_ = false;
  uint16_t enrollId_ = 0;
  uint16_t deleteId_ = 0;
  uint16_t existsId_ = 0;
  uint8_t enrollSample_ = 0;
  uint32_t enrollRetries_ = 0;
  bool enrollLearning_ = false;
  bool enrollFinish_ = false;
  bool enrollCleanup_ = false;
  uint16_t enrollProvisionalId_ = 0;
  uint32_t enrollCleanupAt_ = 0;
  uint32_t learnCaptures_ = 0;
  uint32_t learnMatches_ = 0;
  uint32_t learnUpdates_ = 0;
  bool learnRetryCenter_ = false;
  uint16_t listId_ = 0;
  uint8_t paramType_ = 0;

  Outcome outcome_ = Outcome::None;

  uint32_t transactions_ = 0;
  uint32_t timeouts_ = 0;
  uint32_t badFrames_ = 0;
};
