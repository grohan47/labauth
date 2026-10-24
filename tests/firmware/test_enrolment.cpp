#include <cassert>
#include <iostream>

#include "../../firmware/labauth_pico/labauth_pico.ino"

// Drive complete serial commands and real Sensor F packets, without private
// state access. Replies are injected only after observing a complete write.
std::string output() {
  hostFlush();
  std::string value(Serial.tx.begin(), Serial.tx.end());
  Serial.tx.clear();
  return value;
}

std::string command(const std::string& line) {
  output();
  for (const char c : line + '\n') Serial.rx.push_back(c);
  hostPoll();
  return output();
}

void contains(const std::string& text, const char* expected) {
  if (text.find(expected) == std::string::npos) {
    std::cerr << "Missing: " << expected << "\nOutput: " << text;
    std::abort();
  }
}

uint16_t pendingCommand() {
  if (Serial2.tx.size() != 26) {
    std::cerr << "Unexpected UART write size=" << Serial2.tx.size()
              << " time=" << testMillis << " mode=" << modeName(mode) << '\n';
  }
  assert(Serial2.tx.size() == 26);
  return Serial2.tx[4] | (Serial2.tx[5] << 8);
}

std::vector<int> ledHistory;
bool sensorFingerPresent = false;
bool autoPresence = true;
bool autoLearnParam = true;
uint32_t sensorAutoLearn = 1;
std::vector<uint32_t> presenceTimes;

void reply(uint16_t expected, uint16_t result = 0,
           std::vector<uint8_t> data = {}) {
  assert(pendingCommand() == expected);
  if (expected == 0x0024) ledHistory.push_back(Serial2.tx[8]);
  if (expected == 0x0021) presenceTimes.push_back(testMillis);
  Serial2.tx.clear();
  uint8_t packet[26] = {0xAA, 0x55, 0, 0};
  packet[4] = expected & 0xFF;
  packet[5] = expected >> 8;
  packet[6] = data.size() + 2;
  packet[8] = result & 0xFF;
  packet[9] = result >> 8;
  for (size_t i = 0; i < data.size(); ++i) packet[10 + i] = data[i];
  uint16_t sum = 0;
  for (int i = 0; i < 24; ++i) sum += packet[i];
  packet[24] = sum & 0xFF;
  packet[25] = sum >> 8;
  for (uint8_t byte : packet) Serial2.rx.push_back(byte);
  loop();
}

// Service LED and presence transactions, leaving capture/match replies under
// test control. Presence is deliberately independent of the GPIO signal.
void pump() {
  for (int i = 0; i < 12; ++i) {
    loop();
    if (Serial2.tx.empty()) continue;
    if (pendingCommand() == 0x0024) {
      reply(0x0024);
    } else if (pendingCommand() == 0x0021 && autoPresence) {
      reply(0x0021, 0, {(uint8_t)(sensorFingerPresent ? 1 : 0)});
    } else if (pendingCommand() == 0x0003 && Serial2.tx[8] == 4 && autoLearnParam) {
      reply(0x0003, 0, {(uint8_t)sensorAutoLearn, (uint8_t)(sensorAutoLearn >> 8),
                        (uint8_t)(sensorAutoLearn >> 16),
                        (uint8_t)(sensorAutoLearn >> 24)});
    } else {
      return;
    }
  }
}

void advance(uint32_t ms) {
  testMillis += ms;
  pump();
}

void touch(bool present) {
  // Change only the simulated sensor's UART answer, never the GPIO level.
  const size_t before = presenceTimes.size();
  sensorFingerPresent = present;
  pump();
  for (int i = 0; i < FP_PRESENCE_CONFIRMATIONS &&
                  presenceTimes.size() < before + FP_PRESENCE_CONFIRMATIONS; ++i) {
    advance(FP_PRESENCE_INTERVAL_MS);
  }
}

