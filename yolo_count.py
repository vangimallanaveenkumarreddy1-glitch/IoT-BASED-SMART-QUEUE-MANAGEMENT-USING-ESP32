"""
AI-Powered People Counter for Smart Queue Management System
ESP32 Integration with YOLO Object Detection

Author: VANGIMALLA NAVEENKUMAR REDDY
Date: 10-05-2026

Features:
- Real-time people detection using YOLOv8
- ESP32-CAM video stream processing
- Web dashboard with live video feed
- ESP32 communication via HTTP API
- Automatic people counting with confidence threshold
- Multi-camera support (ESP32-CAM / Webcam)

Dependencies:
- Python 3.8+
- OpenCV
- Ultralytics YOLO
- Flask
- Requests
- NumPy
"""

import cv2
import numpy as np
import requests
import time
import threading
import logging
import sys
from datetime import datetime
from flask import Flask, Response, jsonify, render_template_string, request
from ultralytics import YOLO
import urllib.request
import os

# ============================================
# CONFIGURATION
# ============================================

# ESP32 Configuration
ESP32_IP = "192.168.4.1"           # ESP32 Access Point IP
ESP32_PORT = 80                    # ESP32 Web Server Port
ESP32_URL = f"http://{ESP32_IP}:{ESP32_PORT}"

# Camera Configuration
CAM_IP = "192.168.4.100"           # ESP32-CAM IP Address
CAM_PORT = "81"                    # ESP32-CAM Stream Port
CAM_URL = f"http://{CAM_IP}:{CAM_PORT}/stream"

# YOLO Configuration
MODEL_NAME = "yolov8n.pt"          # YOLO model (nano version for speed)
CONFIDENCE_THRESHOLD = 0.4         # Minimum confidence for detection
CLASS_ID_PERSON = 0                # COCO class ID for person
IMAGE_SIZE = 320                   # Inference image size (smaller = faster)
FRAME_SKIP = 2                     # Process every N-th frame

# Flask Configuration
FLASK_PORT = 5000                  # Web server port
FLASK_HOST = "0.0.0.0"             # Bind to all interfaces

# Queue Configuration
SEND_INTERVAL = 2                  # Send count to ESP32 every N seconds
MAX_RETRIES = 3                    # Max retries for ESP32 communication

# ============================================
# LOGGING SETUP
# ============================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ============================================
# MAIN APPLICATION CLASS
# ============================================

