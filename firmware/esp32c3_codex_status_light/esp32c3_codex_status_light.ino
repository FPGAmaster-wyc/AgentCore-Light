#include <Adafruit_NeoPixel.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define LED_PIN 4
#define LED_COUNT 8
#define LED_BRIGHTNESS 10

#define BUZZER_PIN 3
#define BUZZER_ACTIVE_LOW 1
// If your buzzer is passive (or you want softer sound), keep PWM enabled.
// For an active buzzer, PWM still works but behavior depends on the module.
#define BUZZER_USE_PWM 0

#define BUZZER_TONE_HZ 2200
// 0-255 (8-bit duty). Lower = quieter (for passive buzzers).
#define BUZZER_DUTY 10
#define BUZZER_BEEP_ON_MS 70
#define BUZZER_BEEP_OFF_MS 120
#define BUZZER_BEEP_TIMES 3

#define OLED_SDA 8
#define OLED_SCL 9
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_RESET -1
#define OLED_ADDRESS 0x3C

Adafruit_NeoPixel pixels(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800);
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

enum AgentState {
  STATE_IDLE,
  STATE_THINKING,
  STATE_WRITING,
  STATE_RUNNING,
  STATE_DONE,
  STATE_ERROR,
  STATE_NEED_CONFIRM
};

AgentState currentState = STATE_IDLE;

String serialBuffer;
bool oledReady = false;

unsigned long stateStartedAt = 0;
unsigned long lastLedFrameAt = 0;
unsigned long lastOledFrameAt = 0;

int tokenPercent = 100;
int idleBrightness = 2;
int idleDirection = 1;
bool tokenBlinkOn = true;
int rotatingPos = 0;
int writingPos = 0;
int pulseStep = 0;
bool alertPhaseBlue = true;
int oledSpinner = 0;

AgentState previousState = STATE_IDLE;

bool doneBeepArmed = false;
bool doneBeepOn = false;
int doneBeepCount = 0;
unsigned long doneBeepNextAt = 0;

#if BUZZER_USE_PWM
static const int kBuzzerPwmChannel = 0;
static const int kBuzzerPwmResolution = 8;
#endif

void buzzerInit() {
  pinMode(BUZZER_PIN, OUTPUT);

#if BUZZER_USE_PWM
  // Keep duty at 0 until needed.
  ledcSetup(kBuzzerPwmChannel, BUZZER_TONE_HZ, kBuzzerPwmResolution);
  ledcAttachPin(BUZZER_PIN, kBuzzerPwmChannel);
  ledcWrite(kBuzzerPwmChannel, 0);
#else
  digitalWrite(BUZZER_PIN, BUZZER_ACTIVE_LOW ? HIGH : LOW);
#endif
}

void buzzerWrite(bool on) {
#if BUZZER_USE_PWM
  ledcWrite(kBuzzerPwmChannel, on ? BUZZER_DUTY : 0);
#else
  bool level = on ? (BUZZER_ACTIVE_LOW ? LOW : HIGH) : (BUZZER_ACTIVE_LOW ? HIGH : LOW);
  digitalWrite(BUZZER_PIN, level);
#endif
}

void startDoneBeepSequence() {
  doneBeepArmed = true;
  doneBeepOn = false;
  doneBeepCount = 0;
  doneBeepNextAt = 0;
  buzzerWrite(false);
}

void updateBuzzer() {
  if (!doneBeepArmed) {
    return;
  }

  unsigned long now = millis();
  if (doneBeepNextAt != 0 && now < doneBeepNextAt) {
    return;
  }

  if (!doneBeepOn) {
    if (doneBeepCount >= BUZZER_BEEP_TIMES) {
      doneBeepArmed = false;
      buzzerWrite(false);
      return;
    }

    doneBeepOn = true;
    buzzerWrite(true);
    doneBeepNextAt = now + BUZZER_BEEP_ON_MS;
    return;
  }

  doneBeepOn = false;
  doneBeepCount++;
  buzzerWrite(false);
  doneBeepNextAt = now + BUZZER_BEEP_OFF_MS;
}