void assertLed(bool on) {
  pump();
  assert(fp.ledWanted() == on);
  if (ledHistory.empty() || ledHistory.back() != (on ? 1 : 0)) {
    std::cerr << "LED expected=" << on << " mode=" << modeName(mode)
              << " state=" << fp.stateName() << " time=" << testMillis
              << " actual=" << (ledHistory.empty() ? -1 : ledHistory.back())
              << '\n';
  }
  assert(!ledHistory.empty() && ledHistory.back() == (on ? 1 : 0));
}

void boot(bool fingerPresent = false) {
  fp = Fingerprint{};
  nfc = Nfc{};
  mode = Mode::Idle;
  fpEnabled = nfcEnabled = true;
  Serial2.rx.clear();
  Serial2.tx.clear();
  ledHistory.clear();
  presenceTimes.clear();
  autoPresence = true;
  autoLearnParam = true;
  sensorAutoLearn = 1;
  sensorFingerPresent = fingerPresent;
  testSetPin(FP_IRQ_PIN, fingerPresent ? LOW : HIGH);  // Intentionally disagree.
  setup();
  assert(Serial2.txPin == 20 && Serial2.rxPin == 21 && FP_IRQ_PIN == 19);
  assert(testPinModes[FP_IRQ_PIN] == INPUT);
  testMillis += FP_BOOT_DELAY_MS;
  loop();
  reply(0x0001);
  assertLed(false);
  output();
}

void armReader(const char* modeCommand = "MODE POLL") {
  contains(command(modeCommand), "OK MODE");
  pump();
  advance(FP_PRESENCE_INTERVAL_MS);
  assert(Serial2.tx.empty());
}

void beginEnrollment(bool queued = true) {
  boot();
  armReader();
  assertLed(true);
  contains(command("MODE ENROLL"), "polling=OFF");
  loop();  // Leave mode LED command in flight for the queue/cancel tests.
  assert(pendingCommand() == 0x0024);
  if (!queued) {
    reply(0x0024);
    testMillis += 1000;
  }
  contains(command("ENROLL"), "OK ENROLL");
  assert(fp.enrolling());
}

void assertExclusive() {
  contains(command("STATUS"), "polling=OFF");
  for (const char* cmd : {"MODE POLL", "MODE CHECK", "MODE VERIFY 41",
                          "MODE IDLE", "MODE MAINT"}) {
    contains(command(cmd), "ERR MODE enrollment-active");
    assert(mode == Mode::Enroll && verifyId == 0);
  }
  contains(command("MODE ENROLL"), "OK MODE ENROLL");
  assert(fp.enrolling());
  contains(command("ENROLL"), "ERR FP BUSY");
  for (const char* cmd : {"FP SCAN", "NFC ON", "NFC READ"})
    contains(command(cmd), "ERR MODE diagnostics-only");
}

void assertPaused() {
  contains(command("STATUS"), "mode=ENROLL");
  contains(command("STATUS"), "polling=OFF");
  assertLed(false);
  advance(1000);
  assert(Serial2.tx.empty());
  const std::string events = output();
  assert(events.find("FP MATCH") == std::string::npos);
  assert(events.find("NFC UID") == std::string::npos);
}

void enrollmentSamples(uint16_t mergeResult = 0) {
  pump();  // Finish mode LED OFF and enrollment LED ON if queued.
  reply(0x0045, 0, {41, 0});
  for (int i = 0; i < FP_ENROLL_SAMPLES; ++i) {
    touch(false);
    assertLed(true);  // Armed for the next impression, using UART presence.
    touch(true);
    reply(0x0020);
    reply(0x0060);
    if (i + 1 < FP_ENROLL_SAMPLES) assertLed(false);  // Must remove first.
  }
  reply(0x0061, mergeResult);
}