class PeopleCounter:
    """
    AI-Powered People Counter with YOLO Object Detection
    """
    
    def __init__(self, model_name=MODEL_NAME, esp32_ip=ESP32_IP):
        """
        Initialize People Counter with YOLO model and ESP32 connection.
        
        Args:
            model_name (str): Path or name of YOLO model
            esp32_ip (str): IP address of ESP32 device
        """
        self.esp32_ip = esp32_ip
        self.esp32_url = f"http://{esp32_ip}:{ESP32_PORT}"
        self.model_name = model_name
        self.model = None
        self.cap = None
        self.current_camera = 'esp32'  # 'esp32' or 'webcam'
        
        # Statistics
        self.count = 0
        self.last_count = 0
        self.frame_count = 0
        self.fps = 0
        self.last_fps_update = time.time()
        self.fps_counter = 0
        
        # Latest frame for web streaming
        self.latest_frame = None
        self.latest_frame_lock = threading.Lock()
        
        # ESP32 connection status
        self.esp32_connected = False
        
        # Thread control
        self.running = False
        self.camera_thread = None
        
        # Camera sources
        self.cameras = {
            'esp32': {
                'name': 'ESP32-CAM',
                'url': CAM_URL
            },
            'webcam': {
                'name': 'Webcam',
                'device': 0
            }
        }
        
        # Send count timer
        self.last_send_time = 0
        
        # Initialize Flask app
        self.app = Flask(__name__)
        self.setup_routes()
        
        # Initialize YOLO model
        self.load_model()
        
        logger.info("PeopleCounter initialized successfully")
        logger.info(f"ESP32 URL: {self.esp32_url}")
        logger.info(f"Model: {model_name}")
    
    # ============================================
    # MODEL LOADING
    # ============================================
    
    def load_model(self):
        """
        Load YOLO model for person detection.
        Downloads model if not found locally.
        """
        try:
            logger.info(f"Loading YOLO model: {self.model_name}")
            self.model = YOLO(self.model_name)
            logger.info("✓ YOLO model loaded successfully")
            
            # Test model with dummy input
            dummy = np.zeros((320, 320, 3), dtype=np.uint8)
            self.model(dummy, verbose=False, imgsz=IMAGE_SIZE)
            logger.info("✓ Model test passed")
            
        except Exception as e:
            logger.warning(f"Model not found locally: {e}")
            logger.info("Downloading YOLO model...")
            try:
                model_url = f"https://github.com/ultralytics/assets/releases/download/v8.0.0/{self.model_name}"
                urllib.request.urlretrieve(model_url, self.model_name)
                logger.info("✓ Model downloaded successfully")
                self.model = YOLO(self.model_name)
            except Exception as e2:
                logger.error(f"Failed to download model: {e2}")
                raise
    
    # ============================================
    # CAMERA CONTROL
    # ============================================
    
    def open_camera(self, source='esp32'):
        """
        Open camera stream from specified source.
        
        Args:
            source (str): 'esp32' or 'webcam'
        
        Returns:
            bool: True if camera opened successfully
        """
        # Close existing camera
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        
        self.current_camera = source
        
        try:
            if source == 'esp32':
                logger.info(f"Connecting to ESP32-CAM: {CAM_URL}")
                self.cap = cv2.VideoCapture(CAM_URL, cv2.CAP_FFMPEG)
                
                # Set buffer size for streaming
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                
            elif source == 'webcam':
                logger.info("Opening webcam...")
                self.cap = cv2.VideoCapture(0)
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            
            if self.cap.isOpened():
                logger.info(f"✓ Camera opened: {source}")
                return True
            else:
                logger.error(f"Failed to open camera: {source}")
                return False
                
        except Exception as e:
            logger.error(f"Camera error: {e}")
            return False
    
    def get_frame(self):
        """
        Capture a frame from current camera.
        
        Returns:
            np.ndarray: Frame image or None if failed
        """
        if self.cap is None or not self.cap.isOpened():
            return None
        
        try:
            ret, frame = self.cap.read()
            if ret and frame is not None:
                return cv2.resize(frame, (640, 480))
            return None
        except Exception as e:
            logger.error(f"Frame capture error: {e}")
            return None
    
    # ============================================
    # PEOPLE DETECTION
    # ============================================
    
    def detect_people(self, frame):
        """
        Detect people in frame using YOLO model.
        
        Args:
            frame (np.ndarray): Input image frame
        
        Returns:
            tuple: (processed_frame, count, detections)
        """
        if frame is None or self.model is None:
            return frame, 0, []
        
        try:
            # Run YOLO inference
            results = self.model(
                frame, 
                conf=CONFIDENCE_THRESHOLD,
                classes=[CLASS_ID_PERSON],
                verbose=False,
                imgsz=IMAGE_SIZE,
                device='cpu'
            )
            
            # Count people in current frame
            count = 0
            detections = []
            
            if results and len(results) > 0:
                boxes = results[0].boxes
                if boxes is not None and len(boxes) > 0:
                    # Filter valid detections
                    for box in boxes:
                        if box.cls[0] == CLASS_ID_PERSON:
                            if box.conf[0] >= CONFIDENCE_THRESHOLD:
                                count += 1
                                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                                conf = float(box.conf[0])
                                detections.append((x1, y1, x2, y2, conf))
            
            # Update count (use last valid count if no detection)
            if count > 0 or self.frame_count % 10 == 0:
                self.count = count
            
            # Annotate frame
            annotated_frame = self.annotate_frame(frame, detections, count)
            
            return annotated_frame, count, detections
            
        except Exception as e:
            logger.error(f"Detection error: {e}")
            return frame, self.count, []
    
    def annotate_frame(self, frame, detections, count):
        """
        Annotate frame with detection boxes and count.
        
        Args:
            frame (np.ndarray): Input frame
            detections (list): List of detections
            count (int): Number of people detected
        
        Returns:
            np.ndarray: Annotated frame
        """
        if frame is None:
            return None
        
        # Create a copy for annotation
        annotated = frame.copy()
        
        # Draw bounding boxes for each detection
        for x1, y1, x2, y2, conf in detections:
            # Green box for person
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
            
            # Label with confidence
            label = f"Person {conf:.2f}"
            cv2.putText(annotated, label, (x1, y1 - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        
        # Draw count overlay
        font = cv2.FONT_HERSHEY_SIMPLEX
        
        # Background for text
        overlay = annotated.copy()
        cv2.rectangle(overlay, (10, 10), (200, 70), (0, 0, 0), -1)
        annotated = cv2.addWeighted(annotated, 0.7, overlay, 0.3, 0)
        
        # Count text
        cv2.putText(annotated, f"People: {count}", (20, 40),
                   font, 0.8, (0, 255, 0), 2)
        
        # FPS
        cv2.putText(annotated, f"FPS: {self.fps:.1f}", (20, 65),
                   font, 0.6, (255, 255, 0), 2)
        
        # Camera source
        cv2.putText(annotated, f"Source: {self.current_camera}", (450, 30),
                   font, 0.5, (200, 200, 200), 1)
        
        # ESP32 connection status
        status = "ESP32: Connected" if self.esp32_connected else "ESP32: Disconnected"
        color = (0, 255, 0) if self.esp32_connected else (0, 0, 255)
        cv2.putText(annotated, status, (450, 55),
                   font, 0.5, color, 1)
        
        # Timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(annotated, timestamp, (450, 80),
                   font, 0.5, (200, 200, 200), 1)
        
        return annotated
    
    # ============================================
    # ESP32 COMMUNICATION
    # ============================================
    
    def send_count_to_esp32(self, count):
        """
        Send people count to ESP32 via HTTP POST.
        
        Args:
            count (int): Number of people detected
        
        Returns:
            bool: True if successful
        """
        if count < 0:
            count = 0
        
        try:
            url = f"{self.esp32_url}/receive_count"
            data = {'yolo_count': count}
            
            response = requests.post(
                url, 
                data=data, 
                timeout=2
            )
            
            if response.status_code == 200:
                self.esp32_connected = True
                logger.debug(f"✓ Sent count {count} to ESP32")
                return True
            else:
                logger.warning(f"ESP32 response error: {response.status_code}")
                self.esp32_connected = False
                return False
                
        except requests.ConnectionError:
            self.esp32_connected = False
            logger.warning("⚠️ ESP32 not reachable")
            return False
            
        except requests.Timeout:
            self.esp32_connected = False
            logger.warning("⚠️ ESP32 connection timeout")
            return False
            
        except Exception as e:
            self.esp32_connected = False
            logger.error(f"⚠️ ESP32 communication error: {e}")
            return False
    
    def test_esp32_connection(self):
        """
        Test ESP32 connection by fetching status.
        
        Returns:
            bool: True if connected
        """
        try:
            url = f"{self.esp32_url}/status"
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                self.esp32_connected = True
                return True
            else:
                self.esp32_connected = False
                return False
        except:
            self.esp32_connected = False
            return False
    
    # ============================================
    # CAMERA THREAD
    # ============================================
    
    def camera_thread_func(self):
        """
        Main camera processing thread.
        Captures frames, runs detection, and updates statistics.
        """
        logger.info("Camera thread started")
        
        # Initialize camera
        if not self.open_camera('esp32'):
            logger.warning("ESP32-CAM failed, trying webcam...")
            if not self.open_camera('webcam'):
                logger.error("No camera available!")
                return
        
        frame_counter = 0
        last_esp32_send = 0
        
        while self.running:
            try:
                # Capture frame
                frame = self.get_frame()
                
                if frame is None:
                    logger.warning("Frame capture failed, reconnecting...")
                    time.sleep(1)
                    self.open_camera(self.current_camera)
                    continue
                
                # Skip frames for speed
                frame_counter += 1
                if frame_counter % FRAME_SKIP == 0:
                    # Run detection
                    processed_frame, count, _ = self.detect_people(frame)
                    
                    # Update statistics
                    self.count = count
                    self.fps_counter += 1
                    
                    # Update FPS
                    current_time = time.time()
                    if current_time - self.last_fps_update >= 1.0:
                        self.fps = self.fps_counter / (current_time - self.last_fps_update)
                        self.fps_counter = 0
                        self.last_fps_update = current_time
                    
                    # Store latest frame
                    with self.latest_frame_lock:
                        self.latest_frame = processed_frame
                    
                    # Send count to ESP32
                    if current_time - last_esp32_send >= SEND_INTERVAL:
                        self.send_count_to_esp32(count)
                        last_esp32_send = current_time
                else:
                    # For skipped frames, use latest frame without detection
                    with self.latest_frame_lock:
                        if self.latest_frame is None:
                            self.latest_frame = frame
                
            except Exception as e:
                logger.error(f"Camera thread error: {e}")
                time.sleep(1)
        
        # Cleanup
        if self.cap is not None:
            self.cap.release()
        
        logger.info("Camera thread stopped")
    
    # ============================================
    # MJPEG STREAM GENERATOR
    # ============================================
    
    def generate_mjpeg(self):
        """
        Generate MJPEG stream for web browser.
        
        Yields:
            bytes: MJPEG frame data
        """
        while True:
            try:
                with self.latest_frame_lock:
                    frame = self.latest_frame
                
                if frame is not None:
                    ret, jpeg = cv2.imencode(
                        '.jpg', 
                        frame, 
                        [cv2.IMWRITE_JPEG_QUALITY, 80]
                    )
                    if ret:
                        yield (
                            b'--frame\r\n'
                            b'Content-Type: image/jpeg\r\n\r\n' +
                            jpeg.tobytes() +
                            b'\r\n'
                        )
                
                time.sleep(0.033)  # ~30 FPS
                
            except Exception as e:
                logger.error(f"MJPEG generation error: {e}")
                time.sleep(0.1)
    
    # ============================================
    # FLASK ROUTES
    # ============================================
    
    def setup_routes(self):
        """Setup Flask routes for web interface."""
        
        @self.app.route('/')
        def index():
            """Web dashboard homepage."""
            return render_template_string(HTML_TEMPLATE)
        
        @self.app.route('/video_feed')
        def video_feed():
            """MJPEG video stream endpoint."""
            return Response(
                self.generate_mjpeg(),
                mimetype='multipart/x-mixed-replace; boundary=frame'
            )
        
        @self.app.route('/api/status')
        def status():
            """Get system status as JSON."""
            return jsonify({
                'count': self.count,
                'fps': round(self.fps, 1),
                'esp32': self.esp32_connected,
                'camera': self.current_camera,
                'frame_count': self.frame_count,
                'uptime': time.time() - self.last_fps_update
            })
        
        @self.app.route('/api/switch')
        def switch_camera():
            """Switch between ESP32-CAM and webcam."""
            if self.current_camera == 'esp32':
                self.open_camera('webcam')
            else:
                self.open_camera('esp32')
            return jsonify({'camera': self.current_camera})
        
        @self.app.route('/api/send')
        def send_count():
            """Manually send count to ESP32."""
            success = self.send_count_to_esp32(self.count)
            return jsonify({'success': success})
        
        @self.app.route('/api/esp32_status')
        def esp32_status():
            """Get ESP32 connection status."""
            connected = self.test_esp32_connection()
            return jsonify({'connected': connected})
        
        @self.app.route('/api/esp32_data')
        def esp32_data():
            """Get ESP32 queue data."""
            try:
                response = requests.get(f"{self.esp32_url}/status", timeout=2)
                if response.status_code == 200:
                    data = response.json()
                    return jsonify(data)
                else:
                    return jsonify({'error': 'ESP32 error'}), 500
            except:
                return jsonify({'error': 'ESP32 not reachable'}), 500
    
    # ============================================
    # APPLICATION START
    # ============================================
    
    def start(self):
        """
        Start the people counter application.
        Launches camera thread and Flask server.
        """
        logger.info("=" * 60)
        logger.info("🚦 AI People Counter - Smart Queue System")
        logger.info("=" * 60)
        logger.info(f"📹 Camera Source: {self.current_camera}")
        logger.info(f"🤖 YOLO Model: {self.model_name}")
        logger.info(f"🎯 Confidence Threshold: {CONFIDENCE_THRESHOLD}")
        logger.info(f"📡 ESP32 IP: {self.esp32_ip}")
        logger.info(f"🌐 Web Interface: http://localhost:{FLASK_PORT}")
        logger.info("=" * 60)
        logger.info("Starting application...")
        
        # Start camera thread
        self.running = True
        self.camera_thread = threading.Thread(target=self.camera_thread_func, daemon=True)
        self.camera_thread.start()
        
        # Start Flask server
        try:
            self.app.run(
                host=FLASK_HOST,
                port=FLASK_PORT,
                threaded=True,
                debug=False,
                use_reloader=False
            )
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self.running = False
            if self.cap is not None:
                self.cap.release()
            logger.info("Application stopped")

# ============================================
# HTML TEMPLATE
# ============================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI People Counter - Smart Queue System</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
        }
        body {
            background: #0a0e27;
            color: #e0e0e0;
            padding: 20px;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .container {
            max-width: 1200px;
            width: 100%;
            margin: 0 auto;
        }
        .header {
            text-align: center;
            margin-bottom: 30px;
        }
        .header h1 {
            font-size: 32px;
            font-weight: 700;
            background: linear-gradient(135deg, #00e676, #2979ff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .header p {
            color: #6b7a9f;
            font-size: 16px;
            margin-top: 8px;
        }
        .main-grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 20px;
        }
        .video-container {
            background: #12163a;
            border-radius: 16px;
            padding: 16px;
            border: 1px solid rgba(255, 255, 255, 0.06);
        }
        .video-container video {
            width: 100%;
            border-radius: 12px;
            background: #000;
        }
        .video-container img {
            width: 100%;
            border-radius: 12px;
            background: #000;
            display: block;
        }
        .stats-panel {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }
        .stat-card {
            background: #12163a;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            border: 1px solid rgba(255, 255, 255, 0.06);
        }
        .stat-card .icon {
            font-size: 28px;
            margin-bottom: 4px;
        }
        .stat-card .value {
            font-size: 36px;
            font-weight: 700;
            color: #fff;
        }
        .stat-card .value.green {
            color: #00e676;
        }
        .stat-card .value.orange {
            color: #ff9800;
        }
        .stat-card .value.blue {
            color: #2979ff;
        }
        .stat-card .label {
            font-size: 12px;
            color: #6b7a9f;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-top: 4px;
        }
        .stat-card .status {
            font-size: 12px;
            padding: 3px 12px;
            border-radius: 12px;
            display: inline-block;
            margin-top: 6px;
        }
        .status.online {
            background: rgba(0, 230, 118, 0.15);
            color: #00e676;
        }
        .status.offline {
            background: rgba(255, 23, 68, 0.15);
            color: #ff1744;
        }
        .control-buttons {
            grid-column: 1 / -1;
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        .btn {
            flex: 1;
            padding: 12px 20px;
            border: none;
            border-radius: 10px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
            min-width: 100px;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
        }
        .btn:active {
            transform: scale(0.97);
        }
        .btn-green {
            background: #00e676;
            color: #000;
        }
        .btn-blue {
            background: #2979ff;
            color: #fff;
        }
        .btn-orange {
            background: #ff9800;
            color: #000;
        }
        .btn-purple {
            background: #7c4dff;
            color: #fff;
        }
        .btn-red {
            background: #ff1744;
            color: #fff;
        }
        .esp32-data {
            grid-column: 1 / -1;
            background: rgba(255, 255, 255, 0.03);
            border-radius: 12px;
            padding: 16px;
            border: 1px solid rgba(255, 255, 255, 0.06);
        }
        .esp32-data h3 {
            color: #6b7a9f;
            font-size: 14px;
            margin-bottom: 10px;
        }
        .esp32-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 10px;
        }
        .esp32-item {
            text-align: center;
        }
        .esp32-item .val {
            font-size: 20px;
            font-weight: 600;
            color: #fff;
        }
        .esp32-item .lbl {
            font-size: 11px;
            color: #6b7a9f;
        }
        @media (max-width: 768px) {
            .main-grid {
                grid-template-columns: 1fr;
            }
            .stats-panel {
                grid-template-columns: 1fr 1fr;
            }
            .esp32-grid {
                grid-template-columns: 1fr 1fr;
            }
            .header h1 {
                font-size: 24px;
            }
        }
        @media (max-width: 480px) {
            .stats-panel {
                grid-template-columns: 1fr;
            }
            .control-buttons {
                flex-direction: column;
            }
            .btn {
                width: 100%;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 AI People Counter</h1>
            <p>Real-time Person Detection with YOLO & ESP32 Integration</p>
        </div>
        
        <div class="main-grid">
            <!-- Video Feed -->
            <div class="video-container">
                <img id="videoFeed" src="/video_feed" alt="Live Video Feed">
            </div>
            
            <!-- Stats Panel -->
            <div class="stats-panel">
                <div class="stat-card">
                    <div class="icon">👥</div>
                    <div class="value green" id="peopleCount">0</div>
                    <div class="label">People Detected</div>
                </div>
                <div class="stat-card">
                    <div class="icon">⚡</div>
                    <div class="value blue" id="fpsDisplay">0.0</div>
                    <div class="label">FPS</div>
                </div>
                <div class="stat-card">
                    <div class="icon">📡</div>
                    <div class="value" id="espStatus" style="font-size:20px;">⚠️</div>
                    <div class="label">ESP32 Status</div>
                    <span class="status offline" id="espStatusText">Offline</span>
                </div>
                <div class="stat-card">
                    <div class="icon">📷</div>
                    <div class="value" id="cameraSource" style="font-size:16px;">ESP32</div>
                    <div class="label">Camera Source</div>
                </div>
                
                <div class="control-buttons">
                    <button class="btn btn-blue" onclick="switchCamera()">📷 Switch Camera</button>
                    <button class="btn btn-green" onclick="sendCount()">📤 Send to ESP32</button>
                    <button class="btn btn-purple" onclick="testESP()">🔌 Test ESP32</button>
                    <button class="btn btn-orange" onclick="refreshData()">🔄 Refresh</button>
                </div>
                
                <!-- ESP32 Queue Data -->
                <div class="esp32-data" id="esp32DataPanel">
                    <h3>📊 ESP32 Queue Data</h3>
                    <div class="esp32-grid">
                        <div class="esp32-item">
                            <div class="val" id="espManual">-</div>
                            <div class="lbl">Manual Count</div>
                        </div>
                        <div class="esp32-item">
                            <div class="val" id="espYolo">-</div>
                            <div class="lbl">YOLO Count</div>
                        </div>
                        <div class="esp32-item">
                            <div class="val" id="espTotal">-</div>
                            <div class="lbl">Total People</div>
                        </div>
                        <div class="esp32-item">
                            <div class="val" id="espLine">-</div>
                            <div class="lbl">Queue Length</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        // ============================================
        // UPDATE FUNCTIONS
        // ============================================
        
        // Update stats every second
        async function updateStats() {
            try {
                const response = await fetch('/api/status');
                const data = await response.json();
                
                document.getElementById('peopleCount').textContent = data.count;
                document.getElementById('fpsDisplay').textContent = data.fps;
                
                // Update ESP32 status
                const espStatus = document.getElementById('espStatus');
                const espStatusText = document.getElementById('espStatusText');
                if (data.esp32) {
                    espStatus.textContent = '✅';
                    espStatusText.textContent = 'Online';
                    espStatusText.className = 'status online';
                } else {
                    espStatus.textContent = '❌';
                    espStatusText.textContent = 'Offline';
                    espStatusText.className = 'status offline';
                }
                
                // Update camera source
                document.getElementById('cameraSource').textContent = data.camera.toUpperCase();
                
            } catch(e) {
                console.error('Update error:', e);
            }
        }
        
        // Update ESP32 data
        async function updateESP32Data() {
            try {
                const response = await fetch('/api/esp32_data');
                if (response.ok) {
                    const data = await response.json();
                    document.getElementById('espManual').textContent = data.m || '-';
                    document.getElementById('espYolo').textContent = data.y || '-';
                    document.getElementById('espTotal').textContent = data.t || '-';
                    document.getElementById('espLine').textContent = data.l || '-';
                }
            } catch(e) {
                // Silent fail - ESP32 not reachable
            }
        }
        
        // ============================================
        // BUTTON FUNCTIONS
        // ============================================
        
        function switchCamera() {
            fetch('/api/switch')
                .then(() => {
                    setTimeout(updateStats, 1000);
                })
                .catch(e => console.error('Switch error:', e));
        }
        
        function sendCount() {
            fetch('/api/send')
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert('✅ Count sent to ESP32 successfully!');
                    } else {
                        alert('❌ Failed to send count. ESP32 offline?');
                    }
                })
                .catch(e => console.error('Send error:', e));
        }
        
        function testESP() {
            fetch('/api/esp32_status')
                .then(response => response.json())
                .then(data => {
                    if (data.connected) {
                        alert('✅ ESP32 is connected and reachable!');
                    } else {
                        alert('❌ ESP32 is not reachable. Check WiFi connection.');
                    }
                })
                .catch(e => alert('❌ ESP32 test failed: ' + e.message));
        }
        
        function refreshData() {
            updateStats();
            updateESP32Data();
        }
        
        // ============================================
        // INITIALIZATION
        // ============================================
        
        // Update every second
        setInterval(updateStats, 1000);
        setInterval(updateESP32Data, 3000);
        
        // Initial update
        updateStats();
        setTimeout(updateESP32Data, 1000);
        
        // Handle page visibility (reconnect on focus)
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) {
                refreshData();
            }
        });
    </script>
</body>
</html>
"""

# ============================================
# MAIN ENTRY POINT
# ============================================

if __name__ == "__main__":
    try:
        # Create and start the people counter
        counter = PeopleCounter()
        counter.start()
    except KeyboardInterrupt:
        logger.info("\n👋 Shutting down...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        sys.exit(1)