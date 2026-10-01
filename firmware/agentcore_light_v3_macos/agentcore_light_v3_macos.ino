#include <Adafruit_NeoPixel.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define LED_PIN 4
#define LED_COUNT 8
#define LED_BRIGHTNESS 10

#define OLED_SDA 8
#define OLED_SCL 9
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
#define OLED_ADDRESS 0x3C
#define MAX_HARDWARE_BRIGHTNESS 128

Adafruit_NeoPixel pixels(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

enum AgentState {
  STATE_IDLE,
  STATE_THINKING,
  STATE_WRITING,
  STATE_RUNNING,
  STATE_DONE,
  STATE_ERROR,
  STATE_NEED_CONFIRM,
  STATE_OFF
};

AgentState currentState = STATE_IDLE;

String serialBuffer;
const int TITLE_BYTES = 3584;  // 2048 x 14, one bit per pixel.
uint8_t threadTitles[8][TITLE_BYTES] = {};
uint16_t titleWidths[8] = {92,92,92,92,92,92,92,92};
int titleOffsets[8] = {};
int titleHolds[8] = {};
uint8_t pendingTitle[TITLE_BYTES];
int pendingSlot = -1, pendingWidth = 0, pendingLength = 0, pendingReceived = 0;
bool threadTitleReady[8] = {};
String threadFrame = "THREADS:00000000,0,0,0";
char threadStates[9] = "00000000";
int threadActive = 0, threadWaiting = 0, threadOverflow = 0;
const uint8_t threadColors[8][3] = {{160,80,255},{255,80,80},{0,214,220},{255,148,31},
                                  {57,140,255},{255,99,174},{83,219,121},{255,211,77}};

bool hasThreads() { return strcmp(threadStates, "00000000") != 0; }


bool oledReady = false;
unsigned long stateStartedAt = 0;
unsigned long lastLedFrameAt = 0;
unsigned long lastOledFrameAt = 0;

int tokenPercent = 100;
bool quotaKnown = false;
bool quotaStale = true;
unsigned long lastQuotaAt = 0;
unsigned long lastHostAt = 0;
bool lastOffline = false;
bool lastStale = true;
// v3 has eight bright NeoPixel LEDs; keep the factory default comfortable.
int brightnessPercent = 16;
int idleBrightness = 2;
int idleDirection = 1;
bool tokenBlinkOn = true;
int rotatingPos = 0;
int writingPos = 0;
int pulseStep = 0;
bool alertPhaseBlue = true;
// Rotate whole-ring task displays without restarting the five-second dwell on hook updates.
int displayedThread = -1;
unsigned long threadDisplayStartedAt = 0;

void effectThreads() {
  unsigned long now = millis();
  if (displayedThread < 0 || threadStates[displayedThread] == '0' ||
      now - threadDisplayStartedAt >= 5000UL) {
    for (int offset = 1; offset <= 8; offset++) {
      int candidate = (displayedThread + offset) % 8;
      if (threadStates[candidate] != '0') {
        displayedThread = candidate;
        threadDisplayStartedAt = now;
        break;
      }
    }
  }
  if (displayedThread < 0 || now - lastLedFrameAt < 20) return;
  lastLedFrameAt = now;
  setDeviceBrightness();
  char state = threadStates[displayedThread];
  unsigned long elapsed = now - threadDisplayStartedAt;
  int interval = state == '1' ? 95 : (state == '2' ? 55 : 40);
  int head = (elapsed / interval) % LED_COUNT;
  for (int i = 0; i < LED_COUNT; i++) {
    int distance = (head - i + LED_COUNT) % LED_COUNT;
    int level = distance == 0 ? 255 : (distance == 1 ? 90 : (distance == 2 ? 25 : 0));
    if (state == '4') level = 180;
    else if (state == '5') level = elapsed % 250 < 125 ? 255 : 0;
    else if (state == '6') {
      int phase = elapsed % 1400;
      level = (phase < 120 || (phase >= 260 && phase < 380)) ? 255 : 0;
    }
    pixels.setPixelColor(i, pixels.Color(threadColors[displayedThread][0]*level/255,
                         threadColors[displayedThread][1]*level/255,
                         threadColors[displayedThread][2]*level/255));
  }
  pixels.show();
}

void setup() {
  // Title frames exceed the USB CDC default 256-byte queue.
  Serial.setRxBufferSize(1024);
  Serial.setTxBufferSize(1024);
  Serial.begin(115200);
  serialBuffer.reserve(384);

  pixels.begin();
  setDeviceBrightness();
  pixels.clear();
  pixels.show();

  Wire.begin(OLED_SDA, OLED_SCL);
  Wire.setTimeOut(50);
  oledReady = display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDRESS);
  if (!oledReady) {
    Serial.println("OLED init failed. WS2812 will continue running.");
  } else {
    display.setRotation(0);
    display.ssd1306_command(SSD1306_SETCONTRAST);
    display.ssd1306_command(255);
    display.clearDisplay();
    display.display();
  }

  setState(STATE_IDLE);
  Serial.println("ESP32-C3 AI Agent status light ready.");
  Serial.println("AgentCore-Light v3 firmware ready (NeoPixel + OLED, no buzzer). MAC4");
  Serial.println("Commands: IDLE, THINKING, WRITING, RUNNING, DONE, ERROR, NEED_CONFIRM, TOKEN:x, BRIGHTNESS:x, STATUS");
}