void checkEnrollment() {
  beginEnrollment();
  assertExclusive();
  contains(command("CANCEL"), "EVT FP ENROLL_ABORTED");
  reply(0x0024);  // Queued enrollment must not start after cancellation.
  assert(!fp.enrolling());
  assertPaused();

  beginEnrollment(false);  // Enrollment's own LED command is in flight.
  assertExclusive();
  contains(command("CANCEL"), "EVT FP ENROLL_ABORTED");
  assert(!fp.enrolling() && !fp.ledWanted());
  Serial2.tx.clear();  // Abandoned command; recovery must ping before LED off.
  advance(FP_LINK_RETRY_MS);
  reply(0x0001);
  assertPaused();

  beginEnrollment();
  Serial2.tx.clear();  // Drop LED reply to exercise a transport timeout.
  testMillis += FP_REPLY_TIMEOUT_MS;
  loop();
  contains(output(), "EVT FP ENROLL_ABORTED");
  assert(!fp.enrolling() && !fp.ledWanted());
  advance(FP_LINK_RETRY_MS);
  reply(0x0001);
  assertPaused();

  beginEnrollment();
  pump();
  reply(0x0045, 0x15);  // No free slot.
  assert(!fp.enrolling());
  assertPaused();

  beginEnrollment();
  enrollmentSamples();
  assertExclusive();  // Even STORE cannot be interrupted by MODE POLL.
  reply(0x0040);
  contains(output(), "phase=LEARN_READY id=41");
  assert(fp.enrolling() && fp.learning());
  contains(command("ENROLL FINISH"), "OK ENROLL FINISH");
  pump();
  contains(output(), "EVT FP ENROLLED id=41");
  assert(!fp.enrolling());
  assertPaused();

  armReader();
  assertLed(false);  // Enrollment finger is still held on the sensor.
  advance(11000);
  assert(Serial2.tx.empty());
  touch(false);
  assertLed(true);
  touch(true);
  reply(0x0020);
  reply(0x0060);
  reply(0x0063, 0, {41, 0});
  contains(output(), "EVT FP MATCH id=41");
  assertLed(false);
  advance(30000);
  assert(Serial2.tx.empty());  // Held finger never repeats.
  touch(false);
  advance(FP_SUCCESS_COOLDOWN_MS - 1);
  assertLed(false);
  advance(1);
  assertLed(true);
  touch(true);
  assert(pendingCommand() == 0x0020);
}

void checkPollingStatus() {
  boot();
  armReader();
  assert(fp.busy());  // The driver is waiting for a finger, not unavailable.
  contains(command("STATUS"), "mode=POLL fp=READY");
  contains(command("STATUS"), "cleanup=OFF fp_state=BUSY");
  contains(command("FP STATUS"), "FP state=READY");
  sendReady();
  contains(output(), "mode=POLL fp=READY");
  assert(fp.busy());  // Reporting readiness must not change command admission.
  contains(command("FP COUNT"), "ERR MODE diagnostics-only");

  // Actual UART traffic stays Ready throughout polling/capture.
  touch(true);
  assert(pendingCommand() == 0x0020);
  contains(command("STATUS"), "mode=POLL fp=READY");
  assert(fp.busy());

  boot();
  armReader("MODE CHECK");
  contains(command("STATUS"), "mode=CHECK fp=BUSY");

  boot();
  armReader();
  autoPresence = false;
  advance(FP_PRESENCE_INTERVAL_MS);
  reply(0x0021, 0, {});  // Malformed sensor reply creates a real link fault.
  contains(command("STATUS"), "mode=POLL fp=FAULT");
  contains(command("FP STATUS"), "FP state=FAULT");

  // Startup and disabled states are not polling availability.
  fp = Fingerprint{};
  contains(command("FP STATUS"), "FP state=OFF");
  fp.begin();
  contains(command("FP STATUS"), "FP state=STARTING");
  contains(command("FP DISABLE"), "OK FP DISABLE");
  assert(std::string(fingerprintStatusName()) == fp.stateName());
}

