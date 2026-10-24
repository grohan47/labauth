#pragma once

#include <Arduino.h>

#include "config.h"

// ---------------------------------------------------------------------------
// Host link: newline-delimited ASCII over USB CDC.
//
// Commands are ASCII, one per line, case-insensitive. The same commands work
// from the backend (pyserial) and from the Arduino Serial Monitor.
//
// Responses use three prefixes:
//   OK <command> [detail]       command accepted / completed
//   ERR <scope> <detail>        command or reader error
//   EVT <source> <event> ...    asynchronous event
//
// The Pico never decides whether a credential is a sign-in or sign-out. It
// only reports "this template matched" or "this UID was read".
// ---------------------------------------------------------------------------

using LineCallback = void (*)(char* line);

void hostBegin(LineCallback callback);
void hostPoll();                  // Read bytes, dispatch complete lines.
void hostFlush();                 // Non-blocking USB TX drain.
bool hostTakeReconnected();       // True once after the host reconnects.
bool hostConnected();
uint32_t hostDroppedLines();

void hostSendf(const char* fmt, ...);
void hostEvent(const char* fmt, ...);
void hostOk(const char* fmt, ...);
void hostErr(const char* fmt, ...);
