#!/usr/bin/env python3
"""
Palantir at Home - Advanced Webcam Motion Monitoring System
Real-time motion detection with web dashboard, snapshots, and alerts
"""

import cv2
import numpy as np
import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, Response, request, jsonify
from flask_socketio import SocketIO, emit
import threading
import time
from collections import deque
import sqlite3
from PIL import Image

# Configuration
CONFIG = {
    'camera_id': 0,  # 0 = Logitech C170, 1 = iPhone Camera
    'width': 1280,
    'height': 720,
    'fps': 30,
    'motion_threshold': 25,
    'min_area': 500,
    'max_area': 100000,
    'blur_size': 21,
    'snapshot_dir': 'snapshots',
    'db_path': 'palantir.db',
    'host': '0.0.0.0',
    'port': 5555,
    'debug': False
}

# Paths
BASE_DIR = Path(__file__).parent
SNAPSHOT_DIR = BASE_DIR / CONFIG['snapshot_dir']
DB_PATH = BASE_DIR / CONFIG['db_path']
SNAPSHOT_DIR.mkdir(exist_ok=True)

# Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'palantir-secret-key-change-in-production'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Global state
class MotionMonitor:
    def __init__(self):
        self.camera = None
        self.running = False
        self.motion_detected = False
        self.motion_count = 0
        self.last_motion_time = None
        self.current_frame = None
        self.annotated_frame = None
        self.bg_subtractor = None
        self.lock = threading.Lock()
        self.motion_events = deque(maxlen=100)
        self.fps_counter = deque(maxlen=30)
        
    def start_camera(self):
        """Initialize camera capture"""
        try:
            self.camera = cv2.VideoCapture(CONFIG['camera_id'], cv2.CAP_AVFOUNDATION)
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, CONFIG['width'])
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, CONFIG['height'])
            self.camera.set(cv2.CAP_PROP_FPS, CONFIG['fps'])
            
            if not self.camera.isOpened():
                print(f"❌ Failed to open camera {CONFIG['camera_id']}")
                return False
                
            self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
                history=500, 
                varThreshold=50,
                detectShadows=True
            )
            print(f"✅ Camera initialized: {CONFIG['width']}x{CONFIG['height']}@{CONFIG['fps']}fps")
            return True
        except Exception as e:
            print(f"❌ Camera error: {e}")
            return False
    
    def detect_motion(self, frame):
        """Detect motion in frame"""
        if self.bg_subtractor is None:
            return False, None, 0
            
        # Apply background subtraction
        fg_mask = self.bg_subtractor.apply(frame)
        
        # Remove noise
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
        fg_mask = cv2.GaussianBlur(fg_mask, (CONFIG['blur_size'], CONFIG['blur_size']), 0)
        
        # Find contours
        contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        motion_found = False
        total_motion_area = 0
        bounding_boxes = []
        
        for contour in contours:
            area = cv2.contourArea(contour)
            if CONFIG['min_area'] < area < CONFIG['max_area']:
                motion_found = True
                total_motion_area += area
                x, y, w, h = cv2.boundingRect(contour)
                bounding_boxes.append((x, y, w, h))
        
        return motion_found, bounding_boxes, total_motion_area
    
    def process_frames(self):
        """Main frame processing loop"""
        frame_count = 0
        last_snapshot_time = time.time()
        snapshot_interval = 5  # seconds
        
        while self.running:
            if self.camera is None or not self.camera.isOpened():
                time.sleep(1)
                continue
                
            ret, frame = self.camera.read()
            if not ret:
                time.sleep(0.1)
                continue
            
            frame_count += 1
            
            # Calculate FPS
            current_time = time.time()
            self.fps_counter.append(current_time)
            if len(self.fps_counter) > 1:
                fps = len(self.fps_counter) / (self.fps_counter[-1] - self.fps_counter[0])
            else:
                fps = 0
            
            # Detect motion
            motion_found, boxes, motion_area = self.detect_motion(frame)
            
            # Annotate frame
            annotated = frame.copy()
            if motion_found:
                self.motion_detected = True
                self.last_motion_time = datetime.now()
                
                # Draw bounding boxes
                for (x, y, w, h) in boxes:
                    cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 255, 0), 2)
                
                # Draw motion info
                cv2.putText(annotated, f"MOTION DETECTED", (10, 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                cv2.putText(annotated, f"Area: {motion_area}", (10, 60),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                
                # Log motion event
                self.motion_count += 1
                event = {
                    'timestamp': self.last_motion_time.isoformat(),
                    'area': motion_area,
                    'boxes': len(boxes)
                }
                self.motion_events.append(event)
                save_motion_event(event)
                
                # Auto-snapshot on motion
                if time.time() - last_snapshot_time > 2:  # Min 2s between snapshots
                    snapshot_path = save_snapshot(annotated, 'motion')
                    last_snapshot_time = time.time()
                    socketio.emit('snapshot_saved', {'path': str(snapshot_path), 'reason': 'motion'})
            else:
                self.motion_detected = False
            
            # Draw FPS
            cv2.putText(annotated, f"FPS: {fps:.1f}", (annotated.shape[1] - 150, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            
            # Update state
            with self.lock:
                self.current_frame = frame
                self.annotated_frame = annotated
            
            # Broadcast frame to WebSocket clients
            try:
                _, buffer = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
                frame_base64 = base64.b64encode(buffer).decode('utf-8')
                socketio.emit('video_frame', {
                    'frame': frame_base64,
                    'motion': self.motion_detected,
                    'fps': fps,
                    'motion_count': self.motion_count
                })
            except Exception as e:
                pass  # Ignore WebSocket errors
            
            time.sleep(0.01)  # Small delay to prevent CPU hog
    
    def start(self):
        """Start monitoring"""
        if not self.start_camera():
            return False
        self.running = True
        self.thread = threading.Thread(target=self.process_frames, daemon=True)
        self.thread.start()
        print("✅ Motion monitoring started")
        return True
    
    def stop(self):
        """Stop monitoring"""
        self.running = False
        if self.camera:
            self.camera.release()
        print("⏹️ Motion monitoring stopped")
    
    def get_status(self):
        """Get current status"""
        with self.lock:
            return {
                'running': self.running,
                'motion_detected': self.motion_detected,
                'motion_count': self.motion_count,
                'last_motion': self.last_motion_time.isoformat() if self.last_motion_time else None,
                'camera_id': CONFIG['camera_id']
            }

# Global monitor instance
monitor = MotionMonitor()

# Database functions
def init_db():
    """Initialize SQLite database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS motion_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            area INTEGER,
            boxes INTEGER,
            snapshot_path TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT,
            timestamp TEXT,
            reason TEXT,
            motion_area INTEGER
        )
    ''')
    conn.commit()
    conn.close()

def save_motion_event(event):
    """Save motion event to database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO motion_events (timestamp, area, boxes)
        VALUES (?, ?, ?)
    ''', (event['timestamp'], event['area'], event['boxes']))
    conn.commit()
    conn.close()

def save_snapshot(frame, reason='manual'):
    """Save snapshot to disk"""
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    filename = f"{timestamp}_{reason}.jpg"
    path = SNAPSHOT_DIR / filename
    cv2.imwrite(str(path), frame)
    
    # Log to database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO snapshots (path, timestamp, reason)
        VALUES (?, ?, ?)
    ''', (str(path), timestamp, reason))
    conn.commit()
    conn.close()
    
    return path

# Routes
@app.route('/')
def index():
    """Main dashboard"""
    return render_template('dashboard.html')

@app.route('/api/status')
def api_status():
    """Get monitor status"""
    return jsonify(monitor.get_status())

@app.route('/api/start', methods=['POST'])
def api_start():
    """Start monitoring"""
    if monitor.start():
        return jsonify({'success': True, 'message': 'Monitoring started'})
    return jsonify({'success': False, 'message': 'Failed to start'}), 500

@app.route('/api/stop', methods=['POST'])
def api_stop():
    """Stop monitoring"""
    monitor.stop()
    return jsonify({'success': True, 'message': 'Monitoring stopped'})

@app.route('/api/snapshot', methods=['POST'])
def api_snapshot():
    """Take manual snapshot"""
    with monitor.lock:
        if monitor.annotated_frame is not None:
            path = save_snapshot(monitor.annotated_frame, 'manual')
            return jsonify({'success': True, 'path': str(path)})
    return jsonify({'success': False, 'message': 'No frame available'}), 500

@app.route('/api/snapshots')
def api_snapshots():
    """Get recent snapshots"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT path, timestamp, reason, motion_area 
        FROM snapshots 
        ORDER BY timestamp DESC 
        LIMIT 50
    ''')
    snapshots = [
        {'path': row[0], 'timestamp': row[1], 'reason': row[2], 'motion_area': row[3]}
        for row in cursor.fetchall()
    ]
    conn.close()
    return jsonify(snapshots)

@app.route('/api/events')
def api_events():
    """Get recent motion events"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT timestamp, area, boxes 
        FROM motion_events 
        ORDER BY timestamp DESC 
        LIMIT 100
    ''')
    events = [
        {'timestamp': row[0], 'area': row[1], 'boxes': row[2]}
        for row in cursor.fetchall()
    ]
    conn.close()
    return jsonify(events)

@app.route('/api/config', methods=['GET'])
def api_get_config():
    """Get current configuration"""
    return jsonify(CONFIG)

@app.route('/api/config', methods=['POST'])
def api_set_config():
    """Update configuration"""
    global CONFIG
    data = request.json
    for key, value in data.items():
        if key in CONFIG:
            CONFIG[key] = value
    return jsonify({'success': True, 'config': CONFIG})

@app.route('/snapshots/<filename>')
def serve_snapshot(filename):
    """Serve snapshot images"""
    from flask import send_from_directory
    return send_from_directory(SNAPSHOT_DIR, filename)

# WebSocket events
@socketio.on('connect')
def handle_connect():
    print("🔌 Client connected")
    emit('connected', {'message': 'Connected to Palantir'})

@socketio.on('disconnect')
def handle_disconnect():
    print("🔌 Client disconnected")

@socketio.on('request_status')
def handle_status_request():
    emit('status_update', monitor.get_status())

# Main
if __name__ == '__main__':
    print("👁️  PALANTIR AT HOME - Starting...")
    print(f"📁 Snapshots: {SNAPSHOT_DIR}")
    print(f"💾 Database: {DB_PATH}")
    print(f"🌐 Dashboard: http://localhost:{CONFIG['port']}")
    print(f"📹 Camera: {CONFIG['camera_id']} (0=Logitech, 1=iPhone)")
    print("=" * 50)
    
    init_db()
    
    # Start monitoring
    if not monitor.start():
        print("⚠️  Starting without camera (manual start required)")
    
    # Start web server
    socketio.run(app, host=CONFIG['host'], port=CONFIG['port'], debug=CONFIG['debug'], allow_unsafe_werkzeug=True)