void loop() {
  readSerialCommands();

  if (hasThreads() && currentState != STATE_OFF) effectThreads();
  else switch (currentState) {
    case STATE_IDLE:
      effectIdle();
      break;
    case STATE_THINKING:
      effectThinking();
      break;
    case STATE_WRITING:
      effectWriting();
      break;
    case STATE_RUNNING:
      effectRunning();
      break;
    case STATE_DONE:
      effectDone();
      break;
    case STATE_ERROR:
      effectError();
      break;
    case STATE_NEED_CONFIRM:
      effectNeedConfirm();
      break;
    case STATE_OFF:
      effectOff();
      break;
  }

  updateOLEDAnimation();
  delay(1);
}

void readSerialCommands() {
  while (Serial.available() > 0) {
    char c = Serial.read();

    if (c == '\n' || c == '\r') {
      if (serialBuffer.length() > 0) {
        handleCommand(serialBuffer);
        serialBuffer = "";
      }
    } else if (serialBuffer.length() < 383) {
      serialBuffer += c;
    }
  }
}

void handleCommand(String command) {
  command.trim();
  command.toUpperCase();

  if (command.length() == 0) {
    return;
  }
  lastHostAt = millis();

  if (command.startsWith("TBEGIN:")) {
    int slot, width, consumed = 0;
    pendingSlot = -1;
    if (sscanf(command.c_str(), "TBEGIN:%d:%d%n", &slot, &width, &consumed) != 2 ||
        consumed != command.length() || slot < 1 || slot > 8 || width < 92 || width > 2048) {
      Serial.println("ERR invalid title begin"); return;
    }
    pendingSlot = slot - 1; pendingWidth = width;
    pendingLength = ((width + 7) / 8) * 14; pendingReceived = 0;
    Serial.println(command); return;
  }
  if (command.startsWith("TDATA:")) {
    int slot, offset, start = 0;
    if (sscanf(command.c_str(), "TDATA:%d:%d:%n", &slot, &offset, &start) != 2 ||
        start <= 0 || slot - 1 != pendingSlot || pendingSlot < 0 || offset != pendingReceived) {
      Serial.println("ERR invalid title offset"); return;
    }
    int length = command.length() - start;
    if (length < 2 || length > 256 || length % 2 || offset + length/2 > pendingLength) {
      Serial.println("ERR invalid title size"); return;
    }
    for (int i = start; i < command.length(); i++) {
      if (!isxdigit(command[i])) { Serial.println("ERR invalid title data"); return; }
    }
    for (int i = 0; i < length/2; i++) {
      char hex[3] = {command[start+i*2], command[start+i*2+1], 0};
      pendingTitle[offset+i] = strtoul(hex, nullptr, 16);
    }
    pendingReceived += length/2;
    Serial.println(command); return;
  }
  if (command.startsWith("TEND:")) {
    int slot, consumed = 0;
    if (sscanf(command.c_str(), "TEND:%d%n", &slot, &consumed) != 1 ||
        consumed != command.length() || pendingSlot < 0 || slot-1 != pendingSlot || pendingReceived != pendingLength) {
      Serial.println("ERR incomplete title"); return;
    }
    memcpy(threadTitles[pendingSlot], pendingTitle, pendingLength);
    titleWidths[pendingSlot] = pendingWidth;
    titleOffsets[pendingSlot] = 0; titleHolds[pendingSlot] = 10;
    bool any = false;
    for (int i = 0; i < pendingLength; i++) any |= pendingTitle[i] != 0;
    threadTitleReady[pendingSlot] = any;
    pendingSlot = -1;
    Serial.println(command); updateOLED(); return;
  }

  if (command.startsWith("TITLE:")) {
    if (command.length() != 344 || command[6] < '1' || command[6] > '8' || command[7] != ':') {
      Serial.println("ERR invalid title"); return;
    }
    for (int i = 8; i < 344; i++) {
      if (!isxdigit(command[i])) { Serial.println("ERR invalid title"); return; }
    }
    int slot = command[6] - '1';
    bool any = false;
    for (int i = 0; i < 168; i++) {
      char hex[3] = {command[8 + i*2], command[9 + i*2], 0};
      threadTitles[slot][i] = strtoul(hex, nullptr, 16);
      any |= threadTitles[slot][i] != 0;
    }
    titleWidths[slot] = 92; titleOffsets[slot] = 0;
    threadTitleReady[slot] = any;
    Serial.println(command);
    updateOLED();
    return;
  }

  if (command.startsWith("THREADS:")) {
    char states[9]; int active, waiting, overflow, consumed = 0;
    if (sscanf(command.c_str(), "THREADS:%8[0-6],%d,%d,%d%n", states,
               &active, &waiting, &overflow, &consumed) == 4 && strlen(states) == 8 &&
        consumed == command.length() && active >= 0 && active <= 999 &&
        waiting >= 0 && waiting <= active && overflow >= 0 && overflow <= 999) {
      if (strcmp(states, "00000000") == 0) displayedThread = -1;
      strcpy(threadStates, states);
      threadActive = active; threadWaiting = waiting; threadOverflow = overflow;
      threadFrame = command;
      Serial.println(command);
      updateOLED();
    } else Serial.println("ERR invalid thread frame");
    return;
  }

  if (command.startsWith("TOKEN:")) {
    tokenPercent = constrain(command.substring(6).toInt(), 0, 100);
    quotaKnown = true;
    quotaStale = false;
    lastQuotaAt = millis();

    Serial.print("Token percent: ");
    Serial.println(tokenPercent);
    updateOLED();

    if (currentState == STATE_IDLE && !hasThreads()) {
      tokenBlinkOn = true;
      lastLedFrameAt = 0;
      idleBrightness = 2;
      idleDirection = 1;
      showTokenBreath();
    }

    return;
  }

  if (command == "STALE:0" || command == "STALE:1") {
    quotaStale = command == "STALE:1";
    if (!quotaStale) lastQuotaAt = millis();
    Serial.println(command);
    updateOLED();
    return;
  }

  if (command.startsWith("BRIGHTNESS:")) {
    brightnessPercent = constrain(command.substring(11).toInt(), 0, 100);
    setDeviceBrightness();
    Serial.print("BRIGHTNESS:");
    Serial.println(brightnessPercent);
    return;
  }

  if (command == "PING") {
    Serial.println("PONG:AGENTCORE-LIGHT-V3");
    return;
  }

  if (command == "STATUS") {
    Serial.print("STATUS:");
    Serial.print(getStateName());
    Serial.print(",TOKEN:");
    Serial.print(tokenPercent);
    Serial.print(",BRIGHTNESS:");
    Serial.print(brightnessPercent);
    Serial.print(",FW:MAC4,");
    Serial.println(threadFrame);
    return;
  }

  // v1 control-center aliases. v3 has no buzzer, so these are accepted as no-ops.
  if (command == "BUZZER:ON" || command == "BUZZER:OFF" ||
      command.startsWith("BUZZER_VOLUME:") || command.startsWith("SOUND:") ||
      command.startsWith("BEEP")) {
    Serial.print("IGNORED:");
    Serial.println(command);
    return;
  }

  if (command == "IDLE") {
    setState(STATE_IDLE);
  } else if (command == "THINKING") {
    setState(STATE_THINKING);
  } else if (command == "WRITING") {
    setState(STATE_WRITING);
  } else if (command == "RUNNING") {
    setState(STATE_RUNNING);
  } else if (command == "DONE") {
    setState(STATE_DONE);
  } else if (command == "ERROR") {
    setState(STATE_ERROR);
  } else if (command == "NEED_CONFIRM") {
    setState(STATE_NEED_CONFIRM);
  } else if (command == "AI") {
    setState(STATE_WRITING);
  } else if (command == "BUSY") {
    setState(STATE_RUNNING);
  } else if (command == "SUCCESS") {
    setState(STATE_DONE);
  } else if (command == "WAIT_CONFIRM" || command == "CONFIRM" || command == "WAITING" || command == "WAIT") {
    setState(STATE_NEED_CONFIRM);
  } else if (command == "OFF") {
    setState(STATE_OFF);
  } else {
    Serial.print("Unknown command: ");
    Serial.println(command);
    return;
  }

  Serial.print("State changed to: ");
  Serial.println(command);
}

