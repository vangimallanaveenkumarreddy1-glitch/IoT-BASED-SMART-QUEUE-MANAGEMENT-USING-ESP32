/*
 * IoT-Based Smart Queue Management Using ESP32
 
 * Features:
 * - IR Sensor For People Counting
 * - YOLO Camera Integration
 * - Servo for Gate Control
 * - LCD Display
 * - Web Dashboard to Monitor & Controll
 * - Emergency Response System
 * - Fire Detection & Immediate  Responce
 * - Temperature & Humidity Monitoring
 * 
 * Author: VANGIMALLA NAVEENKUMAR REDDY
 * Date: 10-05-2026
 */

#include <WiFi.h>
#include <WebServer.h>
#include <ESP32Servo.h>
#include <LiquidCrystal_I2C.h>

// ============================================
// WIFI CONFIGURATION
// ============================================
const char* WIFI_SSID = "QLineControl_AP";
const char* WIFI_PASSWORD = "12345678";

// ============================================
// PIN DEFINITIONS
// ============================================
// Servo Motors
#define G1_PIN 13        // Gate 1 
#define G2_PIN 12        // Gate 2 
#define G3_PIN 14        // Gate 3 
#define GV_PIN 27        // VIP Gate

// IR Sensors(For this i took one for example.But actually we need each ir sensor each gate)
#define IR_IN 33         // Entry IR Sensor
#define IR_OUT 32        // Exit IR Sensor

// Push Buttons
#define VIP_BTN 26       // VIP Access Button
#define PANIC_BTN 35     // Panic or Emergency Button

// Sensors
#define FIRE_SEN 34      // Flame Sensor (LOW = Fire Detected)

// Relay Module (Active LOW)
#define FAN_REL 25       // Air Condition control
#define PUMP_REL 4       // Water Pump Control (Fire Fighting)

// Buzzer
#define BUZZ_PIN 18      // Active Buzzer
#define GRND_PIN 19      // Common Ground Pin

// ============================================
// OBJECTS
// ============================================
WebServer server(80);
Servo g1, g2, g3, gV;
LiquidCrystal_I2C lcd(0x27, 16, 2);

// ============================================
// GLOBAL VARIABLES
// ============================================
// Counters (Volatile for Interrupts)
volatile unsigned long ir_in = 0;      // IR entry count
volatile unsigned long ir_out = 0;     // IR exit count

int man_cnt = 0;      // Manual/YOLO count
int yolo_cnt = 0;     // YOLO detected count
int total = 0;        // Total people
int line_length = 0;  // Current queue length

// Threshold Settings
int g1_th = 10;       // Gate 1 threshold (people)
int g2_th = 20;       // Gate 2 threshold
int g3_th = 21;       // Gate 3 threshold
int st1_th = 5;       // Stage 1 threshold (GO SLOW)
int st2_th = 7;       // Stage 2 threshold (BUZZER)
int st3_th = 10;      // Stage 3 threshold (LOCKDOWN)

// System Status
String sys_stat = "Normal";

// Gate States
bool g1o = 0, g2o = 0, g3o = 0, gVo = 0;

// Control Flags
bool auto_mode = 1;
bool manual_mode = 0;
bool gates_locked = 0;

// Emergency Flags
bool vip = 0;
bool panic = 0;
bool fire = 0;
bool emergency = 0;

// Output States
bool buzzer = 0;
bool fan_on = 0;
bool pump_on = 0;

// ============================================
// INTERRUPT HANDLERS
// ============================================
void IRAM_ATTR handleIRIn() {
    ir_in++;
}

void IRAM_ATTR handleIROut() {
    ir_out++;
    if (man_cnt > 0) man_cnt--;
    if (yolo_cnt > 0) yolo_cnt--;
}