void checkUartScans() {
  boot();
  armReader();
  assertLed(true);
  size_t before = presenceTimes.size();
  advance(FP_PRESENCE_INTERVAL_MS - 1);
  assert(presenceTimes.size() == before);  // No tight polling loop.
  advance(1);
  assert(presenceTimes.size() == before + 1);

  // IRQ HIGH/LOW and chatter cannot substitute for a UART presence reply.
  for (int i = 0; i < 8; ++i) {
    testSetPin(FP_IRQ_PIN, i % 2 ? HIGH : LOW);
    advance(FP_PRESENCE_INTERVAL_MS);
    assert(Serial2.tx.empty());
  }
  advance(60000);  // Continuous waiting has no placement timeout.
  assertLed(true);
  assert(Serial2.tx.empty());

  // One stray PRESENT response, then ABSENT, must not start capture.
  sensorFingerPresent = true;
  advance(FP_PRESENCE_INTERVAL_MS);
  assert(Serial2.tx.empty());
  sensorFingerPresent = false;
  advance(FP_PRESENCE_INTERVAL_MS);
  assert(Serial2.tx.empty());
  touch(true);
  reply(0x0020);
  reply(0x0060);
  reply(0x0063, 0x11);
  contains(output(), "EVT FP NOMATCH");
  assertLed(false);
  advance(30000);
  assert(Serial2.tx.empty());
  touch(false);
  advance(FP_FAIL_COOLDOWN_MS - 1);
  assertLed(false);
  advance(1);
  assertLed(true);
  touch(true);
  reply(0x0020, 0x23);  // Presence confirmed, but no image was captured.
  assertLed(false);
  advance(1000);
  assert(Serial2.tx.empty());  // Must remove; no tight GET_IMAGE retry.

  armReader("MODE VERIFY 41");
  assertLed(false);
  advance(11000);
  assert(Serial2.tx.empty());
  touch(false);
  assertLed(true);
  touch(true);
  reply(0x0020);
  reply(0x0060);
  reply(0x0064);
  contains(output(), "EVT FP VERIFY id=41 result=MATCH");
  assertLed(false);

  boot(true);
  armReader();
  assertLed(false);  // UART reports a finger, even though IRQ is LOW.
  advance(11000);
  assert(Serial2.tx.empty());
  touch(false);
  assertLed(true);

  // Poll scheduling remains valid across millis() rollover.
  testMillis = UINT32_MAX - FP_BOOT_DELAY_MS - 250;
  boot();
  armReader();
  // Make a query due just before wrap, then schedule the next across it.
  autoPresence = false;
  advance(FP_PRESENCE_INTERVAL_MS);
  reply(0x0021, 0, {0});
  before = presenceTimes.size();
  advance(FP_PRESENCE_INTERVAL_MS - 1);
  assert(Serial2.tx.empty() && presenceTimes.size() == before);
  advance(1);
  assert(pendingCommand() == 0x0021);
  autoPresence = true;
  pump();
}

