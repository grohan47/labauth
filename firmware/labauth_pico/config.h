#pragma once

#include <stdint.h>
#include <stddef.h>

// ---------------------------------------------------------------------------
// LabAuth Pico firmware configuration
//
// Target: Raspberry Pi Pico, Arduino-Pico core (Earle Philhower).
// The Pico is a dumb bridge: it reports credential IDs and accepts mode
// commands. Sign-in/out, user lookup, cooldowns and persistence belong to the
// backend.
// ---------------------------------------------------------------------------

#define LABAUTH_FW_VERSION 1

// Reboot if loop() ever stops making progress. The longest legitimate blocking
// operation is one 26-byte UART write, far below this.
constexpr uint32_t WDT_TIMEOUT_MS = 10000;

// ---------------------------------------------------------------------------
// Host link: USB CDC ("Serial" in Arduino-Pico)
// ---------------------------------------------------------------------------
constexpr uint32_t USB_SERIAL_BAUD = 115200;  // Ignored by USB CDC.
constexpr uint32_t USB_BOOT_WAIT_MS = 5000;   // Give the monitor a chance to open.
constexpr size_t HOST_LINE_MAX = 120;
constexpr size_t HOST_TX_BYTES = 2048;

// 0 = unauthenticated bench/testing mode.
// Future: 1 = HMAC-SHA256, 2 = Ed25519 signatures. See README "Security".
#define AUTH_MODE 0

// ---------------------------------------------------------------------------
// Waveshare UART Fingerprint Sensor (F)
//
// UART1 (Serial2), 3.3 V logic. TX/RX are crossed. No level shifter is needed.
// Template IDs are stored on the sensor; the backend stores the
// template-ID <-> user association.
// ---------------------------------------------------------------------------
constexpr uint8_t FP_TX_PIN = 20;  // GP20 / UART1 TX -> sensor RXD
constexpr uint8_t FP_RX_PIN = 21;  // GP21 / UART1 RX <- sensor TXD
constexpr uint8_t FP_IRQ_PIN = 19; // IRQ may remain connected; unused input.
// Connect VIN and VT to 3.3 V. VT powers touch detection; it is not a signal.
constexpr uint32_t FP_BAUD = 115200;
constexpr uint8_t FP_DEVICE_ID = 0;  // 0 = broadcast.
constexpr uint16_t FP_FIRST_ID = 1;
constexpr uint16_t FP_LAST_ID = 1000;  // Sensor F capacity (SKU 31887).
constexpr size_t FP_UART_RX_BUFFER_BYTES = 64;

constexpr uint32_t FP_BOOT_DELAY_MS = 300;       // Sensor needs >= 280 ms.
constexpr uint32_t FP_REPLY_TIMEOUT_MS = 5000;   // Per command.
constexpr uint32_t FP_FINGER_TIMEOUT_MS = 20000; // Wait for placement.
constexpr uint32_t FP_ENROLL_REMOVE_TIMEOUT_MS = 10000;
constexpr uint32_t FP_PRESENCE_INTERVAL_MS = 100;
constexpr uint8_t FP_PRESENCE_CONFIRMATIONS = 2; // Consecutive UART results.
constexpr uint32_t FP_LINK_RETRY_MS = 1000;
constexpr uint32_t FP_LED_REFRESH_MS = 5000;

// The important anti-spam policy:
// - successful read: short cooldown, so a queue of people can move quickly.
// - unsuccessful read: longer cooldown, so a bad finger does not spam events.
// Both start only after the finger has been removed.
constexpr uint32_t FP_SUCCESS_COOLDOWN_MS = 100;
constexpr uint32_t FP_FAIL_COOLDOWN_MS = 200;

// Sensor F can merge only 2 or 3 templates. Further placements use Auto Learn.
constexpr uint8_t FP_ENROLL_SAMPLES = 3;
// Guided learning has no capture cap and ends only on ENROLL FINISH/CANCEL.

// ---------------------------------------------------------------------------
// PN532 (future), I2C0
//
// The PN532 I2C path uses 0x24. Do not run an I2C address scan: the PN532
// clock-stretches and expects a status-byte read, and a bare probe can leave
// it holding SCL low. Most cheap "PN532" boards are 5 V modules; power from
// 5 V and level-shift SDA/SCL to 3.3 V.
//
// Reserved now so the wiring does not move when the reader arrives.
// Fingerprint UART1 uses GP20/GP21; unused IRQ GP19; PN532 uses GP4/GP5.
// ---------------------------------------------------------------------------
#define ENABLE_PN532 0

constexpr uint8_t NFC_SDA_PIN = 4;  // GP4 / I2C0 SDA
constexpr uint8_t NFC_SCL_PIN = 5;  // GP5 / I2C0 SCL
constexpr uint32_t NFC_I2C_HZ = 100000;
constexpr uint8_t NFC_I2C_ADDRESS = 0x24;
constexpr uint32_t NFC_I2C_TIMEOUT_MS = 25;

constexpr uint32_t NFC_POLL_INTERVAL_MS = 100;
constexpr uint32_t NFC_RELEASE_MS = 500;        // No card before re-arming.
constexpr uint32_t NFC_SUCCESS_COOLDOWN_MS = 300;
constexpr uint32_t NFC_FAIL_COOLDOWN_MS = 1000;
constexpr uint32_t NFC_HEALTH_CHECK_MS = 5000;
constexpr size_t NFC_RX_BUFFER_BYTES = 256;

// ---------------------------------------------------------------------------
// Compile-time wiring checks
// ---------------------------------------------------------------------------
static_assert(FP_TX_PIN != FP_RX_PIN, "Fingerprint TX and RX must differ");
static_assert(FP_IRQ_PIN != FP_TX_PIN && FP_IRQ_PIN != FP_RX_PIN,
              "Fingerprint IRQ and UART pins must differ");
static_assert(FP_FIRST_ID >= 1 && FP_FIRST_ID <= FP_LAST_ID,
              "Invalid fingerprint ID range");
static_assert(FP_PRESENCE_INTERVAL_MS > 0 && FP_PRESENCE_CONFIRMATIONS > 0,
              "Presence polling needs a positive interval and confirmation count");
static_assert(FP_ENROLL_SAMPLES == 3, "Sensor F baseline uses three RAM buffers");
static_assert(!(FP_TX_PIN == NFC_SDA_PIN || FP_TX_PIN == NFC_SCL_PIN ||
                FP_RX_PIN == NFC_SDA_PIN || FP_RX_PIN == NFC_SCL_PIN ||
                FP_IRQ_PIN == NFC_SDA_PIN || FP_IRQ_PIN == NFC_SCL_PIN),
              "Fingerprint and PN532 I2C pins overlap");
