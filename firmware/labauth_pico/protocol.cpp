#include "protocol.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#if AUTH_MODE != 0
#error "Authentication is not implemented yet. Keep AUTH_MODE 0 for bench builds."
#endif

namespace {

LineCallback g_callback = nullptr;

char g_line[HOST_LINE_MAX];
size_t g_length = 0;
bool g_overflow = false;

char g_tx[HOST_TX_BYTES];
size_t g_txRead = 0;
size_t g_txWrite = 0;
uint32_t g_dropped = 0;

bool g_wasConnected = false;
bool g_reconnected = false;

size_t txUsed() {
  return (g_txWrite + HOST_TX_BYTES - g_txRead) % HOST_TX_BYTES;
}

void appendLine(const char* text, size_t length) {
  // Reserve one byte so read == write always means empty.
  if (txUsed() + length + 1 >= HOST_TX_BYTES) {
    ++g_dropped;
    return;
  }
  for (size_t i = 0; i < length; ++i) {
    g_tx[g_txWrite] = text[i];
    g_txWrite = (g_txWrite + 1) % HOST_TX_BYTES;
  }
  g_tx[g_txWrite] = '\n';
  g_txWrite = (g_txWrite + 1) % HOST_TX_BYTES;
}

void vformat(char* out, size_t capacity, const char* fmt, va_list args) {
  int written = vsnprintf(out, capacity, fmt, args);
  if (written < 0) {
    out[0] = '\0';
  } else if ((size_t)written >= capacity) {
    out[capacity - 1] = '\0';
  }
}

void dispatchLine() {
  if (g_overflow) {
    hostErr("LINE too-long");
  } else if (g_length > 0) {
    g_line[g_length] = '\0';

    // Normalise command keywords. Arguments are numeric or keywords too, so
    // uppercasing the whole line keeps the serial monitor forgiving.
    for (size_t i = 0; i < g_length; ++i) {
      if (g_line[i] >= 'a' && g_line[i] <= 'z') {
        g_line[i] = (char)(g_line[i] - 'a' + 'A');
      }
    }

#if AUTH_MODE == 0
    // Allow a future signed form: "MODE POLL #<signature>". In bench mode the
    // signature is stripped and ignored.
    char* signature = strstr(g_line, " #");
    if (signature != nullptr) {
      *signature = '\0';
    }
#else
    // TODO: split the trailing "#<signature>", verify HMAC/Ed25519 over
    // "v1 <seq> <body>" and reject on failure before dispatch. See README.
#endif

    if (g_callback != nullptr) {
      g_callback(g_line);
    }
  }
  g_length = 0;
  g_overflow = false;
}

}  // namespace

void hostBegin(LineCallback callback) {
  g_callback = callback;
  uint32_t started = millis();
  while (!Serial && millis() - started < USB_BOOT_WAIT_MS) {
    delay(10);
  }
  g_wasConnected = (bool)Serial;
  g_txRead = g_txWrite = 0;
}

void hostPoll() {
  const bool connected = (bool)Serial;

  if (connected && !g_wasConnected) {
    // Drop anything queued while the host was away; it is stale.
    g_txRead = g_txWrite = 0;
    g_reconnected = true;
  } else if (!connected && g_wasConnected) {
    g_txRead = g_txWrite = 0;
  }
  g_wasConnected = connected;

  while (Serial.available() > 0) {
    const int value = Serial.read();
    if (value < 0) {
      break;
    }
    const char c = (char)value;

    if (c == '\r') {
      continue;
    }
    if (c == '\n') {
      dispatchLine();
      continue;
    }
    if (c == 0x08 || c == 0x7F) {  // Backspace / delete for Serial Monitor.
      if (g_length > 0) {
        --g_length;
      }
      continue;
    }
    if (c < 0x20 || c > 0x7E) {
      continue;
    }
    if (g_length < sizeof(g_line) - 1) {
      g_line[g_length++] = c;
    } else {
      g_overflow = true;
    }
  }
}

void hostFlush() {
  if (!Serial) {
    return;
  }
  while (g_txRead != g_txWrite) {
    const int space = Serial.availableForWrite();
    if (space <= 0) {
      return;
    }
    size_t used = txUsed();
    size_t chunk = used < (size_t)space ? used : (size_t)space;
    size_t first = HOST_TX_BYTES - g_txRead;
    if (first > chunk) {
      first = chunk;
    }
    Serial.write((const uint8_t*)g_tx + g_txRead, first);
    if (chunk > first) {
      Serial.write((const uint8_t*)g_tx, chunk - first);
    }
    g_txRead = (g_txRead + chunk) % HOST_TX_BYTES;
  }
}

bool hostTakeReconnected() {
  const bool value = g_reconnected;
  g_reconnected = false;
  return value;
}

bool hostConnected() {
  return (bool)Serial;
}

uint32_t hostDroppedLines() {
  return g_dropped;
}

void hostSendf(const char* fmt, ...) {
  char body[224];  // Full STATUS includes raw fingerprint diagnostics.
  va_list args;
  va_start(args, fmt);
  vformat(body, sizeof(body), fmt, args);
  va_end(args);
  appendLine(body, strlen(body));
}

void hostEvent(const char* fmt, ...) {
  char body[160];
  va_list args;
  va_start(args, fmt);
  vformat(body, sizeof(body), fmt, args);
  va_end(args);
  hostSendf("EVT %s", body);
}

void hostOk(const char* fmt, ...) {
  char body[160];
  va_list args;
  va_start(args, fmt);
  vformat(body, sizeof(body), fmt, args);
  va_end(args);
  hostSendf("OK %s", body);
}

void hostErr(const char* fmt, ...) {
  char body[160];
  va_list args;
  va_start(args, fmt);
  vformat(body, sizeof(body), fmt, args);
  va_end(args);
  hostSendf("ERR %s", body);
}