void setState(AgentState newState) {
  currentState = newState;
  stateStartedAt = millis();
  lastLedFrameAt = 0;

  idleBrightness = 2;
  idleDirection = 1;
  tokenBlinkOn = true;
  rotatingPos = 0;
  writingPos = 0;
  pulseStep = 0;
  alertPhaseBlue = true;

  setDeviceBrightness();
  if (!hasThreads() || currentState == STATE_OFF) {
    pixels.clear();
    pixels.show();
  }

  if (currentState == STATE_IDLE && !hasThreads()) {
    showTokenBreath();
  }

  updateOLED();
}

void effectIdle() {
  const unsigned long intervalMs = tokenPercent < 10 ? 450 : 45;
  if (!ledFrameDue(intervalMs)) {
    return;
  }

  if (tokenPercent < 10) {
    tokenBlinkOn = !tokenBlinkOn;
    if ((millis() / 1200) % 2 == 0) {
      alertPhaseBlue = true;
    } else {
      alertPhaseBlue = false;
    }
  } else {
    idleBrightness += idleDirection;
    if (idleBrightness >= 10) {
      idleBrightness = 10;
      idleDirection = -1;
    } else if (idleBrightness <= 2) {
      idleBrightness = 2;
      idleDirection = 1;
    }
  }

  showTokenBreath();
}