// ============================================
// SETUP FUNCTION
// ============================================
void setup() {
    Serial.begin(115200);
    delay(100);
    Serial.println("\n\n=== Smart Queue System Starting ===");
    
    // --- Initialize Servo Motors ---
    g1.attach(G1_PIN);
    g2.attach(G2_PIN);
    g3.attach(G3_PIN);
    gV.attach(GV_PIN);
    
    // Close all gates initially
    g1.write(0);
    g2.write(0);
    g3.write(0);
    gV.write(0);
    Serial.println("✓ Servos Initialized");
    
    // --- Initialize Sensor Pins ---
    pinMode(IR_IN, INPUT_PULLUP);
    pinMode(IR_OUT, INPUT_PULLUP);
    pinMode(VIP_BTN, INPUT_PULLUP);
    pinMode(PANIC_BTN, INPUT_PULLUP);
    pinMode(FIRE_SEN, INPUT_PULLUP);
    Serial.println("✓ Sensors Initialized");
    
    // --- Attach Interrupts ---
    attachInterrupt(digitalPinToInterrupt(IR_IN), handleIRIn, FALLING);
    attachInterrupt(digitalPinToInterrupt(IR_OUT), handleIROut, FALLING);
    Serial.println("✓ Interrupts Attached");
    
    // --- Initialize Outputs ---
    pinMode(FAN_REL, OUTPUT);
    pinMode(PUMP_REL, OUTPUT);
    pinMode(BUZZ_PIN, OUTPUT);
    pinMode(GRND_PIN, OUTPUT);
    
    // Active LOW: HIGH = OFF, LOW = ON
    digitalWrite(FAN_REL, HIGH);
    digitalWrite(PUMP_REL, HIGH);
    digitalWrite(BUZZ_PIN, HIGH);
    digitalWrite(GRND_PIN, HIGH);
    Serial.println("✓ Outputs Initialized");
    
    // --- Setup WiFi Access Point ---
    WiFi.softAP(WIFI_SSID, WIFI_PASSWORD);
    Serial.println("✓ WiFi AP Started: " + String(WIFI_SSID));
    Serial.println("  IP Address: " + WiFi.softAPIP().toString());
    
    // --- Setup Web Server Routes ---
    server.on("/", handleRoot);
    server.on("/status", handleStatus);
    server.on("/control", handleControl);
    server.on("/receive_count", handleReceiveCount);
    server.begin();
    Serial.println("✓ Web Server Started");
    
    // --- Initialize LCD ---
    lcd.init();
    lcd.backlight();
    lcd.clear();
    lcd.print("Q-Line Ready");
    Serial.println("✓ LCD Initialized");
    
    Serial.println("=== System Ready! ===\n");
}

// ============================================
// MAIN LOOP
// ============================================
void loop() {
    // Handle web server requests
    server.handleClient();
    
    // --- Update Counts ---
    line_length = ir_in - ir_out;
    if (line_length < 0) line_length = 0;
    
    total = man_cnt + yolo_cnt;
    if (total < 0) total = 0;
    
    // --- Check Emergency Buttons ---
    checkEmergency();
    
    // --- Check Fire Sensor ---
    checkFire();
    
    // --- VIP Button Handling ---
    handleVIP();
    
    // --- Gate Control Logic ---
    updateGates();
    
    // --- Buzzer Logic ---
    updateBuzzer();
    
    // --- LCD Update ---
    updateLCD();
    
    // --- Serial Debug (Optional) ---
    // Print to Serial Monitor every 2 seconds
    static unsigned long lastDebug = 0;
    if (millis() - lastDebug > 2000) {
        Serial.print("Line: "); Serial.print(line_length);
        Serial.print(" | Total: "); Serial.print(total);
        Serial.print(" | Status: "); Serial.println(sys_stat);
        lastDebug = millis();
    }
    
    delay(50);
}

// ============================================
// EMERGENCY CHECK FUNCTIONS
// ============================================
void checkEmergency() {
    if (digitalRead(PANIC_BTN) == LOW) {
        panic = 1;
        emergency = 1;
        buzzer = 1;
        gates_locked = 1;
        openAllGates();
        sys_stat = "PANIC";
        Serial.println("⚠️ PANIC BUTTON PRESSED!");
    }
}

void checkFire() {
    if (digitalRead(FIRE_SEN) == LOW) {
        fire = 1;
        emergency = 1;
        digitalWrite(PUMP_REL, LOW);  // Turn ON pump
        pump_on = 1;
        openAllGates();
        sys_stat = "FIRE";
        Serial.println("🔥 FIRE DETECTED!");
    }
}

void handleVIP() {
    if (digitalRead(VIP_BTN) == LOW && !vip) {
        vip = 1;
        Serial.println("👑 VIP ACCESS GRANTED");
        openGate(4);
        delay(3000);
        closeGate(4);
        vip = 0;
    }
}

// ============================================
// GATE CONTROL FUNCTIONS
// ============================================
void updateGates() {
    // If emergency, all gates already open
    if (panic || fire || emergency) {
        // Already open
        return;
    }
    
    // If gates locked, close all
    if (gates_locked) {
        closeGate(1);
        closeGate(2);
        closeGate(3);
        return;
    }
    
    // Auto Mode Control
    if (auto_mode && !manual_mode && !vip) {
        if (total >= g1_th) {
            openGate(1);
        } else {
            closeGate(1);
        }
        
        if (total >= g2_th) {
            openGate(2);
        } else {
            closeGate(2);
        }
        
        if (total > g3_th) {
            openGate(3);
        } else {
            closeGate(3);
        }
    }
}