void checkPresenceFailures() {
  // A sensor error is not an ABSENT response and must not open the start gate.
  boot(true);
  armReader();
  autoPresence = false;
  advance(FP_PRESENCE_INTERVAL_MS);
  reply(0x0021, 0x23);
  contains(output(), "ERR FP 0x23 FINGER_DETECT");
  autoPresence = true;
  advance(FP_FAIL_COOLDOWN_MS);
  assertLed(false);
  touch(false);
  assertLed(true);

  // Malformed presence data cannot become a placement/removal observation.
  for (const auto& data : {std::vector<uint8_t>{}, std::vector<uint8_t>{2}}) {
    boot();
    armReader();
    autoPresence = false;
    advance(FP_PRESENCE_INTERVAL_MS);
    reply(0x0021, 0, data);
    contains(output(), "EVT FP FAULT");
    assert(!fp.ledWanted());
    advance(FP_LINK_RETRY_MS);
    reply(0x0001);
    autoPresence = true;
    pump();
    advance(FP_PRESENCE_INTERVAL_MS);
    assertLed(true);
  }

  // UART silence does not block the USB command loop; it eventually faults.
  boot();
  armReader();
  autoPresence = false;
  advance(FP_PRESENCE_INTERVAL_MS);
  assert(pendingCommand() == 0x0021);
  contains(command("PING"), "OK PONG");
  Serial2.tx.clear();  // Observed complete write; simulate a missing reply.
  testMillis += FP_REPLY_TIMEOUT_MS;
  loop();
  contains(output(), "ERR FP TIMEOUT");
  assert(!fp.ledWanted());

  // A late PRESENT result cannot revive an expired enrollment prompt.
  beginEnrollment();
  pump();
  reply(0x0045, 0, {41, 0});
  touch(false);
  assertLed(true);
  autoPresence = false;
  advance(FP_PRESENCE_INTERVAL_MS);
  testMillis += FP_FINGER_TIMEOUT_MS;
  reply(0x0021, 0, {1});
  contains(output(), "ERR FP FINGER_TIMEOUT");
  autoPresence = true;
  assertPaused();

  // HEALTH keeps its diagnostic presence reply path and proceeds to params.
  boot();
  contains(command("FP HEALTH"), "OK FP HEALTH");
  reply(0x0001);
  reply(0x0021, 0, {0});
  contains(output(), "EVT FP PRESENT present=0");
  assert(pendingCommand() == 0x0003);
}

void checkTimeoutsAndDisable() {
  beginEnrollment();
  pump();
  reply(0x0045, 0, {41, 0});
  touch(false);
  assertLed(true);
  advance(FP_FINGER_TIMEOUT_MS);
  contains(output(), "ERR FP FINGER_TIMEOUT");
  assert(!fp.enrolling());
  assertPaused();

  beginEnrollment();
  pump();
  touch(true);  // Existing finger must be removed before the first impression.
  reply(0x0045, 0, {41, 0});
  advance(FP_ENROLL_REMOVE_TIMEOUT_MS);
  contains(output(), "ERR FP REMOVE_TIMEOUT");
  assert(!fp.enrolling());
  assertPaused();

  boot();
  armReader();
  assertLed(true);
  armReader("MODE IDLE");
  assertLed(false);
  contains(command("FP SCAN"), "OK FP SCAN");
  assertLed(true);
  advance(FP_FINGER_TIMEOUT_MS);
  contains(output(), "EVT FP NOMATCH");
  assertLed(false);
  advance(FP_FAIL_COOLDOWN_MS);
  assertLed(false);
  assert(!oneShotScan);
  armReader();
  assertLed(true);
  armReader("MODE MAINT");
  assertLed(false);
}