void setup() {
  Serial.begin(115200);
  serialBuffer.reserve(32);

  pixels.begin();
  pixels.setBrightness(LED_BRIGHTNESS);
  pixels.clear();
  pixels.show();

  Wire.begin(OLED_SDA, OLED_SCL);
  oledReady = display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDRESS);
  if (!oledReady) {
    Serial.println("OLED init failed. WS2812 will continue running.");
  } else {
    display.setRotation(2);
    display.ssd1306_command(SSD1306_SETCONTRAST);
    display.ssd1306_command(255);
    display.clearDisplay();
    display.display();
  }

  setState(STATE_IDLE);
  buzzerInit();
  Serial.println("ESP32-C3 AI Agent status light ready.");
  Serial.println("Commands: IDLE, THINKING, WRITING, RUNNING, DONE, ERROR, NEED_CONFIRM, TOKEN:x");
}

void loop() {
  readSerialCommands();
  updateBuzzer();

  switch (currentState) {
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
  }

  updateOLEDAnimation();
}

void readSerialCommands() {
  while (Serial.available() > 0) {
    char c = Serial.read();

    if (c == '\n' || c == '\r') {
      if (serialBuffer.length() > 0) {
        handleCommand(serialBuffer);
        serialBuffer = "";
      }
    } else if (serialBuffer.length() < 31) {
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

  if (command.startsWith("TOKEN:")) {
    tokenPercent = constrain(command.substring(6).toInt(), 0, 100);

    Serial.print("Token percent: ");
    Serial.println(tokenPercent);
    updateOLED();

    if (currentState == STATE_IDLE) {
      tokenBlinkOn = true;
      lastLedFrameAt = 0;
      idleBrightness = 2;
      idleDirection = 1;
      showTokenBreath();
    }

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
  } else {
    Serial.print("Unknown command: ");
    Serial.println(command);
    return;
  }

  Serial.print("State changed to: ");
  Serial.println(command);
}

void setState(AgentState newState) {
  previousState = currentState;
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

  pixels.setBrightness(LED_BRIGHTNESS);
  pixels.clear();
  pixels.show();

  if (currentState == STATE_DONE && previousState != STATE_DONE) {
    startDoneBeepSequence();
  }

  if (currentState == STATE_IDLE) {
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

  pixels.setBrightness(LED_BRIGHTNESS);
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

  pixels.setBrightness(LED_BRIGHTNESS);
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

  pixels.setBrightness(LED_BRIGHTNESS);
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

  pixels.setBrightness(LED_BRIGHTNESS);
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

  pixels.setBrightness(LED_BRIGHTNESS);
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

  pixels.setBrightness(LED_BRIGHTNESS);
  pixels.clear();
  if (on) {
    fillColor(80, 80, 80);
  }
  pixels.show();
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

void updateOLEDAnimation() {
  unsigned long now = millis();
  if (now - lastOledFrameAt < 250) {
    return;
  }

  lastOledFrameAt = now;
  oledSpinner = (oledSpinner + 1) % 4;
  updateOLED();
}

void updateOLED() {
  if (!oledReady) {
    return;
  }

  const int safeX = 18;
  const int safeW = 92;
  const int barW = 80;
  const int barH = 6;
  const int centerX = safeX + safeW / 2;
  const char *stateText = getShortStateName();
  int16_t textX;
  int16_t textY;
  uint16_t textW;
  uint16_t textH;
  char tokenText[16];

  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  display.setTextSize(1);
  display.getTextBounds("Codex", 0, 0, &textX, &textY, &textW, &textH);
  display.setCursor(centerX - textW / 2, 3);
  display.print("Codex");

  display.setTextSize(2);
  display.getTextBounds(stateText, 0, 0, &textX, &textY, &textW, &textH);
  display.setCursor(centerX - textW / 2, 18);
  display.print(stateText);

  snprintf(tokenText, sizeof(tokenText), "Token %d%%", tokenPercent);
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
    pixels.setBrightness(6);
    if (tokenBlinkOn) {
      if (alertPhaseBlue) {
        pixels.setPixelColor(0, pixels.Color(0, 18, 55));
      } else {
        pixels.setPixelColor(0, pixels.Color(45, 0, 0));
      }
    }

    pixels.show();
    return;
  }

  pixels.setBrightness(idleBrightness);
  int ledCountToShow = (tokenPercent * LED_COUNT + 99) / 100;
  ledCountToShow = constrain(ledCountToShow, 1, LED_COUNT);

  for (int i = 0; i < ledCountToShow; i++) {
    pixels.setPixelColor(i, pixels.Color(0, 18, 60));
  }

  pixels.show();
}