void openGate(int gate) {
    switch(gate) {
        case 1:
            if (!g1o) {
                g1.write(90);
                g1o = 1;
                Serial.println("Gate 1 Opened");
            }
            break;
        case 2:
            if (!g2o) {
                g2.write(90);
                g2o = 1;
                Serial.println("Gate 2 Opened");
            }
            break;
        case 3:
            if (!g3o) {
                g3.write(90);
                g3o = 1;
                Serial.println("Gate 3 Opened");
            }
            break;
        case 4:
            if (!gVo) {
                gV.write(90);
                gVo = 1;
                Serial.println("VIP Gate Opened");
            }
            break;
    }
}

void closeGate(int gate) {
    switch(gate) {
        case 1:
            if (g1o) {
                g1.write(0);
                g1o = 0;
                Serial.println("Gate 1 Closed");
            }
            break;
        case 2:
            if (g2o) {
                g2.write(0);
                g2o = 0;
                Serial.println("Gate 2 Closed");
            }
            break;
        case 3:
            if (g3o) {
                g3.write(0);
                g3o = 0;
                Serial.println("Gate 3 Closed");
            }
            break;
        case 4:
            if (gVo) {
                gV.write(0);
                gVo = 0;
                Serial.println("VIP Gate Closed");
            }
            break;
    }
}

void openAllGates() {
    openGate(1);
    openGate(2);
    openGate(3);
    openGate(4);
}

void closeAllGates() {
    closeGate(1);
    closeGate(2);
    closeGate(3);
    closeGate(4);
}

// ============================================
// QUEUE STAGE LOGIC
// ============================================
void updateBuzzer() {
    // Emergency override
    if (emergency) {
        digitalWrite(BUZZ_PIN, LOW);
        return;
    }
    
    // Check queue stages
    if (line_length >= st3_th) {
        sys_stat = "Stage3";
        gates_locked = 1;
        buzzer = 1;
        digitalWrite(BUZZ_PIN, LOW);
    } 
    else if (line_length >= st2_th) {
        sys_stat = "Stage2";
        gates_locked = 0;
        buzzer = 1;
        digitalWrite(BUZZ_PIN, LOW);
    } 
    else if (line_length >= st1_th) {
        sys_stat = "Stage1";
        gates_locked = 0;
        buzzer = 0;
        digitalWrite(BUZZ_PIN, HIGH);
    } 
    else {
        sys_stat = "Normal";
        gates_locked = 0;
        buzzer = 0;
        digitalWrite(BUZZ_PIN, HIGH);
    }
    
    // Temperature fan control (Auto)
    // Note: Temperature reading would come from DHT11
    // For now, simple logic - implement later
}

// ============================================
// LCD UPDATE
// ============================================
void updateLCD() {
    lcd.clear();
    
    // Line 1: Counts
    lcd.print("M:");
    lcd.print(man_cnt);
    lcd.print(" Y:");
    lcd.print(yolo_cnt);
    
    // Line 2: Total and Status
    lcd.setCursor(0, 1);
    lcd.print("T:");
    lcd.print(total);
    lcd.print(" L:");
    lcd.print(line_length);
    lcd.print(" ");
    lcd.print(sys_stat.substring(0, 6));
}