void effectThinking() {
  const uint8_t intervalPattern[] = {72, 88, 110, 82, 95, 75, 120, 90};
  const unsigned long intervalMs = intervalPattern[pulseStep % 8];
  if (!ledFrameDue(intervalMs)) {
    return;
  }

  setDeviceBrightness();
  pixels.clear();
  pixels.setPixelColor(rotatingPos, pixels.Color(80, 20, 120));
  pixels.setPixelColor((rotatingPos + LED_COUNT - 1) % LED_COUNT, pixels.Color(30, 6, 50));
  pixels.setPixelColor((rotatingPos + LED_COUNT - 2) % LED_COUNT, pixels.Color(12, 2, 20));
  pixels.show();

  rotatingPos = (rotatingPos + 1) % LED_COUNT;
  pulseStep++;
}

void effectWriting() {
  const unsigned long intervalMs = 55;
  if (!ledFrameDue(intervalMs)) {
    return;
  }

  setDeviceBrightness();
  pixels.clear();

  int p1 = writingPos % LED_COUNT;
  int p2 = (writingPos + 3) % LED_COUNT;
  int p3 = (writingPos + 6) % LED_COUNT;

  pixels.setPixelColor(p1, pixels.Color(10, 95, 110));
  pixels.setPixelColor((p1 + LED_COUNT - 1) % LED_COUNT, pixels.Color(4, 35, 55));
  pixels.setPixelColor(p2, pixels.Color(8, 70, 90));
  pixels.setPixelColor((p2 + LED_COUNT - 1) % LED_COUNT, pixels.Color(3, 28, 45));
  pixels.setPixelColor(p3, pixels.Color(6, 55, 75));
  pixels.setPixelColor((p3 + LED_COUNT - 1) % LED_COUNT, pixels.Color(2, 18, 28));

  pixels.show();
  writingPos = (writingPos + 1) % LED_COUNT;
}