void checkReaderSwitches() {
  boot();
  armReader();
  assertLed(true);
  contains(command("FP DISABLE"), "OK FP DISABLE");
  contains(command("STATUS"), "fp_enabled=OFF");
  assert(mode == Mode::Poll);
  assertLed(false);
  touch(true);
  advance(60000);
  assert(Serial2.tx.empty());
  contains(command("FP SCAN"), "ERR FP DISABLED");
  contains(command("LED ON"), "ERR FP DISABLED");
  contains(command("FP LED ON"), "ERR FP DISABLED");
  contains(command("ENROLL"), "ERR FP DISABLED");
  contains(command("FP STATUS"), "enabled=OFF");
  armReader("MODE CHECK");
  contains(command("STATUS"), "fp_enabled=OFF");
  assertLed(false);
  contains(command("FP ENABLE"), "OK FP ENABLE");
  assertLed(false);  // Existing touch must be removed before resuming.
  touch(false);
  assertLed(true);
  touch(true);
  reply(0x0020);
  reply(0x0060);
  reply(0x0063, 0, {41, 0});
  contains(output(), "EVT FP MATCH id=41");

  // DISABLE also suppresses a result whose UART reply arrives afterward.
  boot();
  armReader();
  touch(true);
  reply(0x0020);
  reply(0x0060);
  assert(pendingCommand() == 0x0063);
  contains(command("FP DISABLE"), "OK FP DISABLE");
  reply(0x0063, 0, {41, 0});  // Late response to abandoned SEARCH.
  assert(output().find("FP MATCH") == std::string::npos);
  advance(FP_LINK_RETRY_MS);
  reply(0x0001);
  assertLed(false);
  contains(command("STATUS"), "fp_enabled=OFF");
  contains(command("FP DISABLE"), "OK FP DISABLE");
  contains(command("FP ENABLE EXTRA"), "ERR ARG fp-switch");
  contains(command("STATUS"), "fp_enabled=OFF");

  // A one-shot is also cancelled and never restarted by ENABLE in IDLE.
  boot();
  contains(command("FP SCAN"), "OK FP SCAN");
  assertLed(true);
  contains(command("FP DISABLE"), "OK FP DISABLE");
  assert(!oneShotScan);
  assertLed(false);
  contains(command("FP ENABLE"), "OK FP ENABLE");
  assertLed(false);
  touch(true);
  assert(Serial2.tx.empty());

  // Disabling NFC must neither cancel fingerprint enrollment nor bypass it.
  beginEnrollment();
  assert(fp.enrolling());
  contains(command("FP ENABLE"), "OK FP ENABLE");
  assert(fp.enrolling());  // Idempotent ENABLE preserves the active operation.
  contains(command("NFC DISABLE"), "OK NFC DISABLE");
  contains(command("NFC ENABLE EXTRA"), "ERR ARG nfc-switch");
  contains(command("STATUS"), "nfc_enabled=OFF");
  assert(fp.enrolling());
  contains(command("NFC ENABLE"), "OK NFC ENABLE");
  assert(fp.enrolling() && mode == Mode::Enroll);
  contains(command("NFC READ"), "ERR MODE diagnostics-only");
  contains(command("NFC ON"), "ERR MODE diagnostics-only");
  contains(command("NFC DISABLE"), "OK NFC DISABLE");

  // Disable can explicitly abort enrollment, including its queued LED setup.
  contains(command("FP DISABLE"), "EVT FP ENROLL_ABORTED");
  assert(!fp.enrolling());
  reply(0x0024);
  assertLed(false);
  contains(command("FP ENABLE"), "OK FP ENABLE");
  assertPaused();  // No automatic enrollment or attendance restart.
  armReader();
  contains(command("STATUS"), "nfc_enabled=OFF");
  armReader("MODE MAINT");
  contains(command("NFC READ"), "ERR NFC DISABLED");
  contains(command("NFC ON"), "ERR NFC DISABLED");
  contains(command("NFC STATUS"), "enabled=OFF");
  contains(command("NFC ENABLE"), "OK NFC ENABLE");
  contains(command("NFC READ"), "ERR NFC ABSENT");
  contains(command("STATUS"), "nfc=ABSENT");  // Enable is not hardware presence.

  // A disabled reader stays disabled through VERIFY and does not capture.
  contains(command("FP DISABLE"), "OK FP DISABLE");
  armReader("MODE VERIFY 41");
  contains(command("VERIFY 41"), "ERR FP DISABLED");
  touch(true);
  assert(Serial2.tx.empty());
  contains(command("FP ENABLE"), "OK FP ENABLE");
  assertLed(false);
  touch(false);
  assertLed(true);
  touch(true);
  reply(0x0020);
  reply(0x0060);
  reply(0x0064);
  contains(output(), "EVT FP VERIFY id=41 result=MATCH");
}

void startLearning() {
  beginEnrollment();
  enrollmentSamples();
  assert(Serial2.tx[8] == 41 && Serial2.tx[10] == 0);
  reply(0x0040);
  contains(output(), "phase=LEARN_READY id=41");
  assert(fp.enrolling() && fp.learning());
}

