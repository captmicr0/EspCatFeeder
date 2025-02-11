#include <ESP8266WiFi.h>
#include <WiFiClient.h>
#include <ESPAsyncWebServer.h>
#include <ESPAsyncDNSServer.h>

#define USE_ESP_WIFIMANAGER_NTP true

#include <ESPAsync_WiFiManager.h>

#include <WiFiUdp.h>
#include <NTPClient.h>
#include <time.h>
#include <TZ.h>

#include <EEPROM.h>

// NTP client setup
#define DEFAULT_TIMEZONE TZ_America_New_York
WiFiUDP ntpUDP;
NTPClient timeClient(ntpUDP, "time.nist.gov,pool.ntp.org,time.google.com", 0, 10000); // Time offset will be set dynamically, update every 10s

// Define the times to run in 24-hour format (HH:MM)
#define MAX_SCHEDULED_TIMES 256
String scheduledTimes[MAX_SCHEDULED_TIMES];
int numTimes = 0;

// Web server setup
AsyncWebServer webServer(80);
AsyncDNSServer dnsServer;

// pages
String my404Page = "<html><head><title>Cat Feeder</title></head><body><h2>Error, page not found! <a href='/'>Go back to main page!</a></h2></body></html>";
#include "HTML_minified.h"

// feeder functions
#define LED_PIN LED_BUILTIN
#define MOTOR_PIN D1
#define SENSOR_PIN D7
unsigned long feedStartTime = 0;  // store the start time for feeding
unsigned long feedingState = 0;        // state to track feeding

unsigned long portionsLeftToFeed = 0;        // how many portions are left to feed

// WebSerial
//#define EnableWebSerial

#ifdef EnableWebSerial
#include <WebSerial.h>
bool WebSerialActive = 0;
#define BothPrintLn(x) { Serial.println(x); if (WebSerialActive) WebSerial.println(x); }
#define BothPrint(x) { Serial.print(x); if (WebSerialActive) WebSerial.print(x); }
#else
#define BothPrintLn(x) { Serial.println(x); }
#define BothPrint(x) { Serial.print(x); }
#endif

// ElegantOTA
#define EnableElegantOTA //comment out to remove ElegantOTA

#ifdef EnableElegantOTA
#include <ElegantOTA.h>
#endif

// feeder initialization. put into known state.
void feedInit()
{
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);  // turn LED off
  pinMode(MOTOR_PIN, OUTPUT);
  pinMode(SENSOR_PIN, INPUT);

  // put feeder into known state
  digitalWrite(MOTOR_PIN, HIGH); // turn on motor
  digitalWrite(LED_PIN, LOW); // turn LED on
  while (digitalRead(SENSOR_PIN) != HIGH) delay(10); // wait for sensor to activate
  digitalWrite(MOTOR_PIN, LOW); // turn off motor
  digitalWrite(LED_PIN, HIGH);  // turn LED off
}

void feedPortionBlocking()
{
  digitalWrite(MOTOR_PIN, HIGH); // turn on motor
  digitalWrite(LED_PIN, LOW); // turn LED on
  while (digitalRead(SENSOR_PIN) == HIGH) delay(10); // wait for sensor to deativate
  while (digitalRead(SENSOR_PIN) != HIGH) delay(10); // wait for sensor to activate
  digitalWrite(MOTOR_PIN, LOW); // turn off motor
  digitalWrite(LED_PIN, HIGH);  // turn LED off
}

void feedPortionNonBlockingLoop()
{
  if (portionsLeftToFeed > 0)
  {
    if (feedingState == 0) {
      BothPrintLn("Feeding 1 portion");
      feedingState = 1;
    } else if (feedingState == 1) {
      digitalWrite(MOTOR_PIN, HIGH); // turn on motor
      digitalWrite(LED_PIN, LOW); // turn LED on
      feedingState = 2; // start step 2
    } else if (feedingState == 2) {
    if (digitalRead(SENSOR_PIN) != HIGH) feedingState = 3; // if sensor is off, start step 3
    } else if (feedingState == 3) {
    if (digitalRead(SENSOR_PIN) == HIGH) feedingState = 4; // if sensor is on, start step 4
    } else if (feedingState == 4) {
      digitalWrite(MOTOR_PIN, LOW); // turn off motor
      digitalWrite(LED_PIN, HIGH);  // turn LED off
      portionsLeftToFeed = portionsLeftToFeed - 1;
      feedingState = 0;
    }
  }
}

bool feedPortion(unsigned long count)
{
  BothPrintLn("Adding " + String(count) + " portions to portionsLeftToFeed");
  portionsLeftToFeed = portionsLeftToFeed + count;
  return true;
}