void effectRunning() {
  const unsigned long intervalMs = 34;
  if (!ledFrameDue(intervalMs)) {
    return;
  }

  setDeviceBrightness();
  pixels.clear();
  int p1 = rotatingPos;
  int p2 = (rotatingPos + 4) % LED_COUNT;
  pixels.setPixelColor(p1, pixels.Color(125, 45, 0));
  pixels.setPixelColor((p1 + LED_COUNT - 1) % LED_COUNT, pixels.Color(40, 8, 0));
  pixels.setPixelColor(p2, pixels.Color(95, 30, 0));
  pixels.setPixelColor((p2 + LED_COUNT - 1) % LED_COUNT, pixels.Color(28, 4, 0));
  pixels.show();

  rotatingPos = (rotatingPos + 1) % LED_COUNT;
}

void effectDone() {
  const unsigned long intervalMs = 70;
  if (!ledFrameDue(intervalMs)) {
    return;
  }

  unsigned long elapsed = millis() - stateStartedAt;
  if (elapsed >= 10000UL) {
    setState(STATE_IDLE);
    return;
  }

  setDeviceBrightness();
  pixels.clear();

  int center = (elapsed / 220) % LED_COUNT;
  int radius = (elapsed / 140) % 4;
  for (int d = 0; d <= radius; d++) {
    uint8_t g = (d == 0) ? 90 : (d == 1 ? 55 : (d == 2 ? 28 : 12));
    uint8_t b = (d == 0) ? 60 : (d == 1 ? 34 : (d == 2 ? 18 : 8));
    pixels.setPixelColor((center + d) % LED_COUNT, pixels.Color(0, g, b));
    pixels.setPixelColor((center + LED_COUNT - d) % LED_COUNT, pixels.Color(0, g, b));
  }

  pixels.show();
}

void effectError() {
  const unsigned long intervalMs = 55 + random(0, 100);
  if (!ledFrameDue(intervalMs)) {
    return;
  }

  setDeviceBrightness();
  pixels.clear();
  int dice = random(0, 100);
  if (dice < 12) {
    fillColor(160, 0, 0);
  } else if (dice < 70) {
    int idx = random(0, LED_COUNT);
    pixels.setPixelColor(idx, pixels.Color(120, 0, 0));
    if (random(0, 100) < 45) {
      pixels.setPixelColor((idx + 1) % LED_COUNT, pixels.Color(45, 0, 0));
    }
  } else {
    for (int i = 0; i < LED_COUNT; i++) {
      if (random(0, 100) < 35) {
        pixels.setPixelColor(i, pixels.Color(70, 0, 0));
      }
    }
  }
  pixels.show();
}

void effectNeedConfirm() {
  const unsigned long intervalMs = 60;
  if (!ledFrameDue(intervalMs)) {
    return;
  }

  unsigned long phase = (millis() - stateStartedAt) % 1400UL;
  bool on = (phase < 180UL) || (phase >= 360UL && phase < 540UL);

  setDeviceBrightness();
  pixels.clear();
  if (on) {
    fillColor(80, 80, 80);
  }
  pixels.show();
}