std::string learningCapture(uint16_t result = 0, uint8_t update = 1) {
  touch(false);
  assertLed(true);
  touch(true);
  reply(0x0020);
  assert(Serial2.tx[8] == 0);  // Learning always generates into RAM buffer 0.
  reply(0x0060);
  assert(Serial2.tx[8] == 41 && Serial2.tx[10] == 0);  // VERIFY ID, buffer.
  reply(0x0064, result, result == 0 ? std::vector<uint8_t>{41, 0, update}
                                  : std::vector<uint8_t>{});
  const std::string events = output();
  assert(events.find("FP MATCH") == std::string::npos);
  assert(events.find("FP VERIFY") == std::string::npos);
  assert(events.find("FP ENROLLED") == std::string::npos);
  return events;
}

void cleanEnrollment() {
  pump();
  assert(pendingCommand() == 0x0044);
  assert(Serial2.tx[8] == 41 && Serial2.tx[9] == 0 &&
         Serial2.tx[10] == 41 && Serial2.tx[11] == 0);
  reply(0x0044);
  contains(output(), "EVT FP ENROLL_CLEANED id=41");
  assert(!fp.enrolling() && !fp.cleanupPending());
  assertPaused();
}

void checkGuidedLearning() {
  startLearning();
  assertExclusive();
  advance(60000);  // Held finger/removal prompt has no learning timeout.
  assert(fp.learning());
  touch(false);
  advance(60000);  // Neither does the placement prompt.
  assertLed(true);
  contains(learningCapture(0, 0), "result=MATCH update=0");
  assert(fp.learning());  // No update is not proof of complete coverage.
  contains(learningCapture(0x10), "result=NOMATCH");
  touch(false);
  contains(output(), "hint=MOVE_TOWARD_CENTER");
  for (int i = 0; i < 13; ++i) {
    contains(learningCapture(), "result=MATCH update=1");
    assert(fp.learning());  // More than ten captures never auto-finishes.
  }
  contains(command("STATUS"), "learning=ON");
  assertExclusive();

  // FINISH drains an in-flight presence reply without beginning a new image.
  autoPresence = false;
  advance(FP_PRESENCE_INTERVAL_MS);
  assert(pendingCommand() == 0x0021);
  contains(command("ENROLL FINISH"), "OK ENROLL FINISH");
  reply(0x0021, 0, {1});
  assert(Serial2.tx.empty());
  autoPresence = true;
  pump();
  contains(output(), "FP ENROLLED id=41 captures=18 matches=14 updates=13");
  assert(!fp.enrolling());
  assertPaused();

  // FINISH during image processing drains GENERATE and VERIFY in sequence.
  startLearning();
  touch(false);
  touch(true);
  assert(pendingCommand() == 0x0020);
  contains(command("ENROLL FINISH"), "OK ENROLL FINISH");
  reply(0x0020);
  reply(0x0060);
  reply(0x0064, 0, {41, 0, 1});
  pump();
  contains(output(), "FP ENROLLED id=41 captures=4 matches=1 updates=1");
  assertPaused();
}