void syncTo10SecondStart() {
  while (timeClient.getMillis() % 10000 != 0) {
    delay(1);
  }
}

// Function that will run at specific times
void runAtTime(String scheduledTime) {
  syncToSecondStart();
  BothPrintLn("Running at scheduled time: " + scheduledTime);
  feedPortion(scheduledTime.substring(scheduledTime.indexOf('-') + 1).toInt());
}

// Function to compare current time with scheduled times
void checkScheduledTimes(String currentTime) {
  for (int i = 0; i < numTimes; i++) {
    String checkTime = scheduledTimes[i].substring(0, scheduledTimes[i].indexOf('-'));
    if (currentTime == checkTime) {
      runAtTime(scheduledTimes[i]);
      delay(62000); // Delay to prevent the task from running multiple times in the same minute
    }
  }
}

// Function to get the current time with correct timezone
String getCurrentTime() {
  time_t now;
  struct tm timeInfo;
  if (!getLocalTime(&timeInfo)) {
    BothPrintLn("Failed to obtain time");
    return "Failed to obtain time";
  }

  char timeStr[6];
  strftime(timeStr, sizeof(timeStr), "%H:%M", &timeInfo); // Format time as HH:MM
  return String(timeStr);
}

// Function to get the current timezone
String getCurrentTimezone() {
  char* tz = getenv("TZ"); // Get the current timezone environment variable
  if (tz != nullptr) {
    return String(tz); // Return the timezone as a String
  } else {
    return "Timezone not set"; // Return a message if timezone is not set
  }
}

// Function to add a time to the list
bool addTime(String timeToAdd) {
  if (numTimes < (MAX_SCHEDULED_TIMES-1)) {
    scheduledTimes[numTimes] = timeToAdd;
    numTimes++;
    BothPrintLn("Time added: " + timeToAdd);
    return true;
  } else {
    BothPrintLn("Error: List is full.");
    return false;
  }
}

// Function to remove a time from the list
bool removeTime(String timeToRemove) {
  for (int i = 0; i < numTimes; i++) {
    if (scheduledTimes[i] == timeToRemove) {
      // Shift the remaining times down by one
      for (int j = i; j < numTimes - 1; j++) {
        scheduledTimes[j] = scheduledTimes[j + 1];
      }
      numTimes--;
      BothPrintLn("Time removed: " + timeToRemove);
      return true;
    }
  }
  BothPrintLn("Error: Time not found.");
  return false;
}

// Function to get the list of scheduled times as a comma-separated string
String getScheduledTimes() {
  String times = "";
  for (int i = 0; i < numTimes; i++) {
    times += scheduledTimes[i];
    if (i < numTimes - 1) {
      times += ","; // Add a comma between times
    }
  }
  return times;
}

void initTimezone(String timezone)
{
  struct timezone tz={0,0};
  struct timeval tv={0,0};
  settimeofday(&tv, &tz);  
  setenv("TZ", timezone.c_str(), 0);
  tzset();
}

// Function to set the timezone dynamically
void setTimezone(String tz) {
  initTimezone(DEFAULT_TIMEZONE);
  // Set the timezone with setenv and tzset
  setenv("TZ", tz.c_str(), 1);  // Convert String to C-string
  tzset();
  configTime(tz.c_str(), "pool.ntp.org", "time.nist.gov");
  BothPrintLn("Timezone set to: " + tz);
  BothPrintLn("Current Time: " + getCurrentTime());
}

void splitTimeStr(String timeStr, byte *hour, byte *minute, byte *count)
{
  int colonIdx = timeStr.indexOf(':');
  int dashIdx = timeStr.indexOf('-');
  *hour = (byte)timeStr.substring(0, colonIdx).toInt();
  *minute = (byte)timeStr.substring(colonIdx + 1, dashIdx).toInt();
  *count = (byte)timeStr.substring(dashIdx + 1).toInt();
}

String buildTimeStr(byte hour, byte minute, byte count)
{
  char timeStr[10]; // Buffer to hold "HH:MM-CC" format string
  memset(&timeStr, 0, 10);
  sprintf(timeStr, "%02d:%02d-%02d", hour, minute, count);
  return String(timeStr);
}