// ============================================
// WEB SERVER HANDLERS
// ============================================
void handleRoot() {
    String html = R"(
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Q-Line Control</title>
        <style>
            * { box-sizing: border-box; }
            body { font-family: Arial; margin: 20px; background: #f5f5f5; }
            .container { max-width: 500px; margin: auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            h1 { color: #2c3e50; text-align: center; }
            .stats { display: grid; grid-template-columns: repeat(2,1fr); gap: 10px; margin: 20px 0; }
            .stat { padding: 15px; background: #f8f9fa; border-radius: 8px; text-align: center; }
            .stat .label { font-size: 12px; color: #7f8c8d; }
            .stat .value { font-size: 24px; font-weight: bold; color: #2c3e50; }
            .stat .value.green { color: #27ae60; }
            .stat .value.red { color: #e74c3c; }
            .stat .value.orange { color: #f39c12; }
            .btn { padding: 12px 20px; margin: 5px; border: none; border-radius: 5px; color: white; cursor: pointer; font-size: 16px; width: 48%; }
            .btn-green { background: #27ae60; }
            .btn-red { background: #e74c3c; }
            .btn-blue { background: #3498db; }
            .btn-orange { background: #f39c12; }
            .btn:hover { opacity: 0.8; }
            .btn-group { display: flex; flex-wrap: wrap; gap: 5px; margin: 10px 0; }
            .status-badge { display: inline-block; padding: 5px 15px; border-radius: 20px; color: white; font-weight: bold; }
            .badge-normal { background: #27ae60; }
            .badge-stage1 { background: #f39c12; }
            .badge-stage2 { background: #e67e22; }
            .badge-stage3 { background: #e74c3c; }
            .badge-panic { background: #8e44ad; }
            .badge-fire { background: #c0392b; animation: blink 0.5s infinite; }
            @keyframes blink { 0% { opacity: 1; } 50% { opacity: 0.3; } 100% { opacity: 1; } }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚦 Q-Line Control</h1>
            
            <div class="stats">
                <div class="stat">
                    <div class="label">Manual Count</div>
                    <div class="value" id="manual">0</div>
                </div>
                <div class="stat">
                    <div class="label">YOLO Count</div>
                    <div class="value" id="yolo">0</div>
                </div>
                <div class="stat">
                    <div class="label">Total People</div>
                    <div class="value green" id="total">0</div>
                </div>
                <div class="stat">
                    <div class="label">Queue Length</div>
                    <div class="value orange" id="line">0</div>
                </div>
            </div>
            
            <div style="text-align: center; margin: 15px 0;">
                <span class="status-badge badge-normal" id="statusBadge">Normal</span>
            </div>
            
            <div class="btn-group">
                <button class="btn btn-green" onclick="openAll()">🔓 Open All</button>
                <button class="btn btn-red" onclick="closeAll()">🔒 Close All</button>
            </div>
            
            <div class="btn-group">
                <button class="btn btn-blue" onclick="resetEmergency()">🔄 Reset</button>
                <button class="btn btn-orange" onclick="testBuzzer()">🔔 Test Buzzer</button>
            </div>
            
            <div style="margin-top: 15px; font-size: 12px; color: #7f8c8d; text-align: center;">
                <span id="uptime">Connected</span>
            </div>
        </div>
        
        <script>
            // Update stats every second
            async function updateStats() {
                try {
                    const response = await fetch('/status');
                    const data = await response.json();
                    
                    document.getElementById('manual').textContent = data.m;
                    document.getElementById('yolo').textContent = data.y;
                    document.getElementById('total').textContent = data.t;
                    document.getElementById('line').textContent = data.l;
                    
                    // Update status badge
                    const badge = document.getElementById('statusBadge');
                    const status = data.s || 'Normal';
                    badge.textContent = status;
                    badge.className = 'status-badge';
                    
                    switch(status) {
                        case 'Normal': badge.classList.add('badge-normal'); break;
                        case 'Stage1': badge.classList.add('badge-stage1'); break;
                        case 'Stage2': badge.classList.add('badge-stage2'); break;
                        case 'Stage3': badge.classList.add('badge-stage3'); break;
                        case 'PANIC': badge.classList.add('badge-panic'); break;
                        case 'FIRE': badge.classList.add('badge-fire'); break;
                        default: badge.classList.add('badge-normal');
                    }
                } catch(e) {
                    console.error('Update error:', e);
                }
            }
            
            function openAll() {
                fetch('/control?cmd=open_all');
            }
            
            function closeAll() {
                fetch('/control?cmd=close_all');
            }
            
            function resetEmergency() {
                fetch('/control?cmd=reset');
            }
            
            function testBuzzer() {
                fetch('/control?cmd=buzzer_on');
                setTimeout(() => fetch('/control?cmd=buzzer_off'), 2000);
            }
            
            setInterval(updateStats, 1000);
            updateStats();
        </script>
    </body>
    </html>
    )";
    
    server.send(200, "text/html", html);
}

void handleStatus() {
    String json = "{";
    json += "\"m\":" + String(man_cnt) + ",";
    json += "\"y\":" + String(yolo_cnt) + ",";
    json += "\"t\":" + String(total) + ",";
    json += "\"l\":" + String(line_length) + ",";
    json += "\"s\":\"" + sys_stat + "\"";
    json += "}";
    server.send(200, "application/json", json);
}

void handleControl() {
    String cmd = server.arg("cmd");
    
    if (cmd == "open_all") {
        openAllGates();
        server.send(200, "text/plain", "OK");
    } 
    else if (cmd == "close_all") {
        closeAllGates();
        server.send(200, "text/plain", "OK");
    } 
    else if (cmd == "reset") {
        panic = 0;
        fire = 0;
        emergency = 0;
        gates_locked = 0;
        digitalWrite(PUMP_REL, HIGH);
        digitalWrite(BUZZ_PIN, HIGH);
        sys_stat = "Normal";
        server.send(200, "text/plain", "OK");
    } 
    else if (cmd == "buzzer_on") {
        digitalWrite(BUZZ_PIN, LOW);
        server.send(200, "text/plain", "OK");
    } 
    else if (cmd == "buzzer_off") {
        digitalWrite(BUZZ_PIN, HIGH);
        server.send(200, "text/plain", "OK");
    } 
    else {
        server.send(400, "text/plain", "Invalid command");
    }
}

void handleReceiveCount() {
    if (server.hasArg("yolo_count")) {
        yolo_cnt = server.arg("yolo_count").toInt();
        Serial.println("YOLO Count updated: " + String(yolo_cnt));
    }
    server.send(200, "text/plain", "OK");
}