void checkLearningParametersAndRetries() {
  beginEnrollment();
  autoLearnParam = false;
  pump();
  contains(command("ENROLL FINISH"), "ERR FP NOT_LEARNING");
  assert(Serial2.tx[8] == 4);
  reply(0x0003, 0, {0, 0, 0, 0});
  assert(pendingCommand() == 0x0002 && Serial2.tx[6] == 5 &&
         Serial2.tx[8] == 4 && Serial2.tx[9] == 1);
  reply(0x0002);
  reply(0x0003, 0, {1, 0, 0, 0});
  assert(pendingCommand() == 0x0045);

  // Refuse enrollment if the module ignores SET_PARAM; no provisional STORE.
  beginEnrollment();
  autoLearnParam = false;
  pump();
  reply(0x0003, 0, {0, 0, 0, 0});
  reply(0x0002);
  reply(0x0003, 0, {0, 0, 0, 0});
  contains(output(), "ERR FP AUTOLEARN_NOT_ENABLED");
  assert(!fp.enrolling());
  assertPaused();

  // Bad quality retries the same baseline slot instead of ending after one retry.
  beginEnrollment();
  pump();
  reply(0x0045, 0, {41, 0});
  for (int i = 0; i < 4; ++i) {
    touch(false);
    touch(true);
    reply(0x0020);
    assert(Serial2.tx[8] == 0);
    reply(0x0060, 0x19);
    contains(output(), "reason=BAD_QUALITY");
    assert(fp.enrolling());
  }

  // A rejected merge asks for a fresh overlapping baseline, not a new user/ID.
  beginEnrollment();
  enrollmentSamples(0x1A);
  contains(output(), "reason=MERGE_FAIL hint=CENTER_OVERLAP");
  for (int i = 0; i < FP_ENROLL_SAMPLES; ++i) {
    touch(false);
    touch(true);
    reply(0x0020);
    assert(Serial2.tx[8] == i);
    reply(0x0060);
  }
  assert(pendingCommand() == 0x0061 && Serial2.tx[10] == 3);
  reply(0x0061);
  reply(0x0040, 0x18, {17, 0});
  contains(output(), "FP DUPLICATE id=17");
  assert(!fp.cleanupPending());  // Never delete somebody else's template.
  assertPaused();
}

void checkLearningCleanup() {
  startLearning();
  assertLed(false);
  contains(command("CANCEL"), "FP ENROLL_ABORTED");
  contains(command("MODE POLL"), "ERR MODE enrollment-active");
  cleanEnrollment();

  startLearning();
  assertLed(false);
  contains(command("FP DISABLE"), "OK FP DISABLE");
  assert(!fpEnabled && fp.cleanupPending());
  cleanEnrollment();  // Rollback still runs while scanning is disabled.

  // A STORE reply may be lost after the module actually wrote the template.
  beginEnrollment();
  enrollmentSamples();
  assert(pendingCommand() == 0x0040);
  contains(command("CANCEL"), "FP ENROLL_ABORTED");
  reply(0x0040);  // Late reply to abandoned STORE must not enter learning.
  advance(FP_LINK_RETRY_MS);
  reply(0x0001);
  cleanEnrollment();

  // A UART failure in learning also rolls back after link resynchronization.
  startLearning();
  touch(false);
  touch(true);
  reply(0x0020);
  reply(0x0060);
  assert(pendingCommand() == 0x0064);
  Serial2.tx.clear();
  testMillis += FP_REPLY_TIMEOUT_MS;
  loop();
  contains(output(), "FP ENROLL_ABORTED");
  assert(fp.cleanupPending());
  advance(FP_LINK_RETRY_MS);
  reply(0x0001);
  pump();
  reply(0x0044, 0x22);
  contains(output(), "FP ENROLL_CLEANUP id=41");
  contains(command("ENROLL"), "ERR FP BUSY");
  contains(command("MODE POLL"), "ERR MODE enrollment-active");
  advance(FP_LINK_RETRY_MS);
  cleanEnrollment();

  // A malformed/foreign verification result cannot finalize the provisional ID.
  startLearning();
  touch(false);
  touch(true);
  reply(0x0020);
  reply(0x0060);
  reply(0x0064, 0, {17, 0, 1});
  contains(output(), "ERR FP LEARN_VERIFY");
  cleanEnrollment();
}

int main() {
  checkEnrollment();
  checkPollingStatus();
  checkUartScans();
  checkPresenceFailures();
  checkTimeoutsAndDisable();
  checkReaderSwitches();
  checkGuidedLearning();
  checkLearningParametersAndRetries();
  checkLearningCleanup();
  std::cout << "PASS: UART-only presence polling and confirmation, IRQ ignored, enrollment "
               "exclusivity/cancel/failure/success, held-finger gates, "
               "cooldowns, verify, timer rollover, LED off on timeout/disable "
               "and on again when armed, fault recovery, independent reader "
               "switches, uncapped guided Auto Learn, explicit finish and "
               "provisional-template rollback\n";
}
