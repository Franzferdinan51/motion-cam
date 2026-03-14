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
    'snapshot_dir': 'snapshots',  # Can be absolute path or relative
    'snapshot_retention_days': 7,  # Auto-delete snapshots older than this
    'auto_cleanup_enabled': True,  # Enable automatic cleanup
    'auto_cleanup_interval_hours': 24,  # Run cleanup every X hours
    'max_snapshots': 1000,  # Keep max N snapshots (delete oldest when exceeded)
    'db_path': 'palantir.db',
    'host': '0.0.0.0',
    'port': 5555,
    'debug': False
}

# Paths
BASE_DIR = Path(__file__).parent
# Support both relative and absolute paths for snapshot directory
if Path(CONFIG['snapshot_dir']).is_absolute():
    SNAPSHOT_DIR = Path(CONFIG['snapshot_dir'])
else:
    SNAPSHOT_DIR = BASE_DIR / CONFIG['snapshot_dir']
DB_PATH = BASE_DIR / CONFIG['db_path']
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

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

def cleanup_old_snapshots():
    """Delete snapshots older than retention period"""
    if not CONFIG['auto_cleanup_enabled']:
        return 0, "Cleanup disabled"
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Calculate cutoff date
        from datetime import timedelta
        cutoff_date = (datetime.now() - timedelta(days=CONFIG['snapshot_retention_days'])).strftime('%Y%m%d-%H%M%S')
        
        # Get old snapshots
        cursor.execute('SELECT path, timestamp FROM snapshots WHERE timestamp < ? ORDER BY timestamp', (cutoff_date,))
        old_snapshots = cursor.fetchall()
        
        deleted_count = 0
        for path, timestamp in old_snapshots:
            try:
                # Delete file if exists
                if Path(path).exists():
                    Path(path).unlink()
                # Delete from database
                cursor.execute('DELETE FROM snapshots WHERE path = ?', (path,))
                deleted_count += 1
            except Exception as e:
                print(f"⚠️  Error deleting {path}: {e}")
        
        conn.commit()
        conn.close()
        
        return deleted_count, f"Deleted {deleted_count} old snapshots"
    except Exception as e:
        return 0, f"Cleanup error: {e}"