void effectOff() {
  if (!ledFrameDue(250)) {
    return;
  }
  pixels.clear();
  pixels.show();
}

void setDeviceBrightness() {
  // v3 LEDs are physically brighter than the v1 indicators. Cap the actual
  // NeoPixel driver at 50%, while keeping the web control range at 0..100.
  pixels.setBrightness((uint8_t)map(brightnessPercent, 0, 100, 0, MAX_HARDWARE_BRIGHTNESS));
}

bool ledFrameDue(unsigned long intervalMs) {
  unsigned long now = millis();
  if (now - lastLedFrameAt < intervalMs) {
    return false;
  }

  lastLedFrameAt = now;
  return true;
}

void fillColor(uint8_t r, uint8_t g, uint8_t b) {
  for (int i = 0; i < LED_COUNT; i++) {
    pixels.setPixelColor(i, pixels.Color(r, g, b));
  }
}

const char *getStateName() {
  switch (currentState) {
    case STATE_IDLE:
      return "IDLE";
    case STATE_THINKING:
      return "THINKING";
    case STATE_WRITING:
      return "WRITING";
    case STATE_RUNNING:
      return "RUNNING";
    case STATE_DONE:
      return "DONE";
    case STATE_ERROR:
      return "ERROR";
    case STATE_NEED_CONFIRM:
      return "NEED_CONFIRM";
    case STATE_OFF:
      return "OFF";
  }

  return "UNKNOWN";
}

const char *getShortStateName() {
  switch (currentState) {
    case STATE_IDLE:
      return "IDLE";
    case STATE_THINKING:
      return "THINK";
    case STATE_WRITING:
      return "WRITE";
    case STATE_RUNNING:
      return "RUN";
    case STATE_DONE:
      return "DONE";
    case STATE_ERROR:
      return "ERROR";
    case STATE_NEED_CONFIRM:
      return "CONFIRM";
  }

  return "UNKNOWN";
}

const char *getDisplayedStateName() {
  if (displayedThread < 0 || !hasThreads()) return getShortStateName();
  switch (threadStates[displayedThread]) {
    case '1': return "THINK";
    case '2': return "WRITE";
    case '3': return "RUN";
    case '4': return "DONE";
    case '5': return "ERROR";
    case '6': return "CONFIRM";
    default: return getShortStateName();
  }
}

void updateOLEDAnimation() {
  static unsigned long lastScrollAt = 0;
  static int lastDisplayedThread = -1;
  static char lastDisplayedState = '0';
  char displayedState = displayedThread >= 0 ? threadStates[displayedThread] : '0';
  bool offline = millis() - lastHostAt > 20000UL;
  bool stale = quotaStale || !quotaKnown || millis() - lastQuotaAt > 900000UL;
  bool scrollChanged = false;
  if (!offline && currentState != STATE_OFF && displayedThread >= 0 && hasThreads() &&
      threadTitleReady[displayedThread] && titleWidths[displayedThread] > 92 && millis() - lastScrollAt >= 50UL) {
    lastScrollAt = millis();
    int slot = displayedThread;
    if (titleHolds[slot] > 0) titleHolds[slot]--;
    else {
      if (titleOffsets[slot] >= titleWidths[slot] - 92) {
        titleOffsets[slot] = 0; titleHolds[slot] = 10;
      } else {
        titleOffsets[slot]++;
        if (titleOffsets[slot] == titleWidths[slot] - 92) titleHolds[slot] = 14;
      }
      scrollChanged = true;
    }
  }
  if (scrollChanged || offline != lastOffline || stale != lastStale ||
      displayedThread != lastDisplayedThread || displayedState != lastDisplayedState) {
    lastDisplayedThread = displayedThread;
    lastDisplayedState = displayedState;
    lastOffline = offline;
    lastStale = stale;
    updateOLED();
  }
}