// Function to save scheduleTimes to EEPROM
bool saveTimesToEEPROM()
{
  BothPrintLn("Saving times to EEPROM...");
  EEPROM.begin(sizeof(int) + (sizeof(char) * 128) + sizeof(int) + (MAX_SCHEDULED_TIMES * sizeof(byte) * 3) + 16);
  
  int addr = 0;

  int check_val = 23456;
  EEPROM.put(addr, check_val); addr += sizeof(int);
  BothPrintLn("check_val = " + String(check_val));
  
  String tz = getCurrentTimezone();
  if (tz.length() >= 128) tz = DEFAULT_TIMEZONE;
  char tz_cstr[129]; memset(tz_cstr, 0, 129);
  tz.toCharArray(tz_cstr, 128);
  for (int i = 0; i < 128; i++)
    EEPROM.write(addr + i, tz_cstr[i]);
  BothPrintLn("tz_cstr = " + String(tz_cstr));
  addr += (sizeof(char) * 128);

  EEPROM.put(addr, numTimes); addr += sizeof(int);
  BothPrintLn("numTimes = " + String(numTimes));

  for (int i = 0; i < numTimes; i++) {
    byte h = 0; byte m = 0; byte c = 0;
    splitTimeStr(scheduledTimes[i], &h, &m, &c);
    EEPROM.put(addr, h); addr += sizeof(byte);
    EEPROM.put(addr, m); addr += sizeof(byte);
    EEPROM.put(addr, c); addr += sizeof(byte);
    BothPrintLn("Saved scheduledTimes[" + String(i) + "] = " + scheduledTimes[i]);
  }

  EEPROM.commit();
  EEPROM.end();
  BothPrintLn("Done!");
  return true;
}

// Function to load scheduleTimes from EEPROM
bool loadTimesFromEEPROM()
{
  BothPrintLn("Loading times from EEPROM...");
  EEPROM.begin(sizeof(int) + (sizeof(char) * 128) + sizeof(int) + (MAX_SCHEDULED_TIMES * sizeof(byte) * 3) + 16);
  
  int addr = 0;

  int check_val = 0;
  EEPROM.get(addr, check_val); addr += sizeof(int);
  if (check_val != 23456) {
    BothPrintLn("check_val = " + String(check_val));
    BothPrintLn("INVALID!!! clearing eeprom data!!!");
    for (int i = 0; i < sizeof(int) + (sizeof(char) * 128) + sizeof(int) + (MAX_SCHEDULED_TIMES * sizeof(byte) * 3) + 16; i++) {
      EEPROM.write(addr + i, 0);
    }
    EEPROM.commit();
    EEPROM.end();
    BothPrintLn("Done erasing EEPROM.");
    return false;
  }

  char tz_cstr[129];
  memset(tz_cstr, 0, 129);
  for (int i = 0; i < 128; i++)
    tz_cstr[i] = (char)EEPROM.read(addr + i);
  BothPrintLn("tz_cstr = " + String(tz_cstr));
  if (strlen(tz_cstr) > 0) setTimezone(tz_cstr);
  addr += (sizeof(char) * 128);

  EEPROM.get(addr, numTimes); addr += sizeof(int);
  BothPrintLn("numTimes = " + String(numTimes));

  for (int i = 0; i < numTimes; i++) {
    byte h = 0; byte m = 0; byte c = 0;
    EEPROM.get(addr, h); addr += sizeof(byte);
    EEPROM.get(addr, m); addr += sizeof(byte);
    EEPROM.get(addr, c); addr += sizeof(byte);
    scheduledTimes[i] = buildTimeStr(h, m, c);
    BothPrintLn("Loaded scheduledTimes[" + String(i) + "] = " + scheduledTimes[i]);
  }

  EEPROM.end();
  BothPrintLn("Done!");
  return true;
}

#ifdef EnableElegantOTA
// OTA status debug functions
unsigned long ota_progress_millis = 0;

// Log when OTA has started
void onOTAStart() {
  BothPrintLn("OTA update started!");
}

// Log every 1 second
void onOTAProgress(size_t current, size_t final) {
  if (millis() - ota_progress_millis > 1000) {
    ota_progress_millis = millis();
    BothPrintLn("OTA Progress Current: " + String(current) + " bytes, Final: " + String(final) + "bytes\n");
  }
}

// Log when OTA has finished
void onOTAEnd(bool success) {
  if (success) {
    BothPrintLn("OTA update finished successfully!");
  } else {
    BothPrintLn("There was an error during OTA update!");
  }
}
#endif