def enforce_max_snapshots():
    """Delete oldest snapshots if count exceeds max"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Get count
        cursor.execute('SELECT COUNT(*) FROM snapshots')
        count = cursor.fetchone()[0]
        
        if count <= CONFIG['max_snapshots']:
            conn.close()
            return 0, "Within limit"
        
        # Delete oldest
        to_delete = count - CONFIG['max_snapshots']
        cursor.execute('SELECT path FROM snapshots ORDER BY timestamp ASC LIMIT ?', (to_delete,))
        old_snapshots = cursor.fetchall()
        
        deleted_count = 0
        for (path,) in old_snapshots:
            try:
                if Path(path).exists():
                    Path(path).unlink()
                cursor.execute('DELETE FROM snapshots WHERE path = ?', (path,))
                deleted_count += 1
            except Exception as e:
                print(f"⚠️  Error deleting {path}: {e}")
        
        conn.commit()
        conn.close()
        
        return deleted_count, f"Deleted {deleted_count} to enforce max limit"
    except Exception as e:
        return 0, f"Max enforcement error: {e}"

def run_auto_cleanup():
    """Background cleanup thread"""
    while True:
        time.sleep(CONFIG['auto_cleanup_interval_hours'] * 3600)
        try:
            count1, msg1 = cleanup_old_snapshots()
            count2, msg2 = enforce_max_snapshots()
            print(f"🧹 Auto-cleanup: {msg1}, {msg2}")
            socketio.emit('cleanup_result', {'deleted': count1 + count2, 'message': f'{msg1}, {msg2}'})
        except Exception as e:
            print(f"❌ Cleanup error: {e}")

def get_storage_stats():
    """Get snapshot storage statistics"""
    try:
        # Count files
        snapshot_files = list(SNAPSHOT_DIR.glob('*.jpg'))
        total_size = sum(f.stat().st_size for f in snapshot_files)
        
        # Database count
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM snapshots')
        db_count = cursor.fetchone()[0]
        conn.close()
        
        return {
            'file_count': len(snapshot_files),
            'db_count': db_count,
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'snapshot_dir': str(SNAPSHOT_DIR),
            'retention_days': CONFIG['snapshot_retention_days'],
            'max_snapshots': CONFIG['max_snapshots'],
            'auto_cleanup': CONFIG['auto_cleanup_enabled']
        }
    except Exception as e:
        return {'error': str(e)}

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

@app.route('/api/storage/stats')
def api_storage_stats():
    """Get storage statistics"""
    return jsonify(get_storage_stats())

@app.route('/api/storage/cleanup', methods=['POST'])
def api_cleanup():
    """Manually trigger cleanup"""
    data = request.json or {}
    days = data.get('days', CONFIG['snapshot_retention_days'])
    
    # Temporarily override retention
    original = CONFIG['snapshot_retention_days']
    CONFIG['snapshot_retention_days'] = days
    
    count1, msg1 = cleanup_old_snapshots()
    count2, msg2 = enforce_max_snapshots()
    
    # Restore
    CONFIG['snapshot_retention_days'] = original
    
    return jsonify({
        'success': True,
        'deleted': count1 + count2,
        'message': f'{msg1}, {msg2}'
    })

@app.route('/api/storage/clear', methods=['POST'])
def api_clear_all():
    """Clear all snapshots"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Get all paths
        cursor.execute('SELECT path FROM snapshots')
        all_paths = cursor.fetchall()
        
        deleted_count = 0
        for (path,) in all_paths:
            try:
                if Path(path).exists():
                    Path(path).unlink()
                deleted_count += 1
            except Exception as e:
                pass
        
        # Clear database
        cursor.execute('DELETE FROM snapshots')
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'deleted': deleted_count,
            'message': f'Cleared all {deleted_count} snapshots'
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/storage/location', methods=['POST'])
def api_set_location():
    """Change snapshot save location"""
    data = request.json
    if not data or 'path' not in data:
        return jsonify({'success': False, 'message': 'Path required'}), 400
    
    new_path = Path(data['path'])
    
    # Validate path
    try:
        new_path.mkdir(parents=True, exist_ok=True)
        # Test write
        test_file = new_path / '.test_write'
        test_file.touch()
        test_file.unlink()
        
        # Update config
        CONFIG['snapshot_dir'] = str(new_path)
        global SNAPSHOT_DIR
        SNAPSHOT_DIR = new_path
        
        return jsonify({
            'success': True,
            'path': str(new_path),
            'message': f'Snapshot location changed to {new_path}'
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

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
    
    # Start auto-cleanup thread
    if CONFIG['auto_cleanup_enabled']:
        cleanup_thread = threading.Thread(target=run_auto_cleanup, daemon=True)
        cleanup_thread.start()
        print(f"🧹 Auto-cleanup enabled (every {CONFIG['auto_cleanup_interval_hours']}h, retain {CONFIG['snapshot_retention_days']} days)")
    
    # Start monitoring
    if not monitor.start():
        print("⚠️  Starting without camera (manual start required)")
    
    # Start web server
    socketio.run(app, host=CONFIG['host'], port=CONFIG['port'], debug=CONFIG['debug'], allow_unsafe_werkzeug=True)

# =====================================================
# NEXUS PHONE EXTRACTOR INTEGRATION
# =====================================================

from .nexus.phone_extractor import PhoneExtractor

nexus_extractor = None

@app.route('/nexus')
def nexus_dashboard():
    """Nexus Phone Extractor dashboard"""
    return render_template('nexus.html')

@app.route('/api/nexus/status')
def nexus_status():
    """Check if device is connected"""
    global nexus_extractor
    if nexus_extractor is None:
        nexus_extractor = PhoneExtractor()
    
    connected, devices = nexus_extractor.check_adb()
    return jsonify({
        'connected': connected,
        'devices': devices if isinstance(devices, list) else []
    })

@app.route('/api/nexus/device-info')
def nexus_device_info():
    """Get connected device information"""
    global nexus_extractor
    if nexus_extractor is None:
        nexus_extractor = PhoneExtractor()
    
    info = nexus_extractor.get_device_info()
    return jsonify({'success': True, 'info': info})

@app.route('/api/nexus/extract/sms', methods=['POST'])
def nexus_extract_sms():
    """Extract SMS messages"""
    global nexus_extractor
    if nexus_extractor is None:
        nexus_extractor = PhoneExtractor()
    
    result = nexus_extractor.extract_sms()
    return jsonify(result)

@app.route('/api/nexus/extract/calls', methods=['POST'])
def nexus_extract_calls():
    """Extract call logs"""
    global nexus_extractor
    if nexus_extractor is None:
        nexus_extractor = PhoneExtractor()
    
    result = nexus_extractor.extract_call_logs()
    return jsonify(result)

@app.route('/api/nexus/extract/contacts', methods=['POST'])
def nexus_extract_contacts():
    """Extract contacts"""
    global nexus_extractor
    if nexus_extractor is None:
        nexus_extractor = PhoneExtractor()
    
    result = nexus_extractor.extract_contacts()
    return jsonify(result)

@app.route('/api/nexus/extract/photos', methods=['POST'])
def nexus_extract_photos():
    """Extract photos with metadata"""
    global nexus_extractor
    if nexus_extractor is None:
        nexus_extractor = PhoneExtractor()
    
    result = nexus_extractor.extract_photos()
    return jsonify(result)

@app.route('/api/nexus/extract/location', methods=['POST'])
def nexus_extract_location():
    """Extract location history"""
    global nexus_extractor
    if nexus_extractor is None:
        nexus_extractor = PhoneExtractor()
    
    result = nexus_extractor.get_location_history()
    return jsonify(result)

@app.route('/api/nexus/extractions')
def nexus_list_extractions():
    """List all extractions"""
    global nexus_extractor
    if nexus_extractor is None:
        nexus_extractor = PhoneExtractor()
    
    extractions = []
    for file in nexus_extractor.extract_dir.rglob('*.json'):
        try:
            with open(file) as f:
                data = json.load(f)
                extractions.append({
                    'type': file.stem,
                    'timestamp': file.stat().st_mtime,
                    'count': data.get('count', 0),
                    'size': round(file.stat().st_size / (1024*1024), 2),
                    'path': str(file)
                })
        except:
            pass
    
    return jsonify(extractions)

# =====================================================
# ADVANCED FEATURES API ROUTES
# =====================================================

from .nexus.phone_extractor import (
    iOSExtractor, WhatsAppExtractor, FaceRecognizer, 
    ObjectDetector, CloudSync, MultiDeviceManager
)

# Initialize extractors
ios_extractor = None
whatsapp_extractor = None
face_recognizer = None
object_detector = None
cloud_sync = None
multi_device = None

# iOS Extraction
@app.route('/api/nexus/ios/backups')
def nexus_ios_backups():
    """List iOS backups"""
    global ios_extractor
    if ios_extractor is None:
        ios_extractor = iOSExtractor()
    
    backups = ios_extractor.find_backups()
    return jsonify({'backups': backups})

@app.route('/api/nexus/ios/extract/sms', methods=['POST'])
def nexus_ios_extract_sms():
    """Extract iMessages from iOS backup"""
    global ios_extractor
    if ios_extractor is None:
        ios_extractor = iOSExtractor()
    
    data = request.json or {}
    backup_id = data.get('backup_id')
    
    if not backup_id:
        return jsonify({'success': False, 'error': 'backup_id required'})
    
    result = ios_extractor.extract_sms(backup_id)
    return jsonify(result)

# WhatsApp Extraction
@app.route('/api/nexus/whatsapp/extract', methods=['POST'])
def nexus_whatsapp_extract():
    """Extract WhatsApp messages"""
    global whatsapp_extractor
    if whatsapp_extractor is None:
        whatsapp_extractor = WhatsAppExtractor()
    
    result = whatsapp_extractor.extract_messages()
    return jsonify(result)

@app.route('/api/nexus/whatsapp/media', methods=['POST'])
def nexus_whatsapp_media():
    """Extract WhatsApp media"""
    global whatsapp_extractor
    if whatsapp_extractor is None:
        whatsapp_extractor = WhatsAppExtractor()
    
    data = request.json or {}
    limit = data.get('limit', 50)
    
    result = whatsapp_extractor.extract_media(limit)
    return jsonify(result)

# Face Recognition
@app.route('/api/nexus/face/detect', methods=['POST'])
def nexus_face_detect():
    """Detect faces in image"""
    global face_recognizer
    if face_recognizer is None:
        face_recognizer = FaceRecognizer()
    
    data = request.json or {}
    image_path = data.get('path')
    
    if not image_path:
        return jsonify({'success': False, 'error': 'image path required'})
    
    result = face_recognizer.detect_faces(image_path)
    return jsonify(result)

@app.route('/api/nexus/face/recognize', methods=['POST'])
def nexus_face_recognize():
    """Recognize faces in image"""
    global face_recognizer
    if face_recognizer is None:
        face_recognizer = FaceRecognizer()
    
    data = request.json or {}
    image_path = data.get('path')
    
    if not image_path:
        return jsonify({'success': False, 'error': 'image path required'})
    
    result = face_recognizer.recognize_faces(image_path)
    return jsonify(result)

@app.route('/api/nexus/face/add', methods=['POST'])
def nexus_face_add():
    """Add known face"""
    global face_recognizer
    if face_recognizer is None:
        face_recognizer = FaceRecognizer()
    
    data = request.json or {}
    name = data.get('name')
    image_path = data.get('path')
    
    if not name or not image_path:
        return jsonify({'success': False, 'error': 'name and image path required'})
    
    result = face_recognizer.add_known_face(name, image_path)
    return jsonify(result)

# Object Detection
@app.route('/api/nexus/object/detect', methods=['POST'])
def nexus_object_detect():
    """Detect objects in image"""
    global object_detector
    if object_detector is None:
        object_detector = ObjectDetector()
    
    data = request.json or {}
    image_path = data.get('path')
    confidence = data.get('confidence', 0.5)
    
    if not image_path:
        return jsonify({'success': False, 'error': 'image path required'})
    
    result = object_detector.detect(image_path, confidence)
    return jsonify(result)

@app.route('/api/nexus/object/detect-folder', methods=['POST'])
def nexus_object_detect_folder():
    """Detect objects in folder of images"""
    global object_detector
    if object_detector is None:
        object_detector = ObjectDetector()
    
    data = request.json or {}
    folder_path = data.get('path')
    confidence = data.get('confidence', 0.5)
    
    if not folder_path:
        return jsonify({'success': False, 'error': 'folder path required'})
    
    result = object_detector.detect_in_folder(folder_path, confidence)
    return jsonify(result)

# Cloud Sync
@app.route('/api/nexus/cloud/sync', methods=['POST'])
def nexus_cloud_sync():
    """Sync file to cloud"""
    global cloud_sync
    if cloud_sync is None:
        cloud_sync = CloudSync()
    
    data = request.json or {}
    provider = data.get('provider', 's3')
    file_path = data.get('path')
    bucket = data.get('bucket')
    
    if not file_path:
        return jsonify({'success': False, 'error': 'file path required'})
    
    if provider == 's3':
        result = cloud_sync.sync_to_s3(bucket, file_path)
    elif provider == 'gdrive':
        result = cloud_sync.sync_to_google_drive(file_path)
    else:
        result = {'success': False, 'error': 'Unknown provider'}
    
    return jsonify(result)

@app.route('/api/nexus/cloud/auto-sync', methods=['POST'])
def nexus_cloud_auto_sync():
    """Auto-sync folder to cloud"""
    global cloud_sync
    if cloud_sync is None:
        cloud_sync = CloudSync()
    
    data = request.json or {}
    folder_path = data.get('path')
    provider = data.get('provider', 's3')
    bucket = data.get('bucket')
    
    if not folder_path:
        return jsonify({'success': False, 'error': 'folder path required'})
    
    result = cloud_sync.auto_sync_folder(folder_path, provider, bucket=bucket)
    return jsonify(result)

# Multi-Device
@app.route('/api/nexus/devices')
def nexus_devices():
    """List all connected devices"""
    global multi_device
    if multi_device is None:
        multi_device = MultiDeviceManager()
    
    devices = multi_device.list_devices()
    return jsonify({'devices': devices})

@app.route('/api/nexus/devices/extract', methods=['POST'])
def nexus_devices_extract():
    """Extract from all devices"""
    global multi_device
    if multi_device is None:
        multi_device = MultiDeviceManager()
    
    data = request.json or {}
    extraction_type = data.get('type', 'all')
    
    result = multi_device.extract_from_all(extraction_type)
    return jsonify(result)

@app.route('/api/nexus/devices/info')
def nexus_devices_info():
    """Get info from all devices"""
    global multi_device
    if multi_device is None:
        multi_device = MultiDeviceManager()
    
    # Refresh device list first
    multi_device.list_devices()
    result = multi_device.get_all_device_info()
    return jsonify(result)

# =====================================================
# COMPREHENSIVE ANDROID EXTRACTION API
# =====================================================

from .nexus.phone_extractor import AndroidFullExtractor

android_full_extractor = None

@app.route('/api/nexus/android/full', methods=['POST'])
def nexus_android_full():
    """Complete Android device extraction"""
    global android_full_extractor
    if android_full_extractor is None:
        android_full_extractor = AndroidFullExtractor()
    
    data = request.json or {}
    include_apps = data.get('include_apps', True)
    include_media = data.get('include_media', True)
    include_system = data.get('include_system', True)
    
    result = android_full_extractor.full_extraction(
        include_apps=include_apps,
        include_media=include_media,
        include_system=include_system
    )
    
    return jsonify(result)

@app.route('/api/nexus/android/apps')
def nexus_android_apps():
    """Extract installed apps"""
    global android_full_extractor
    if android_full_extractor is None:
        android_full_extractor = AndroidFullExtractor()
    
    result = android_full_extractor.extract_installed_apps()
    return jsonify(result)

@app.route('/api/nexus/android/browser')
def nexus_android_browser():
    """Extract browser history"""
    global android_full_extractor
    if android_full_extractor is None:
        android_full_extractor = AndroidFullExtractor()
    
    result = android_full_extractor.extract_browser_history()
    return jsonify(result)

@app.route('/api/nexus/android/call-recordings', methods=['POST'])
def nexus_android_call_recordings():
    """Extract call recordings"""
    global android_full_extractor
    if android_full_extractor is None:
        android_full_extractor = AndroidFullExtractor()
    
    result = android_full_extractor.extract_call_recordings()
    return jsonify(result)

@app.route('/api/nexus/android/voicemails', methods=['POST'])
def nexus_android_voicemails():
    """Extract voicemails"""
    global android_full_extractor
    if android_full_extractor is None:
        android_full_extractor = AndroidFullExtractor()
    
    result = android_full_extractor.extract_voicemails()
    return jsonify(result)

@app.route('/api/nexus/android/documents', methods=['POST'])
def nexus_android_documents():
    """Extract documents"""
    global android_full_extractor
    if android_full_extractor is None:
        android_full_extractor = AndroidFullExtractor()
    
    result = android_full_extractor.extract_documents()
    return jsonify(result)

@app.route('/api/nexus/android/wifi', methods=['POST'])
def nexus_android_wifi():
    """Extract WiFi passwords (requires root)"""
    global android_full_extractor
    if android_full_extractor is None:
        android_full_extractor = AndroidFullExtractor()
    
    result = android_full_extractor.extract_wifi_passwords()
    return jsonify(result)

@app.route('/api/nexus/android/clipboard')
def nexus_android_clipboard():
    """Extract clipboard content"""
    global android_full_extractor
    if android_full_extractor is None:
        android_full_extractor = AndroidFullExtractor()
    
    result = android_full_extractor.extract_clipboard()
    return jsonify(result)

@app.route('/api/nexus/android/videos', methods=['POST'])
def nexus_android_videos():
    """Extract videos"""
    global android_full_extractor
    if android_full_extractor is None:
        android_full_extractor = AndroidFullExtractor()
    
    result = android_full_extractor.extract_videos()
    return jsonify(result)

@app.route('/api/nexus/android/audio', methods=['POST'])
def nexus_android_audio():
    """Extract audio files"""
    global android_full_extractor
    if android_full_extractor is None:
        android_full_extractor = AndroidFullExtractor()
    
    result = android_full_extractor.extract_audio()
    return jsonify(result)

@app.route('/api/nexus/android/dcim', methods=['POST'])
def nexus_android_dcim():
    """Extract DCIM (camera) folder"""
    global android_full_extractor
    if android_full_extractor is None:
        android_full_extractor = AndroidFullExtractor()
    
    result = android_full_extractor.extract_dcim()
    return jsonify(result)

@app.route('/api/nexus/android/build-prop')
def nexus_android_build_prop():
    """Extract build.prop system info"""
    global android_full_extractor
    if android_full_extractor is None:
        android_full_extractor = AndroidFullExtractor()
    
    result = android_full_extractor.extract_build_prop()
    return jsonify(result)

@app.route('/api/nexus/android/permissions')
def nexus_android_permissions():
    """Extract app permissions"""
    global android_full_extractor
    if android_full_extractor is None:
        android_full_extractor = AndroidFullExtractor()
    
    result = android_full_extractor.extract_app_permissions()
    return jsonify(result)

# =====================================================
# ULTRA-COMPREHENSIVE ANDROID EXTRACTION API
# =====================================================

from .nexus.phone_extractor import UltraAndroidExtractor

ultra_extractor = None

@app.route('/api/nexus/android/ultra', methods=['POST'])
def nexus_android_ultra():
    """ULTRA-COMPREHENSIVE Android extraction - EVERYTHING"""
    global ultra_extractor
    if ultra_extractor is None:
        ultra_extractor = UltraAndroidExtractor()
    
    result = ultra_extractor.ultra_extraction()
    return jsonify(result)