void updateOLED() {
  if (!oledReady) {
    return;
  }
  if (currentState == STATE_OFF) {
    display.clearDisplay();
    display.display();
    return;
  }

  const int safeX = 18;
  const int safeW = 92;
  const int barW = 80;
  const int barH = 6;
  const int centerX = safeX + safeW / 2;
  const char *stateText = getDisplayedStateName();
  int16_t textX;
  int16_t textY;
  uint16_t textW;
  uint16_t textH;
  char tokenText[16];

  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  display.setTextSize(1);
  bool offline = millis() - lastHostAt > 20000UL;
  bool showingThread = hasThreads() && displayedThread >= 0 && threadStates[displayedThread] != '0';
  if (!offline && showingThread && threadTitleReady[displayedThread]) {
    int stride = (titleWidths[displayedThread] + 7) / 8;
    for (int y = 0; y < 14; y++) {
      for (int x = 0; x < 92; x++) {
        int sourceX = titleOffsets[displayedThread] + x;
        if (threadTitles[displayedThread][y*stride + sourceX/8] & (0x80 >> (sourceX%8)))
          display.drawPixel(safeX+x, 1+y, SSD1306_WHITE);
      }
    }
  } else {
    char fallback[16];
    snprintf(fallback, sizeof(fallback), "Thread %d", displayedThread + 1);
    const char *title = offline ? "Host offline" : (showingThread ? fallback : "Codex");
    display.getTextBounds(title, 0, 0, &textX, &textY, &textW, &textH);
    display.setCursor(centerX - textW / 2, 3);
    display.print(title);
  }

  display.setTextSize(2);
  display.getTextBounds(stateText, 0, 0, &textX, &textY, &textW, &textH);
  display.setCursor(centerX - textW / 2, 18);
  display.print(stateText);

  if (quotaKnown) {
    bool stale = quotaStale || millis() - lastQuotaAt > 900000UL;
    snprintf(tokenText, sizeof(tokenText), "Week %d%%%s", tokenPercent, stale ? " *" : "");
  } else {
    snprintf(tokenText, sizeof(tokenText), "Week --%%");
  }
  display.setTextSize(1);
  display.getTextBounds(tokenText, 0, 0, &textX, &textY, &textW, &textH);
  display.setCursor(centerX - textW / 2, 42);
  display.print(tokenText);

  int barX = safeX + (safeW - barW) / 2;
  int barY = 56;
  int barWidth = map(tokenPercent, 0, 100, 0, barW);
  display.drawRect(barX, barY, barW, barH, SSD1306_WHITE);
  if (barWidth > 0) {
    display.fillRect(barX, barY, barWidth, barH, SSD1306_WHITE);
  }

  display.display();
}

void showTokenBreath() {
  pixels.clear();

  if (tokenPercent < 10) {
    int alertBrightness = map(brightnessPercent, 0, 100, 0, 32);
    pixels.setBrightness((uint8_t)alertBrightness);
    if (tokenBlinkOn) {
      if (alertPhaseBlue) {
        fillColor(0, 18, 55);
      } else {
        fillColor(45, 0, 0);
      }
    }

    pixels.show();
    return;
  }

  // Keep a useful PWM range at low web values. The old integer-first scaling
  // rounded most frames to zero at 8%, which made the breathing effect flicker.
  int idlePwm = map(idleBrightness, 2, 10, 12, MAX_HARDWARE_BRIGHTNESS);
  idlePwm = (idlePwm * brightnessPercent) / 100;
  pixels.setBrightness((uint8_t)constrain(idlePwm, 0, MAX_HARDWARE_BRIGHTNESS));
  int ledCountToShow = (tokenPercent * LED_COUNT + 99) / 100;
  ledCountToShow = constrain(ledCountToShow, 1, LED_COUNT);

  for (int i = 0; i < ledCountToShow; i++) {
    pixels.setPixelColor(i, pixels.Color(0, 18, 60));
  }

  pixels.show();
}