void setup()
{
  Serial.begin(115200);
  while (!Serial) delay(10);
  delay(200);

#define HARDCODE_WIFI // uncomment to use hardcoded wifi credentials
#ifdef HARDCODE_WIFI
  #include "WIFI_password.h"
  WiFi.begin(WIFI_NAME, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    BothPrintLn("Connecting to WiFi...");
  }
#else
  ESPAsync_WiFiManager wifiManager(&webServer, &dnsServer, "My-ESP8266");
  wifiManager.autoConnect();

  if (WiFi.status() != WL_CONNECTED) {
    BothPrintLn(wifiManager.getStatus(WiFi.status()));
    BothPrintLn("Can't connect! Enter WiFi config mode...");
    BothPrintLn("Restart...");
    ESP.reset();
  }
#endif

  BothPrintLn("Connected to WiFi.");
  BothPrintLn("IP address: " + WiFi.localIP().toString());

  setTimezone(DEFAULT_TIMEZONE);
  timeClient.begin();

  webServer.onNotFound([](AsyncWebServerRequest *request) {
    request->send(404, "text/html", my404Page);
  });

  webServer.on("/", HTTP_GET, [](AsyncWebServerRequest *request){
    request->send_P(200, "text/html", data_page_html);
  });
  webServer.on("/index.html", HTTP_GET, [](AsyncWebServerRequest *request){
    request->send_P(200, "text/html", data_page_html);
  });

  webServer.on("/feedPortion", HTTP_GET, [](AsyncWebServerRequest *request) {
    request->send(200, "text/plain", "feeding portion");
    if (feedPortion(1)) {
      request->send(200, "text/plain", "feeding portion");
    } else {
      request->send(500, "text/plain", "Error: alreadying feeding portion.");
    }
  });

  webServer.on("/addTime", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (request->hasParam("time")) {
      String timeToAdd = request->getParam("time")->value();
      if (addTime(timeToAdd)) {
        request->send(200, "text/plain", "Time added: " + timeToAdd);
        saveTimesToEEPROM();
      } else {
        request->send(500, "text/plain", "Error: List is full.");
      }
    } else {
      request->send(400, "text/plain", "Error: Missing 'time' parameter.");
    }
  });

  webServer.on("/removeTime", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (request->hasParam("time")) {
      String timeToRemove = request->getParam("time")->value();
      if (removeTime(timeToRemove)) {
        request->send(200, "text/plain", "Time removed: " + timeToRemove);
        saveTimesToEEPROM();
      } else {
        request->send(404, "text/plain", "Error: Time not found.");
      }
    } else {
      request->send(400, "text/plain", "Error: Missing 'time' parameter.");
    }
  });

  webServer.on("/getTimes", HTTP_GET, [](AsyncWebServerRequest *request) {
    String times = getScheduledTimes();
    request->send(200, "text/plain", times);
  });
  
  webServer.on("/setTimezone", HTTP_GET, [](AsyncWebServerRequest *request) {
    if (request->hasParam("tz")) {
      String tz = request->getParam("tz")->value();
      setTimezone(tz);
      request->send(200, "text/plain", "Timezone set to: " + tz);
      saveTimesToEEPROM();
    } else {
      request->send(400, "text/plain", "Error: Missing 'tz' parameter.");
    }
  });

  webServer.on("/getTimezone", HTTP_GET, [](AsyncWebServerRequest *request) {
    String tz = getCurrentTimezone();
    request->send(200, "text/plain", tz);
  });

  #ifdef EnableElegantOTA
  ElegantOTA.begin(&webServer);
  ElegantOTA.onStart(onOTAStart);
  ElegantOTA.onProgress(onOTAProgress);
  ElegantOTA.onEnd(onOTAEnd);
  BothPrintLn("ElegantOTA started.");
  #endif

  #ifdef EnableWebSerial
  WebSerial.begin(&webServer);
  BothPrintLn("WebSerial started.");
  #endif

  webServer.begin();
  BothPrintLn("HTTP server started.");

  #ifdef EnableWebSerial
  WebSerialActive = true;
  #endif

  loadTimesFromEEPROM();
  
  BothPrintLn("Feeder initializing...");
  feedInit();
}

const int timeFnInterval = 1000; // interval to run function
unsigned long timeFnPrevTime = 0; // last time function was ran

const int feedFnInterval = 10; // interval to run function
unsigned long feedFnPrevTime = 0; // last time function was ran

void loop()
{
  unsigned long currentMillis = millis();

  if ((currentMillis - timeFnPrevTime) >= timeFnInterval) {
    timeFnPrevTime = currentMillis; // save the last time the function was executed
    timeClient.asyncUpdate();
    checkScheduledTimes(getCurrentTime());
  }

  if ((currentMillis - feedFnPrevTime) >= feedFnInterval) {
    feedFnPrevTime = currentMillis; // save the last time the function was executed
    feedPortionNonBlockingLoop();
  }
  
  #ifdef EnableElegantOTA
  ElegantOTA.loop();
  #endif

  #ifdef EnableWebSerial
  WebSerial.loop();
  #endif
  
  delay(10);
}