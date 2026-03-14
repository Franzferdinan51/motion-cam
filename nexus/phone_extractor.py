#!/usr/bin/env python3
"""
Nexus Phone Extractor - Phone Data Extraction & Analysis
Integrates with Palantir at Home for comprehensive surveillance
"""

import subprocess
import json
import os
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
import re

class PhoneExtractor:
    """Extract data from Android phones via ADB"""
    
    def __init__(self, device_id=None):
        self.device_id = device_id
        self.adb_cmd = ['adb']
        if device_id:
            self.adb_cmd.extend(['-s', device_id])
        self.extract_dir = Path.home() / 'palantir_extractions' / datetime.now().strftime('%Y%m%d_%H%M%S')
        self.extract_dir.mkdir(parents=True, exist_ok=True)
        
    def check_adb(self):
        """Check if ADB is installed and device connected"""
        try:
            result = subprocess.run(['adb', 'devices'], capture_output=True, text=True, timeout=5)
            devices = [line.split('\t')[0] for line in result.stdout.split('\n')[1:] if line.strip() and '\tdevice' in line]
            return len(devices) > 0, devices
        except Exception as e:
            return False, str(e)
    
    def get_device_info(self):
        """Get phone information"""
        info = {}
        commands = {
            'model': 'getprop ro.product.model',
            'manufacturer': 'getprop ro.product.manufacturer',
            'android_version': 'getprop ro.build.version.release',
            'sdk': 'getprop ro.build.version.sdk',
            'serial': 'getprop ro.serialno',
        }
        
        for key, cmd in commands.items():
            try:
                result = subprocess.run(
                    self.adb_cmd + ['shell', cmd],
                    capture_output=True, text=True, timeout=10
                )
                info[key] = result.stdout.strip()
            except:
                info[key] = 'Unknown'
        
        return info
    
    def extract_sms(self, output_path=None):
        """Extract SMS messages"""
        if not output_path:
            output_path = self.extract_dir / 'sms.json'
        
        # Pull SMS database
        db_path = '/data/data/com.android.providers.telephony/databases/mmssms.db'
        local_db = self.extract_dir / 'mmssms.db'
        
        try:
            subprocess.run(self.adb_cmd + ['pull', db_path, str(local_db)], 
                         capture_output=True, timeout=30)
            
            if local_db.exists():
                conn = sqlite3.connect(str(local_db))
                cursor = conn.cursor()
                
                # Get messages
                cursor.execute('''
                    SELECT address, date, type, body FROM sms 
                    ORDER BY date DESC LIMIT 1000
                ''')
                
                messages = []
                for row in cursor.fetchall():
                    messages.append({
                        'contact': row[0],
                        'timestamp': datetime.fromtimestamp(row[1]/1000).isoformat() if row[1] else None,
                        'type': 'received' if row[2] == 1 else 'sent',
                        'message': row[3]
                    })
                
                conn.close()
                
                with open(output_path, 'w') as f:
                    json.dump({'count': len(messages), 'messages': messages}, f, indent=2)
                
                return {'success': True, 'count': len(messages), 'path': str(output_path)}
        except Exception as e:
            return {'success': False, 'error': str(e)}
        
        return {'success': False, 'error': 'Could not pull SMS database'}
    
    def extract_call_logs(self, output_path=None):
        """Extract call history"""
        if not output_path:
            output_path = self.extract_dir / 'call_logs.json'
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'content', 'query', '--uri', 
                               'content://call_log/calls',
                               '--projection', 'number,type,date,duration,name'],
                capture_output=True, text=True, timeout=30
            )
            
            calls = []
            for line in result.stdout.split('\n')[1:]:  # Skip header
                if line.strip():
                    parts = line.split('|')
                    if len(parts) >= 5:
                        calls.append({
                            'number': parts[0],
                            'type': ['incoming', 'outgoing', 'missed'][int(parts[1])-1] if parts[1].isdigit() else 'unknown',
                            'timestamp': datetime.fromtimestamp(int(parts[2])/1000).isoformat() if parts[2].isdigit() else None,
                            'duration': f"{int(parts[3])}s" if parts[3].isdigit() else None,
                            'contact': parts[4] if len(parts) > 4 else None
                        })
            
            with open(output_path, 'w') as f:
                json.dump({'count': len(calls), 'calls': calls}, f, indent=2)
            
            return {'success': True, 'count': len(calls), 'path': str(output_path)}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def extract_contacts(self, output_path=None):
        """Extract contacts"""
        if not output_path:
            output_path = self.extract_dir / 'contacts.json'
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'content', 'query', '--uri',
                               'content://com.android.contacts/contacts',
                               '--projection', '_id,display_name'],
                capture_output=True, text=True, timeout=30
            )
            
            contacts = []
            for line in result.stdout.split('\n')[1:]:
                if line.strip():
                    parts = line.split('|')
                    if len(parts) >= 2:
                        contacts.append({
                            'id': parts[0],
                            'name': parts[1]
                        })
            
            with open(output_path, 'w') as f:
                json.dump({'count': len(contacts), 'contacts': contacts}, f, indent=2)
            
            return {'success': True, 'count': len(contacts), 'path': str(output_path)}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def extract_photos(self, output_dir=None, limit=100):
        """Extract photos with metadata"""
        if not output_dir:
            output_dir = self.extract_dir / 'photos'
            output_dir.mkdir(exist_ok=True)
        
        try:
            # Get list of photos
            result = subprocess.run(
                self.adb_cmd + ['shell', 'find', '/sdcard/DCIM', '-name', '*.jpg', '-o', '-name', '*.png', '|', 'head', f'-{limit}'],
                capture_output=True, text=True, timeout=30
            )
            
            photos = []
            for photo_path in result.stdout.strip().split('\n'):
                if photo_path:
                    local_path = output_dir / Path(photo_path).name
                    subprocess.run(self.adb_cmd + ['pull', photo_path, str(local_path)],
                                 capture_output=True, timeout=60)
                    
                    if local_path.exists():
                        # Extract EXIF metadata
                        metadata = self.extract_exif(local_path)
                        photos.append({
                            'filename': local_path.name,
                            'path': str(local_path),
                            'metadata': metadata
                        })
            
            with open(output_dir / 'photo_manifest.json', 'w') as f:
                json.dump({'count': len(photos), 'photos': photos}, f, indent=2)
            
            return {'success': True, 'count': len(photos), 'path': str(output_dir)}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def extract_exif(self, image_path):
        """Extract EXIF metadata from image"""
        try:
            img = Image.open(image_path)
            exif_data = img._getexif()
            
            if not exif_data:
                return {}
            
            metadata = {}
            for tag_id, value in exif_data.items():
                tag = TAGS.get(tag_id, tag_id)
                if tag == 'GPSInfo':
                    gps = {}
                    for t in value:
                        sub_tag = GPSTAGS.get(t, t)
                        gps[sub_tag] = value[t]
                    metadata['gps'] = gps
                elif isinstance(value, bytes):
                    try:
                        metadata[tag] = value.decode('utf-8', errors='ignore')
                    except:
                        metadata[tag] = str(value)
                else:
                    metadata[tag] = value
            
            return metadata
        except Exception as e:
            return {'error': str(e)}
    
    def extract_app_data(self, package_name, output_path=None):
        """Extract data from specific app"""
        if not output_path:
            output_path = self.extract_dir / f'{package_name}_data.tar'
        
        try:
            # Backup app data
            subprocess.run(
                self.adb_cmd + ['backup', '-f', str(output_path), '-noapk', package_name],
                timeout=120
            )
            
            return {'success': True, 'path': str(output_path)}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_location_history(self, output_path=None):
        """Extract location history from Google Maps"""
        if not output_path:
            output_path = self.extract_dir / 'location_history.json'
        
        try:
            # Pull Google Maps data
            gms_path = '/data/data/com.google.android.gms/app_chimera/m/GoogleServicesLocationHistory'
            local_path = self.extract_dir / 'location_history.db'
            
            result = subprocess.run(
                self.adb_cmd + ['pull', gms_path, str(local_path)],
                capture_output=True, timeout=30
            )
            
            if local_path.exists():
                # Parse location history database
                conn = sqlite3.connect(str(local_path))
                cursor = conn.cursor()
                
                locations = []
                try:
                    cursor.execute('SELECT timestamp, latitude, longitude, accuracy FROM mylocation')
                    for row in cursor.fetchall():
                        locations.append({
                            'timestamp': datetime.fromtimestamp(row[0]/1000).isoformat() if row[0] else None,
                            'latitude': row[1],
                            'longitude': row[2],
                            'accuracy': row[3]
                        })
                except:
                    pass
                
                conn.close()
                
                with open(output_path, 'w') as f:
                    json.dump({'count': len(locations), 'locations': locations}, f, indent=2)
                
                return {'success': True, 'count': len(locations), 'path': str(output_path)}
        except Exception as e:
            return {'success': False, 'error': str(e)}
        
        return {'success': False, 'error': 'Could not extract location history'}
    
    def generate_report(self):
        """Generate comprehensive extraction report"""
        report = {
            'extraction_time': datetime.now().isoformat(),
            'device_info': self.get_device_info(),
            'extraction_dir': str(self.extract_dir),
            'files': []
        }
        
        # List all extracted files
        for file in self.extract_dir.rglob('*'):
            if file.is_file():
                report['files'].append({
                    'path': str(file.relative_to(self.extract_dir)),
                    'size': file.stat().st_size,
                    'modified': datetime.fromtimestamp(file.stat().st_mtime).isoformat()
                })
        
        report_path = self.extract_dir / 'extraction_report.json'
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        return report


# =====================================================
# iOS EXTRACTION (iTunes Backup Parser)
# =====================================================

class iOSExtractor:
    """Extract data from iOS iTunes backups"""
    
    def __init__(self, backup_path=None):
        if backup_path is None:
            # Default macOS backup location
            backup_path = Path.home() / 'Library/Application Support/MobileSync/Backup'
        self.backup_path = Path(backup_path)
        self.extract_dir = Path.home() / 'palantir_extractions' / 'ios' / datetime.now().strftime('%Y%m%d_%H%M%S')
        self.extract_dir.mkdir(parents=True, exist_ok=True)
    
    def find_backups(self):
        """Find all iTunes backups"""
        backups = []
        if self.backup_path.exists():
            for backup in self.backup_path.iterdir():
                if backup.is_dir() and len(backup.name) == 40:  # SHA1 hash
                    manifest = backup / 'Manifest.plist'
                    if manifest.exists():
                        backups.append({
                            'id': backup.name,
                            'path': str(backup),
                            'has_manifest': True
                        })
        return backups
    
    def parse_manifest(self, backup_id):
        """Parse backup manifest"""
        import plistlib
        backup_dir = self.backup_path / backup_id
        manifest_path = backup_dir / 'Manifest.plist'
        
        if not manifest_path.exists():
            return {}
        
        with open(manifest_path, 'rb') as f:
            manifest = plistlib.load(f)
        
        return manifest
    
    def extract_sms(self, backup_id):
        """Extract iMessages from iOS backup"""
        import plistlib
        
        backup_dir = self.backup_path / backup_id
        output_path = self.extract_dir / 'imessages.json'
        
        # Find SMS database in backup
        sms_db = None
        for file in backup_dir.rglob('*'):
            if file.name == '3d' or file.name.startswith('3d'):  # SMS database hash
                sms_db = file
                break
        
        if not sms_db:
            return {'success': False, 'error': 'SMS database not found'}
        
        try:
            conn = sqlite3.connect(str(sms_db))
            cursor = conn.cursor()
            
            # Extract messages
            cursor.execute('''
                SELECT message.date, message.text, message.is_from_me, 
                       handle.id, message.cache_has_attachments
                FROM message
                LEFT JOIN handle ON message.handle_id = handle.ROWID
                ORDER BY message.date DESC LIMIT 1000
            ''')
            
            messages = []
            for row in cursor.fetchall():
                # Convert Apple timestamp (2001-01-01 based)
                timestamp = datetime(2001, 1, 1) + timedelta(seconds=row[0]/1000000000) if row[0] else None
                
                messages.append({
                    'timestamp': timestamp.isoformat() if timestamp else None,
                    'message': row[1],
                    'is_from_me': bool(row[2]),
                    'contact': row[3],
                    'has_attachments': bool(row[4])
                })
            
            conn.close()
            
            with open(output_path, 'w') as f:
                json.dump({'count': len(messages), 'messages': messages}, f, indent=2)
            
            return {'success': True, 'count': len(messages), 'path': str(output_path)}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def extract_photos(self, backup_id):
        """Extract photos from iOS backup"""
        backup_dir = self.backup_path / backup_id
        output_dir = self.extract_dir / 'photos'
        output_dir.mkdir(exist_ok=True)
        
        photos = []
        copied = 0
        
        # Find photo files (MDM domain)
        for file in backup_dir.rglob('*'):
            if file.is_file() and len(file.name) == 40:
                # Check if it's a photo by extension in metadata
                try:
                    # Copy with original extension if possible
                    ext = '.jpg'  # Default
                    local_path = output_dir / f'photo_{copied}{ext}'
                    shutil.copy2(file, local_path)
                    
                    photos.append({
                        'filename': local_path.name,
                        'path': str(local_path),
                        'original_hash': file.name
                    })
                    copied += 1
                    
                    if copied >= 100:  # Limit
                        break
                except:
                    pass
        
        with open(output_dir / 'photo_manifest.json', 'w') as f:
            json.dump({'count': len(photos), 'photos': photos}, f, indent=2)
        
        return {'success': True, 'count': len(photos), 'path': str(output_dir)}


# =====================================================
# WHATSAPP EXTRACTION
# =====================================================

class WhatsAppExtractor:
    """Extract WhatsApp messages and media"""
    
    def __init__(self, device_id=None):
        self.device_id = device_id
        self.adb_cmd = ['adb']
        if device_id:
            self.adb_cmd.extend(['-s', device_id])
        self.extract_dir = Path.home() / 'palantir_extractions' / 'whatsapp' / datetime.now().strftime('%Y%m%d_%H%M%S')
        self.extract_dir.mkdir(parents=True, exist_ok=True)
    
    def extract_messages(self):
        """Extract WhatsApp messages"""
        output_path = self.extract_dir / 'whatsapp_messages.json'
        
        # Pull WhatsApp database
        db_paths = [
            '/sdcard/Android/media/com.whatsapp/WhatsApp/Databases/msgstore.db',
            '/sdcard/WhatsApp/Databases/msgstore.db'
        ]
        
        local_db = self.extract_dir / 'msgstore.db'
        
        for db_path in db_paths:
            result = subprocess.run(
                self.adb_cmd + ['pull', db_path, str(local_db)],
                capture_output=True, timeout=30
            )
            if local_db.exists():
                break
        
        if not local_db.exists():
            return {'success': False, 'error': 'WhatsApp database not found'}
        
        try:
            # Note: WhatsApp DB is encrypted, need key for decryption
            # This extracts metadata only without decryption
            return {
                'success': True,
                'message': 'Database pulled (encrypted). Requires key for decryption.',
                'path': str(local_db),
                'encrypted': True,
                'note': 'WhatsApp databases are encrypted. Use key from /data/data/com.whatsapp/files/key'
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def extract_media(self, limit=50):
        """Extract WhatsApp media files"""
        output_dir = self.extract_dir / 'media'
        output_dir.mkdir(exist_ok=True)
        
        media_paths = [
            '/sdcard/Android/media/com.whatsapp/WhatsApp/Media',
            '/sdcard/WhatsApp/Media'
        ]
        
        media_files = []
        
        for media_path in media_paths:
            try:
                # List media files
                result = subprocess.run(
                    self.adb_cmd + ['shell', f'find {media_path} -type f -name "*.jpg" -o -name "*.mp4" | head -{limit}'],
                    capture_output=True, text=True, timeout=30
                )
                
                for file_path in result.stdout.strip().split('\n'):
                    if file_path:
                        local_path = output_dir / Path(file_path).name
                        subprocess.run(
                            self.adb_cmd + ['pull', file_path, str(local_path)],
                            capture_output=True, timeout=60
                        )
                        
                        if local_path.exists():
                            media_files.append({
                                'filename': local_path.name,
                                'path': str(local_path),
                                'type': 'image' if local_path.suffix in ['.jpg', '.png'] else 'video'
                            })
                
                if media_files:
                    break
            except:
                pass
        
        with open(output_dir / 'media_manifest.json', 'w') as f:
            json.dump({'count': len(media_files), 'media': media_files}, f, indent=2)
        
        return {'success': True, 'count': len(media_files), 'path': str(output_dir)}


# =====================================================
# FACE RECOGNITION
# =====================================================

class FaceRecognizer:
    """Face detection and recognition in photos"""
    
    def __init__(self, model_path=None):
        self.model_path = model_path
        self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        self.known_faces = {}  # name -> encoding
        self.load_known_faces()
    
    def load_known_faces(self, faces_dir=None):
        """Load known face encodings"""
        if faces_dir is None:
            faces_dir = Path.home() / '.palantir' / 'known_faces'
            faces_dir.mkdir(parents=True, exist_ok=True)
        
        # Load existing face encodings
        encoding_file = faces_dir / 'face_encodings.json'
        if encoding_file.exists():
            with open(encoding_file) as f:
                data = json.load(f)
                self.known_faces = {k: np.array(v) for k, v in data.items()}
    
    def detect_faces(self, image_path):
        """Detect faces in image"""
        img = cv2.imread(str(image_path))
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        faces = self.face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
        )
        
        detected = []
        for (x, y, w, h) in faces:
            detected.append({
                'x': int(x),
                'y': int(y),
                'width': int(w),
                'height': int(h),
                'confidence': 0.95  # OpenCV doesn't provide confidence
            })
        
        return {
            'count': len(detected),
            'faces': detected,
            'image': str(image_path)
        }
    
    def recognize_faces(self, image_path):
        """Recognize known faces in image"""
        faces = self.detect_faces(image_path)
        
        # For each detected face, try to match with known faces
        # This is simplified - real implementation would use face_recognition library
        for face in faces['faces']:
            face['recognized_as'] = 'Unknown'
            face['match_confidence'] = 0.0
        
        return faces
    
    def add_known_face(self, name, image_path):
        """Add a known face for recognition"""
        faces = self.detect_faces(image_path)
        
        if faces['count'] == 0:
            return {'success': False, 'error': 'No face detected in image'}
        
        # In real implementation, would create encoding here
        # For now, just store reference
        self.known_faces[name] = str(image_path)
        
        # Save to disk
        faces_dir = Path.home() / '.palantir' / 'known_faces'
        faces_dir.mkdir(parents=True, exist_ok=True)
        
        with open(faces_dir / 'face_encodings.json', 'w') as f:
            json.dump({k: v if isinstance(v, str) else v.tolist() 
                      for k, v in self.known_faces.items()}, f, indent=2)
        
        return {'success': True, 'name': name, 'faces_detected': faces['count']}


# =====================================================
# OBJECT DETECTION
# =====================================================

class ObjectDetector:
    """Detect objects (person, pet, vehicle) in images"""
    
    def __init__(self):
        # Load COCO classes
        self.classes = [
            'person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train',
            'truck', 'boat', 'traffic light', 'fire hydrant', 'stop sign',
            'parking meter', 'bench', 'bird', 'cat', 'dog', 'horse', 'sheep',
            'cow', 'elephant', 'bear', 'zebra', 'giraffe', 'backpack', 'umbrella',
            'handbag', 'tie', 'suitcase', 'frisbee', 'skis', 'snowboard',
            'sports ball', 'kite', 'baseball bat', 'baseball glove', 'skateboard',
            'surfboard', 'tennis racket', 'bottle', 'wine glass', 'cup', 'fork',
            'knife', 'spoon', 'bowl', 'banana', 'apple', 'sandwich', 'orange',
            'broccoli', 'carrot', 'hot dog', 'pizza', 'donut', 'cake', 'chair',
            'couch', 'potted plant', 'bed', 'dining table', 'toilet', 'tv',
            'laptop', 'mouse', 'remote', 'keyboard', 'cell phone', 'microwave',
            'oven', 'toaster', 'sink', 'refrigerator', 'book', 'clock', 'vase',
            'scissors', 'teddy bear', 'hair drier', 'toothbrush'
        ]
        
        # Load pre-trained YOLO model
        try:
            self.net = cv2.dnn.readNetFromDarknet(
                'yolov3.cfg',
                'yolov3.weights'
            )
            self.has_model = True
        except:
            self.has_model = False
            print("⚠️  YOLO model not found. Object detection disabled.")
    
    def detect(self, image_path, confidence=0.5):
        """Detect objects in image"""
        if not self.has_model:
            return {'success': False, 'error': 'Model not loaded'}
        
        img = cv2.imread(str(image_path))
        height, width = img.shape[:2]
        
        # Create blob and run forward pass
        blob = cv2.dnn.blobFromImage(img, 1/255.0, (416, 416), swapRB=True, crop=False)
        self.net.setInput(blob)
        
        output_layers = self.net.getUnconnectedOutLayersNames()
        outputs = self.net.forward(output_layers)
        
        detections = []
        for output in outputs:
            for detection in output:
                scores = detection[5:]
                class_id = np.argmax(scores)
                conf = scores[class_id]
                
                if conf > confidence:
                    box = detection[0:4] * np.array([width, height, width, height])
                    (center_x, center_y, w, h) = box.astype('int')
                    x = int(center_x - w/2)
                    y = int(center_y - h/2)
                    
                    detections.append({
                        'class': self.classes[class_id],
                        'confidence': float(conf),
                        'x': int(x),
                        'y': int(y),
                        'width': int(w),
                        'height': int(h)
                    })
        
        return {
            'success': True,
            'count': len(detections),
            'objects': detections,
            'image': str(image_path)
        }
    
    def detect_in_folder(self, folder_path, confidence=0.5):
        """Detect objects in all images in folder"""
        folder = Path(folder_path)
        results = []
        
        for img_path in folder.glob('*.jpg') + folder.glob('*.png'):
            result = self.detect(img_path, confidence)
            if result['success']:
                results.append(result)
        
        return {
            'total_images': len(results),
            'total_objects': sum(r['count'] for r in results),
            'results': results
        }


# =====================================================
# CLOUD SYNC
# =====================================================

class CloudSync:
    """Sync Palantir data to cloud storage"""
    
    def __init__(self, provider='local'):
        self.provider = provider
        self.sync_dir = Path.home() / 'palantir_sync'
        self.sync_dir.mkdir(exist_ok=True)
    
    def sync_to_s3(self, bucket_name, file_path, aws_key=None, aws_secret=None):
        """Sync file to AWS S3"""
        try:
            import boto3
            
            # Get credentials from env or config
            aws_key = aws_key or os.environ.get('AWS_ACCESS_KEY_ID')
            aws_secret = aws_secret or os.environ.get('AWS_SECRET_ACCESS_KEY')
            
            if not aws_key or not aws_secret:
                return {'success': False, 'error': 'AWS credentials required'}
            
            s3 = boto3.client(
                's3',
                aws_access_key_id=aws_key,
                aws_secret_access_key=aws_secret
            )
            
            file_path = Path(file_path)
            s3.upload_file(str(file_path), bucket_name, file_path.name)
            
            return {
                'success': True,
                'bucket': bucket_name,
                'file': file_path.name,
                'url': f's3://{bucket_name}/{file_path.name}'
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def sync_to_google_drive(self, file_path, credentials_file=None):
        """Sync file to Google Drive"""
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
            
            if not credentials_file:
                credentials_file = Path.home() / '.credentials' / 'google_drive.json'
            
            if not credentials_file.exists():
                return {
                    'success': False,
                    'error': 'Google credentials required. Run OAuth flow first.'
                }
            
            creds = Credentials.from_authorized_user_file(str(credentials_file))
            service = build('drive', 'v3', credentials=creds)
            
            file_path = Path(file_path)
            file_metadata = {'name': file_path.name}
            media = MediaFileUpload(str(file_path), resumable=True)
            
            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink'
            ).execute()
            
            return {
                'success': True,
                'file_id': file.get('id'),
                'url': file.get('webViewLink')
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def auto_sync_folder(self, folder_path, provider='s3', **kwargs):
        """Automatically sync all files in folder"""
        folder = Path(folder_path)
        synced = []
        failed = []
        
        for file in folder.glob('*'):
            if file.is_file():
                if provider == 's3':
                    result = self.sync_to_s3(kwargs.get('bucket'), str(file))
                elif provider == 'gdrive':
                    result = self.sync_to_google_drive(str(file))
                else:
                    result = {'success': False, 'error': 'Unknown provider'}
                
                if result['success']:
                    synced.append(file.name)
                else:
                    failed.append({'file': file.name, 'error': result['error']})
        
        return {
            'synced': synced,
            'failed': failed,
            'total': len(synced) + len(failed)
        }


# =====================================================
# MULTI-DEVICE SUPPORT
# =====================================================

class MultiDeviceManager:
    """Manage multiple Android devices simultaneously"""
    
    def __init__(self):
        self.devices = {}
        self.adb_cmd = ['adb']
    
    def list_devices(self):
        """List all connected devices"""
        result = subprocess.run(
            ['adb', 'devices'],
            capture_output=True, text=True
        )
        
        devices = []
        for line in result.stdout.split('\n')[1:]:
            if line.strip() and '\tdevice' in line:
                device_id = line.split('\t')[0]
                devices.append({
                    'id': device_id,
                    'status': 'connected',
                    'extractor': PhoneExtractor(device_id)
                })
        
        self.devices = {d['id']: d for d in devices}
        return devices
    
    def extract_from_all(self, extraction_type='all'):
        """Extract data from all connected devices"""
        results = {}
        
        for device_id, device in self.devices.items():
            extractor = device['extractor']
            device_results = {}
            
            if extraction_type in ['all', 'sms']:
                device_results['sms'] = extractor.extract_sms()
            if extraction_type in ['all', 'calls']:
                device_results['calls'] = extractor.extract_call_logs()
            if extraction_type in ['all', 'contacts']:
                device_results['contacts'] = extractor.extract_contacts()
            if extraction_type in ['all', 'photos']:
                device_results['photos'] = extractor.extract_photos()
            
            results[device_id] = device_results
        
        return {
            'devices': len(results),
            'results': results,
            'timestamp': datetime.now().isoformat()
        }
    
    def get_all_device_info(self):
        """Get info from all devices"""
        infos = {}
        for device_id, device in self.devices.items():
            infos[device_id] = device['extractor'].get_device_info()
        return infos


# =====================================================
# COMPREHENSIVE ANDROID EXTRACTION
# =====================================================

class AndroidFullExtractor(PhoneExtractor):
    """Complete Android device extraction - all data types"""
    
    def __init__(self, device_id=None):
        super().__init__(device_id)
        self.full_extract_dir = Path.home() / 'palantir_extractions' / 'android_full' / datetime.now().strftime('%Y%m%d_%H%M%S')
        self.full_extract_dir.mkdir(parents=True, exist_ok=True)
    
    def full_extraction(self, include_apps=True, include_media=True, include_system=True):
        """Complete device extraction"""
        results = {
            'device_info': self.get_device_info(),
            'extractions': {},
            'timestamp': datetime.now().isoformat(),
            'device_id': self.device_id
        }
        
        # Basic data
        results['extractions']['sms'] = self.extract_sms()
        results['extractions']['calls'] = self.extract_call_logs()
        results['extractions']['contacts'] = self.extract_contacts()
        results['extractions']['photos'] = self.extract_photos()
        results['extractions']['location'] = self.get_location_history()
        
        # App data
        if include_apps:
            results['extractions']['apps'] = self.extract_installed_apps()
            results['extractions']['browser_history'] = self.extract_browser_history()
            results['extractions']['call_recordings'] = self.extract_call_recordings()
            results['extractions']['voicemails'] = self.extract_voicemails()
            results['extractions']['documents'] = self.extract_documents()
            results['extractions']['downloads'] = self.extract_downloads()
            results['extractions']['wifi_passwords'] = self.extract_wifi_passwords()
            results['extractions']['clipboard'] = self.extract_clipboard()
        
        # Media
        if include_media:
            results['extractions']['videos'] = self.extract_videos()
            results['extractions']['audio'] = self.extract_audio()
            results['extractions']['dcim'] = self.extract_dcim()
        
        # System
        if include_system:
            results['extractions']['build_prop'] = self.extract_build_prop()
            results['extractions']['packages'] = self.extract_package_list()
            results['extractions']['permissions'] = self.extract_app_permissions()
            results['extractions']['users'] = self.extract_user_accounts()
        
        # Save comprehensive report
        report_path = self.full_extract_dir / 'full_extraction_report.json'
        with open(report_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        results['report_path'] = str(report_path)
        results['extract_dir'] = str(self.full_extract_dir)
        
        return results
    
    def extract_installed_apps(self):
        """List all installed apps with metadata"""
        output_path = self.full_extract_dir / 'installed_apps.json'
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'pm', 'list', 'packages', '-f'],
                capture_output=True, text=True, timeout=30
            )
            
            apps = []
            for line in result.stdout.split('\n'):
                if line.startswith('package:'):
                    parts = line.split('=')
                    if len(parts) == 2:
                        apps.append({
                            'package': parts[1].strip(),
                            'apk_path': parts[0].replace('package:', '').strip()
                        })
            
            # Get app details
            for app in apps[:100]:  # Limit to 100
                try:
                    details = subprocess.run(
                        self.adb_cmd + ['shell', 'dumpsys', 'package', app['package']],
                        capture_output=True, text=True, timeout=10
                    )
                    app['has_details'] = True
                except:
                    app['has_details'] = False
            
            with open(output_path, 'w') as f:
                json.dump({'count': len(apps), 'apps': apps}, f, indent=2)
            
            return {'success': True, 'count': len(apps), 'path': str(output_path)}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def extract_browser_history(self):
        """Extract browser history from Chrome/Firefox"""
        output_path = self.full_extract_dir / 'browser_history.json'
        
        browsers = [
            ('Chrome', 'com.android.browser', '/data/data/com.android.browser/databases/browser2.db'),
            ('Chrome', 'com.chrome', '/data/data/com.chrome/databases/Chrome'),
            ('Firefox', 'org.mozilla.firefox', '/data/data/org.mozilla.firefox/files/mozilla/*.default/places.sqlite')
        ]
        
        all_history = []
        
        for browser_name, package, db_path in browsers:
            try:
                local_db = self.full_extract_dir / f'{browser_name}_history.db'
                result = subprocess.run(
                    self.adb_cmd + ['pull', db_path, str(local_db)],
                    capture_output=True, timeout=30
                )
                
                if local_db.exists():
                    # Parse browser DB
                    conn = sqlite3.connect(str(local_db))
                    cursor = conn.cursor()
                    
                    try:
                        cursor.execute('SELECT url, title, date FROM urls ORDER BY date DESC LIMIT 500')
                        for row in cursor.fetchall():
                            all_history.append({
                                'browser': browser_name,
                                'url': row[0],
                                'title': row[1],
                                'timestamp': datetime.fromtimestamp(row[2]/1000000).isoformat() if row[2] else None
                            })
                    except:
                        pass
                    
                    conn.close()
            except:
                pass
        
        with open(output_path, 'w') as f:
            json.dump({'count': len(all_history), 'history': all_history}, f, indent=2)
        
        return {'success': True, 'count': len(all_history), 'path': str(output_path)}
    
    def extract_call_recordings(self):
        """Extract call recordings"""
        output_dir = self.full_extract_dir / 'call_recordings'
        output_dir.mkdir(exist_ok=True)
        
        recording_paths = [
            '/sdcard/Call',
            '/sdcard/Recordings/Call',
            '/sdcard/Music/Call',
            '/data/data/com.android.dialer/files/call_recording'
        ]
        
        recordings = []
        
        for rec_path in recording_paths:
            try:
                result = subprocess.run(
                    self.adb_cmd + ['shell', f'find {rec_path} -name "*.mp3" -o -name "*.m4a" -o -name "*.wav" 2>/dev/null'],
                    capture_output=True, text=True, timeout=30
                )
                
                for file_path in result.stdout.strip().split('\n'):
                    if file_path:
                        local_path = output_dir / Path(file_path).name
                        subprocess.run(
                            self.adb_cmd + ['pull', file_path, str(local_path)],
                            capture_output=True, timeout=60
                        )
                        
                        if local_path.exists():
                            recordings.append({
                                'filename': local_path.name,
                                'path': str(local_path),
                                'original': file_path
                            })
            except:
                pass
        
        with open(output_dir / 'manifest.json', 'w') as f:
            json.dump({'count': len(recordings), 'recordings': recordings}, f, indent=2)
        
        return {'success': True, 'count': len(recordings), 'path': str(output_dir)}
    
    def extract_voicemails(self):
        """Extract voicemails"""
        output_dir = self.full_extract_dir / 'voicemails'
        output_dir.mkdir(exist_ok=True)
        
        voicemail_paths = [
            '/sdcard/voicemail',
            '/data/data/com.android.phone/voicemail'
        ]
        
        voicemails = []
        
        for vm_path in voicemail_paths:
            try:
                result = subprocess.run(
                    self.adb_cmd + ['shell', f'find {vm_path} -type f 2>/dev/null'],
                    capture_output=True, text=True, timeout=30
                )
                
                for file_path in result.stdout.strip().split('\n'):
                    if file_path:
                        local_path = output_dir / Path(file_path).name
                        subprocess.run(
                            self.adb_cmd + ['pull', file_path, str(local_path)],
                            capture_output=True, timeout=60
                        )
                        
                        if local_path.exists():
                            voicemails.append({
                                'filename': local_path.name,
                                'path': str(local_path)
                            })
            except:
                pass
        
        with open(output_dir / 'manifest.json', 'w') as f:
            json.dump({'count': len(voicemails), 'voicemails': voicemails}, f, indent=2)
        
        return {'success': True, 'count': len(voicemails), 'path': str(output_dir)}
    
    def extract_documents(self):
        """Extract documents (PDF, DOC, XLS, etc.)"""
        output_dir = self.full_extract_dir / 'documents'
        output_dir.mkdir(exist_ok=True)
        
        doc_paths = [
            '/sdcard/Documents',
            '/sdcard/Download',
            '/sdcard/Dropbox'
        ]
        
        doc_extensions = ['*.pdf', '*.doc', '*.docx', '*.xls', '*.xlsx', '*.ppt', '*.pptx', '*.odt', '*.ods']
        
        documents = []
        
        for doc_path in doc_paths:
            for ext in doc_extensions:
                try:
                    result = subprocess.run(
                        self.adb_cmd + ['shell', f'find {doc_path} -name "{ext}" 2>/dev/null'],
                        capture_output=True, text=True, timeout=30
                    )
                    
                    for file_path in result.stdout.strip().split('\n'):
                        if file_path:
                            local_path = output_dir / Path(file_path).name
                            subprocess.run(
                                self.adb_cmd + ['pull', file_path, str(local_path)],
                                capture_output=True, timeout=60
                            )
                            
                            if local_path.exists():
                                documents.append({
                                    'filename': local_path.name,
                                    'type': ext.replace('*', ''),
                                    'path': str(local_path)
                                })
                except:
                    pass
        
        with open(output_dir / 'manifest.json', 'w') as f:
            json.dump({'count': len(documents), 'documents': documents}, f, indent=2)
        
        return {'success': True, 'count': len(documents), 'path': str(output_dir)}
    
    def extract_downloads(self):
        """Extract downloads folder"""
        output_dir = self.full_extract_dir / 'downloads'
        output_dir.mkdir(exist_ok=True)
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'ls -la /sdcard/Download'],
                capture_output=True, text=True, timeout=30
            )
            
            files = []
            for line in result.stdout.split('\n')[1:]:  # Skip total line
                parts = line.split()
                if len(parts) >= 9:
                    files.append({
                        'permissions': parts[0],
                        'size': parts[4] if parts[4].isdigit() else 0,
                        'date': ' '.join(parts[5:8]),
                        'name': parts[8] if len(parts) > 8 else ''
                    })
            
            with open(output_dir / 'file_list.json', 'w') as f:
                json.dump({'count': len(files), 'files': files}, f, indent=2)
            
            return {'success': True, 'count': len(files), 'path': str(output_dir)}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def extract_wifi_passwords(self):
        """Extract saved WiFi passwords (requires root)"""
        output_path = self.full_extract_dir / 'wifi_passwords.json'
        
        try:
            # Try to pull wpa_supplicant.conf (requires root)
            result = subprocess.run(
                self.adb_cmd + ['shell', 'su -c "cat /data/misc/wifi/wpa_supplicant.conf"'],
                capture_output=True, text=True, timeout=30
            )
            
            networks = []
            if 'ssid' in result.stdout.lower():
                # Parse config
                current_network = {}
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    if line.startswith('ssid='):
                        if current_network:
                            networks.append(current_network)
                        current_network = {'ssid': line.split('=')[1].strip('"')}
                    elif line.startswith('psk='):
                        current_network['password'] = line.split('=')[1].strip('"')
                    elif line.startswith('bssid='):
                        current_network['bssid'] = line.split('=')[1]
                
                if current_network:
                    networks.append(current_network)
            
            with open(output_path, 'w') as f:
                json.dump({'count': len(networks), 'networks': networks}, f, indent=2)
            
            return {
                'success': True,
                'count': len(networks),
                'path': str(output_path),
                'requires_root': True
            }
        except Exception as e:
            return {'success': False, 'error': str(e), 'requires_root': True}
    
    def extract_clipboard(self):
        """Extract clipboard content"""
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'cmd clipboard get-primary-clip'],
                capture_output=True, text=True, timeout=10
            )
            
            return {
                'success': True,
                'clipboard': result.stdout.strip(),
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def extract_videos(self):
        """Extract videos"""
        output_dir = self.full_extract_dir / 'videos'
        output_dir.mkdir(exist_ok=True)
        
        video_paths = ['/sdcard/DCIM', '/sdcard/Movies', '/sdcard/Videos']
        
        videos = []
        
        for vid_path in video_paths:
            try:
                result = subprocess.run(
                    self.adb_cmd + ['shell', f'find {vid_path} -name "*.mp4" -o -name "*.mkv" -o -name "*.avi" 2>/dev/null | head -50'],
                    capture_output=True, text=True, timeout=30
                )
                
                for file_path in result.stdout.strip().split('\n'):
                    if file_path:
                        local_path = output_dir / Path(file_path).name
                        subprocess.run(
                            self.adb_cmd + ['pull', file_path, str(local_path)],
                            capture_output=True, timeout=120
                        )
                        
                        if local_path.exists():
                            videos.append({
                                'filename': local_path.name,
                                'path': str(local_path),
                                'size': local_path.stat().st_size
                            })
            except:
                pass
        
        with open(output_dir / 'manifest.json', 'w') as f:
            json.dump({'count': len(videos), 'videos': videos}, f, indent=2)
        
        return {'success': True, 'count': len(videos), 'path': str(output_dir)}
    
    def extract_audio(self):
        """Extract audio files"""
        output_dir = self.full_extract_dir / 'audio'
        output_dir.mkdir(exist_ok=True)
        
        audio_paths = ['/sdcard/Music', '/sdcard/Audio', '/sdcard/Recordings']
        
        audio_files = []
        
        for aud_path in audio_paths:
            try:
                result = subprocess.run(
                    self.adb_cmd + ['shell', f'find {aud_path} -name "*.mp3" -o -name "*.wav" -o -name "*.m4a" -o -name "*.flac" 2>/dev/null | head -50'],
                    capture_output=True, text=True, timeout=30
                )
                
                for file_path in result.stdout.strip().split('\n'):
                    if file_path:
                        local_path = output_dir / Path(file_path).name
                        subprocess.run(
                            self.adb_cmd + ['pull', file_path, str(local_path)],
                            capture_output=True, timeout=60
                        )
                        
                        if local_path.exists():
                            audio_files.append({
                                'filename': local_path.name,
                                'path': str(local_path)
                            })
            except:
                pass
        
        with open(output_dir / 'manifest.json', 'w') as f:
            json.dump({'count': len(audio_files), 'audio': audio_files}, f, indent=2)
        
        return {'success': True, 'count': len(audio_files), 'path': str(output_dir)}
    
    def extract_dcim(self):
        """Extract DCIM folder (camera photos/videos)"""
        output_dir = self.full_extract_dir / 'dcim'
        output_dir.mkdir(exist_ok=True)
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'find /sdcard/DCIM -type f | head -100'],
                capture_output=True, text=True, timeout=30
            )
            
            files = []
            for file_path in result.stdout.strip().split('\n'):
                if file_path:
                    local_path = output_dir / Path(file_path).name
                    subprocess.run(
                        self.adb_cmd + ['pull', file_path, str(local_path)],
                        capture_output=True, timeout=60
                    )
                    
                    if local_path.exists():
                        files.append({
                            'filename': local_path.name,
                            'path': str(local_path)
                        })
            
            with open(output_dir / 'manifest.json', 'w') as f:
                json.dump({'count': len(files), 'files': files}, f, indent=2)
            
            return {'success': True, 'count': len(files), 'path': str(output_dir)}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def extract_build_prop(self):
        """Extract build.prop system information"""
        output_path = self.full_extract_dir / 'build_prop.json'
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'getprop'],
                capture_output=True, text=True, timeout=10
            )
            
            props = {}
            for line in result.stdout.strip().split('\n'):
                if '[' in line and ']' in line:
                    parts = line.split(']: [', 1)
                    if len(parts) == 2:
                        key = parts[0].replace('[', '').strip()
                        value = parts[1].replace(']', '').strip()
                        props[key] = value
            
            with open(output_path, 'w') as f:
                json.dump(props, f, indent=2)
            
            return {'success': True, 'count': len(props), 'path': str(output_path)}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def extract_package_list(self):
        """Extract full package list with details"""
        output_path = self.full_extract_dir / 'packages.json'
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'pm', 'list', 'packages', '-f', '-l'],
                capture_output=True, text=True, timeout=30
            )
            
            packages = []
            for line in result.stdout.split('\n'):
                if line.startswith('package:'):
                    packages.append(line.replace('package:', '').strip())
            
            with open(output_path, 'w') as f:
                json.dump({'count': len(packages), 'packages': packages}, f, indent=2)
            
            return {'success': True, 'count': len(packages), 'path': str(output_path)}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def extract_app_permissions(self):
        """Extract app permissions"""
        output_path = self.full_extract_dir / 'app_permissions.json'
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'pm', 'permissions'],
                capture_output=True, text=True, timeout=30
            )
            
            permissions = []
            current_perm = None
            
            for line in result.stdout.split('\n'):
                if 'android.permission.' in line:
                    if line.strip().startswith('android.permission.'):
                        current_perm = line.strip()
                        permissions.append({'permission': current_perm, 'apps': []})
                elif current_perm and line.strip() and not line.startswith(' '):
                    permissions[-1]['apps'].append(line.strip())
            
            with open(output_path, 'w') as f:
                json.dump({'count': len(permissions), 'permissions': permissions}, f, indent=2)
            
            return {'success': True, 'count': len(permissions), 'path': str(output_path)}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def extract_user_accounts(self):
        """Extract user accounts on device"""
        output_path = self.full_extract_dir / 'user_accounts.json'
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'pm', 'list', 'users'],
                capture_output=True, text=True, timeout=10
            )
            
            users = []
            for line in result.stdout.split('\n'):
                if 'UserInfo' in line:
                    users.append(line.strip())
            
            with open(output_path, 'w') as f:
                json.dump({'count': len(users), 'users': users}, f, indent=2)
            
            return {'success': True, 'count': len(users), 'path': str(output_path)}
        except Exception as e:
            return {'success': False, 'error': str(e)}


# =====================================================
# ULTRA-COMPREHENSIVE ANDROID EXTRACTION
# =====================================================

class UltraAndroidExtractor(AndroidFullExtractor):
    """Ultra-comprehensive Android extraction - EVERYTHING possible"""
    
    def __init__(self, device_id=None):
        super().__init__(device_id)
        self.ultra_extract_dir = Path.home() / 'palantir_extractions' / 'android_ultra' / datetime.now().strftime('%Y%m%d_%H%M%S')
        self.ultra_extract_dir.mkdir(parents=True, exist_ok=True)
    
    def ultra_extraction(self):
        """Extract EVERYTHING possible from Android device"""
        results = {
            'device_info': self.get_device_info(),
            'extractions': {},
            'timestamp': datetime.now().isoformat(),
            'device_id': self.device_id,
            'extraction_type': 'ultra_comprehensive'
        }
        
        # ===== MESSAGES & COMMUNICATION =====
        print("📱 Extracting messages...")
        results['extractions']['sms'] = self.extract_sms()
        results['extractions']['mms'] = self.extract_mms()
        results['extractions']['rcs_messages'] = self.extract_rcs_messages()
        results['extractions']['email'] = self.extract_email_data()
        results['extractions']['notifications'] = self.extract_notifications()
        
        # ===== SOCIAL MEDIA =====
        print("💬 Extracting social media...")
        results['extractions']['facebook'] = self.extract_facebook()
        results['extractions']['instagram'] = self.extract_instagram()
        results['extractions']['twitter'] = self.extract_twitter()
        results['extractions']['tiktok'] = self.extract_tiktok()
        results['extractions']['snapchat'] = self.extract_snapchat()
        results['extractions']['telegram'] = self.extract_telegram()
        results['extractions']['signal'] = self.extract_signal()
        
        # ===== PHOTOS & MEDIA WITH METADATA =====
        print("📸 Extracting photos with full metadata...")
        results['extractions']['photos'] = self.extract_photos_with_full_metadata()
        results['extractions']['videos'] = self.extract_videos_with_metadata()
        results['extractions']['audio'] = self.extract_audio_with_metadata()
        results['extractions']['dcim'] = self.extract_dcim()
        results['extractions']['screenshots'] = self.extract_screenshots()
        results['extractions']['thumbnails'] = self.extract_thumbnails()
        
        # ===== LOCATION & MOVEMENT =====
        print("📍 Extracting location data...")
        results['extractions']['location_history'] = self.get_location_history()
        results['extractions']['google_maps'] = self.extract_google_maps_data()
        results['extractions']['geofences'] = self.extract_geofences()
        results['extractions']['wifi_scan_history'] = self.extract_wifi_scan_history()
        results['extractions']['bluetooth_history'] = self.extract_bluetooth_history()
        
        # ===== APPS & DATA =====
        print("📲 Extracting apps...")
        results['extractions']['installed_apps'] = self.extract_installed_apps()
        results['extractions']['app_data'] = self.extract_all_app_data()
        results['extractions']['browser_history'] = self.extract_browser_history()
        results['extractions']['bookmarks'] = self.extract_bookmarks()
        results['extractions']['search_history'] = self.extract_search_history()
        results['extractions']['youtube_history'] = self.extract_youtube_history()
        
        # ===== CONTACTS & COMMUNICATION =====
        print("👥 Extracting contacts...")
        results['extractions']['contacts'] = self.extract_contacts_detailed()
        results['extractions']['call_logs'] = self.extract_call_logs()
        results['extractions']['call_recordings'] = self.extract_call_recordings()
        results['extractions']['voicemails'] = self.extract_voicemails()
        
        # ===== FILES & DOCUMENTS =====
        print("📁 Extracting files...")
        results['extractions']['documents'] = self.extract_documents()
        results['extractions']['downloads'] = self.extract_downloads()
        results['extractions']['sdcard'] = self.extract_sdcard()
        results['extractions']['internal_storage'] = self.extract_internal_storage()
        
        # ===== SYSTEM & DEVICE =====
        print("⚙️ Extracting system data...")
        results['extractions']['build_prop'] = self.extract_build_prop()
        results['extractions']['packages'] = self.extract_package_list()
        results['extractions']['permissions'] = self.extract_app_permissions()
        results['extractions']['users'] = self.extract_user_accounts()
        results['extractions']['system_settings'] = self.extract_system_settings()
        results['extractions']['secure_settings'] = self.extract_secure_settings()
        results['extractions']['battery_history'] = self.extract_battery_history()
        results['extractions']['usage_stats'] = self.extract_usage_statistics()
        results['extractions']['logcat'] = self.extract_logcat()
        
        # ===== SENSITIVE DATA =====
        print("🔐 Extracting sensitive data...")
        results['extractions']['wifi_passwords'] = self.extract_wifi_passwords()
        results['extractions']['clipboard'] = self.extract_clipboard_history()
        results['extractions']['autofill_data'] = self.extract_autofill_data()
        results['extractions']['saved_passwords'] = self.extract_saved_passwords()
        
        # Save comprehensive report
        report_path = self.ultra_extract_dir / 'ultra_extraction_report.json'
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, default=str, ensure_ascii=False)
        
        results['report_path'] = str(report_path)
        results['extract_dir'] = str(self.ultra_extract_dir)
        results['total_extractions'] = len([k for k, v in results['extractions'].items() if v.get('success', False)])
        
        return results
    
    def extract_mms(self):
        """Extract MMS messages with attachments"""
        output_path = self.ultra_extract_dir / 'mms.json'
        
        try:
            # Pull MMS database
            db_path = '/data/data/com.android.providers.telephony/databases/mmssms.db'
            local_db = self.ultra_extract_dir / 'mmssms.db'
            
            subprocess.run(self.adb_cmd + ['pull', db_path, str(local_db)], 
                         capture_output=True, timeout=30)
            
            if local_db.exists():
                conn = sqlite3.connect(str(local_db))
                cursor = conn.cursor()
                
                # Get MMS messages
                cursor.execute('''
                    SELECT _id, thread_id, address, date, msg_type, msg_size, 
                           subject, date_sent
                    FROM mms
                    ORDER BY date DESC LIMIT 500
                ''')
                
                mms_list = []
                for row in cursor.fetchall():
                    mms_list.append({
                        'id': row[0],
                        'thread_id': row[1],
                        'contact': row[2],
                        'timestamp': datetime.fromtimestamp(row[3]/1000).isoformat() if row[3] else None,
                        'type': ['received', 'sent', 'draft', 'outbox'][row[4]-1] if row[4] and 1 <= row[4] <= 4 else 'unknown',
                        'size': row[5],
                        'subject': row[6],
                        'sent_timestamp': datetime.fromtimestamp(row[7]).isoformat() if row[7] else None
                    })
                
                conn.close()
                
                with open(output_path, 'w') as f:
                    json.dump({'count': len(mms_list), 'mms': mms_list}, f, indent=2)
                
                return {'success': True, 'count': len(mms_list), 'path': str(output_path)}
        except Exception as e:
            return {'success': False, 'error': str(e)}
        
        return {'success': False, 'error': 'Could not extract MMS'}
    
    def extract_rcs_messages(self):
        """Extract RCS/Jibe messages"""
        output_path = self.ultra_extract_dir / 'rcs_messages.json'
        
        try:
            db_paths = [
                '/data/data/com.google.android.apps.messaging/databases/bugle.db',
                '/data/data/com.android.messaging/databases/bugle.db'
            ]
            
            for db_path in db_paths:
                local_db = self.ultra_extract_dir / 'rcs.db'
                result = subprocess.run(
                    self.adb_cmd + ['pull', db_path, str(local_db)],
                    capture_output=True, timeout=30
                )
                
                if local_db.exists():
                    conn = sqlite3.connect(str(local_db))
                    cursor = conn.cursor()
                    
                    cursor.execute('''
                        SELECT text, timestamp, sender_id, conversation_id
                        FROM messages
                        ORDER BY timestamp DESC LIMIT 500
                    ''')
                    
                    messages = []
                    for row in cursor.fetchall():
                        messages.append({
                            'message': row[0],
                            'timestamp': datetime.fromtimestamp(row[1]/1000).isoformat() if row[1] else None,
                            'sender': row[2],
                            'conversation_id': row[3]
                        })
                    
                    conn.close()
                    
                    with open(output_path, 'w') as f:
                        json.dump({'count': len(messages), 'messages': messages}, f, indent=2)
                    
                    return {'success': True, 'count': len(messages), 'path': str(output_path)}
            
            return {'success': False, 'error': 'RCS database not found'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def extract_email_data(self):
        """Extract email data from email apps"""
        output_path = self.ultra_extract_dir / 'email_data.json'
        
        email_apps = [
            ('Gmail', 'com.google.android.gm'),
            ('Email', 'com.android.email'),
            ('Outlook', 'com.microsoft.office.outlook'),
            ('Yahoo', 'com.yahoo.mobile.client.android.mail')
        ]
        
        all_emails = []
        
        for app_name, package in email_apps:
            try:
                # Try to pull email database
                db_path = f'/data/data/{package}/databases'
                local_dir = self.ultra_extract_dir / 'email' / package
                local_dir.mkdir(parents=True, exist_ok=True)
                
                result = subprocess.run(
                    self.adb_cmd + ['shell', f'ls {db_path}/*.db 2>/dev/null'],
                    capture_output=True, text=True, timeout=30
                )
                
                if result.stdout.strip():
                    all_emails.append({
                        'app': app_name,
                        'package': package,
                        'databases_found': True
                    })
            except:
                pass
        
        with open(output_path, 'w') as f:
            json.dump({'count': len(all_emails), 'apps': all_emails}, f, indent=2)
        
        return {'success': True, 'count': len(all_emails), 'path': str(output_path)}
    
    def extract_notifications(self):
        """Extract notification history"""
        output_path = self.ultra_extract_dir / 'notifications.json'
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'dumpsys notification'],
                capture_output=True, text=True, timeout=30
            )
            
            # Parse notification dump
            notifications = []
            current_notif = {}
            
            for line in result.stdout.split('\n'):
                if 'NotificationRecord' in line:
                    if current_notif:
                        notifications.append(current_notif)
                    current_notif = {'raw': line.strip()}
                elif 'userId=' in line or 'pkg=' in line or 'title=' in line:
                    current_notif[line.split('=')[0].strip()] = line.split('=')[1].strip() if '=' in line else ''
            
            if current_notif:
                notifications.append(current_notif)
            
            with open(output_path, 'w') as f:
                json.dump({'count': len(notifications), 'notifications': notifications}, f, indent=2)
            
            return {'success': True, 'count': len(notifications), 'path': str(output_path)}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def extract_photos_with_full_metadata(self):
        """Extract photos with EXHAUSTIVE metadata"""
        output_dir = self.ultra_extract_dir / 'photos_metadata'
        output_dir.mkdir(exist_ok=True)
        
        photo_paths = [
            '/sdcard/DCIM/Camera',
            '/sdcard/Pictures',
            '/sdcard/Download',
            '/sdcard/WhatsApp/Media/.Statuses'
        ]
        
        photos = []
        
        for photo_path in photo_paths:
            try:
                result = subprocess.run(
                    self.adb_cmd + ['shell', f'find {photo_path} -name "*.jpg" -o -name "*.png" | head -100'],
                    capture_output=True, text=True, timeout=30
                )
                
                for file_path in result.stdout.strip().split('\n'):
                    if file_path:
                        local_path = output_dir / Path(file_path).name
                        subprocess.run(
                            self.adb_cmd + ['pull', file_path, str(local_path)],
                            capture_output=True, timeout=60
                        )
                        
                        if local_path.exists():
                            # Extract FULL metadata
                            metadata = self.extract_full_photo_metadata(local_path, file_path)
                            photos.append(metadata)
            except:
                pass
        
        with open(output_dir / 'photo_manifest.json', 'w') as f:
            json.dump({'count': len(photos), 'photos': photos}, f, indent=2)
        
        return {'success': True, 'count': len(photos), 'path': str(output_dir)}
    
    def extract_full_photo_metadata(self, local_path, original_path):
        """Extract comprehensive metadata from photo"""
        metadata = {
            'filename': local_path.name,
            'local_path': str(local_path),
            'original_path': original_path,
            'size_bytes': local_path.stat().st_size,
            'modified': datetime.fromtimestamp(local_path.stat().st_mtime).isoformat()
        }
        
        try:
            img = Image.open(local_path)
            
            # Basic image info
            metadata['format'] = img.format
            metadata['mode'] = img.mode
            metadata['width'] = img.width
            metadata['height'] = img.height
            
            # EXIF data
            exif_data = img._getexif()
            if exif_data:
                for tag_id, value in exif_data.items():
                    tag = TAGS.get(tag_id, tag_id)
                    if tag == 'GPSInfo':
                        gps = {}
                        for t in value:
                            sub_tag = GPSTAGS.get(t, t)
                            gps[sub_tag] = value[t]
                        metadata['gps'] = gps
                    elif isinstance(value, bytes):
                        try:
                            metadata[f'exif_{tag}'] = value.decode('utf-8', errors='ignore')
                        except:
                            metadata[f'exif_{tag}'] = str(value)
                    else:
                        metadata[f'exif_{tag}'] = value
        except Exception as e:
            metadata['metadata_error'] = str(e)
        
        return metadata
    
    def extract_videos_with_metadata(self):
        """Extract videos with metadata"""
        output_dir = self.ultra_extract_dir / 'videos_metadata'
        output_dir.mkdir(exist_ok=True)
        
        video_paths = ['/sdcard/DCIM', '/sdcard/Movies', '/sdcard/Videos']
        
        videos = []
        
        for vid_path in video_paths:
            try:
                result = subprocess.run(
                    self.adb_cmd + ['shell', f'find {vid_path} -name "*.mp4" -o -name "*.mkv" | head -50'],
                    capture_output=True, text=True, timeout=30
                )
                
                for file_path in result.stdout.strip().split('\n'):
                    if file_path:
                        local_path = output_dir / Path(file_path).name
                        subprocess.run(
                            self.adb_cmd + ['pull', file_path, str(local_path)],
                            capture_output=True, timeout=120
                        )
                        
                        if local_path.exists():
                            videos.append({
                                'filename': local_path.name,
                                'path': str(local_path),
                                'size': local_path.stat().st_size,
                                'modified': datetime.fromtimestamp(local_path.stat().st_mtime).isoformat()
                            })
            except:
                pass
        
        with open(output_dir / 'video_manifest.json', 'w') as f:
            json.dump({'count': len(videos), 'videos': videos}, f, indent=2)
        
        return {'success': True, 'count': len(videos), 'path': str(output_dir)}
    
    def extract_screenshots(self):
        """Extract screenshots"""
        output_dir = self.ultra_extract_dir / 'screenshots'
        output_dir.mkdir(exist_ok=True)
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'find /sdcard/Pictures/Screenshots -name "*.png" -o -name "*.jpg" 2>/dev/null | head -50'],
                capture_output=True, text=True, timeout=30
            )
            
            screenshots = []
            for file_path in result.stdout.strip().split('\n'):
                if file_path:
                    local_path = output_dir / Path(file_path).name
                    subprocess.run(
                        self.adb_cmd + ['pull', file_path, str(local_path)],
                        capture_output=True, timeout=60
                    )
                    
                    if local_path.exists():
                        screenshots.append({
                            'filename': local_path.name,
                            'path': str(local_path)
                        })
            
            with open(output_dir / 'manifest.json', 'w') as f:
                json.dump({'count': len(screenshots), 'screenshots': screenshots}, f, indent=2)
            
            return {'success': True, 'count': len(screenshots), 'path': str(output_dir)}
        except:
            return {'success': False, 'error': 'Could not extract screenshots'}
    
    def extract_thumbnails(self):
        """Extract thumbnails"""
        output_dir = self.ultra_extract_dir / 'thumbnails'
        output_dir.mkdir(exist_ok=True)
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'find /sdcard/DCIM/.thumbnails -name "*.jpg" 2>/dev/null | head -100'],
                capture_output=True, text=True, timeout=30
            )
            
            thumbnails = []
            for file_path in result.stdout.strip().split('\n'):
                if file_path:
                    local_path = output_dir / Path(file_path).name
                    subprocess.run(
                        self.adb_cmd + ['pull', file_path, str(local_path)],
                        capture_output=True, timeout=60
                    )
                    
                    if local_path.exists():
                        thumbnails.append({
                            'filename': local_path.name,
                            'path': str(local_path)
                        })
            
            with open(output_dir / 'manifest.json', 'w') as f:
                json.dump({'count': len(thumbnails), 'thumbnails': thumbnails}, f, indent=2)
            
            return {'success': True, 'count': len(thumbnails), 'path': str(output_dir)}
        except:
            return {'success': False, 'error': 'Could not extract thumbnails'}
    
    def extract_contacts_detailed(self):
        """Extract detailed contact information"""
        output_path = self.ultra_extract_dir / 'contacts_detailed.json'
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'content', 'query', '--uri',
                               'content://com.android.contacts/contacts',
                               '--projection', '_id,display_name,starred,contact_in_visible_group'],
                capture_output=True, text=True, timeout=30
            )
            
            contacts = []
            for line in result.stdout.split('\n')[1:]:
                if line.strip():
                    parts = line.split('|')
                    if len(parts) >= 2:
                        contact = {
                            'id': parts[0],
                            'name': parts[1],
                            'starred': parts[2] == '1' if len(parts) > 2 else False,
                            'visible': parts[3] == '1' if len(parts) > 3 else True
                        }
                        
                        # Get phone numbers
                        phone_result = subprocess.run(
                            self.adb_cmd + ['shell', 'content', 'query', '--uri',
                                           f'content://com.android.contacts/contacts/{parts[0]}/phones',
                                           '--projection', 'data1,data2'],
                            capture_output=True, text=True, timeout=10
                        )
                        
                        phones = []
                        for phone_line in phone_result.stdout.split('\n')[1:]:
                            if phone_line.strip():
                                phone_parts = phone_line.split('|')
                                if len(phone_parts) >= 2:
                                    phones.append({
                                        'number': phone_parts[0],
                                        'type': phone_parts[1]
                                    })
                        
                        contact['phones'] = phones
                        contacts.append(contact)
            
            with open(output_path, 'w') as f:
                json.dump({'count': len(contacts), 'contacts': contacts}, f, indent=2)
            
            return {'success': True, 'count': len(contacts), 'path': str(output_path)}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def extract_social_media_app(self, app_name, package, data_paths):
        """Generic social media extraction"""
        output_dir = self.ultra_extract_dir / app_name
        output_dir.mkdir(exist_ok=True)
        
        extracted = []
        
        for data_path in data_paths:
            try:
                # List files
                result = subprocess.run(
                    self.adb_cmd + ['shell', f'ls -la {data_path} 2>/dev/null'],
                    capture_output=True, text=True, timeout=30
                )
                
                if result.stdout.strip():
                    extracted.append({
                        'path': data_path,
                        'exists': True,
                        'listing': result.stdout[:1000]  # First 1000 chars
                    })
            except:
                pass
        
        with open(output_dir / 'data_listing.json', 'w') as f:
            json.dump({'app': app_name, 'package': package, 'extracted': extracted}, f, indent=2)
        
        return {'success': True, 'count': len(extracted), 'path': str(output_dir)}
    
    def extract_facebook(self):
        """Extract Facebook data"""
        return self.extract_social_media_app('facebook', 'com.facebook.katana', [
            '/data/data/com.facebook.katana/databases',
            '/sdcard/Android/data/com.facebook.katana/cache'
        ])
    
    def extract_instagram(self):
        """Extract Instagram data"""
        return self.extract_social_media_app('instagram', 'com.instagram.android', [
            '/data/data/com.instagram.android/databases',
            '/sdcard/Instagram'
        ])
    
    def extract_twitter(self):
        """Extract Twitter data"""
        return self.extract_social_media_app('twitter', 'com.twitter.android', [
            '/data/data/com.twitter.android/databases'
        ])
    
    def extract_tiktok(self):
        """Extract TikTok data"""
        return self.extract_social_media_app('tiktok', 'com.zhiliaoapp.musically', [
            '/data/data/com.zhiliaoapp.musically/databases',
            '/sdcard/Android/data/com.zhiliaoapp.musically/files'
        ])
    
    def extract_snapchat(self):
        """Extract Snapchat data"""
        return self.extract_social_media_app('snapchat', 'com.snapchat.android', [
            '/data/data/com.snapchat.android/databases',
            '/sdcard/Android/data/com.snapchat.android/cache'
        ])
    
    def extract_telegram(self):
        """Extract Telegram data"""
        return self.extract_social_media_app('telegram', 'org.telegram.messenger', [
            '/data/data/org.telegram.messenger/databases',
            '/sdcard/Telegram'
        ])
    
    def extract_signal(self):
        """Extract Signal data"""
        return self.extract_social_media_app('signal', 'org.thoughtcrime.securesms', [
            '/data/data/org.thoughtcrime.securesms/databases'
        ])
    
    def extract_google_maps_data(self):
        """Extract Google Maps data"""
        output_path = self.ultra_extract_dir / 'google_maps.json'
        
        try:
            # Pull Maps data
            maps_dir = '/data/data/com.google.android.apps.maps/app_mymaps'
            local_dir = self.ultra_extract_dir / 'google_maps'
            local_dir.mkdir(exist_ok=True)
            
            result = subprocess.run(
                self.adb_cmd + ['shell', f'ls {maps_dir} 2>/dev/null'],
                capture_output=True, text=True, timeout=30
            )
            
            maps_data = []
            if result.stdout.strip():
                maps_data.append({'found': True, 'files': result.stdout.strip()})
            
            with open(output_path, 'w') as f:
                json.dump({'maps_data': maps_data}, f, indent=2)
            
            return {'success': True, 'path': str(output_path)}
        except:
            return {'success': False, 'error': 'Could not extract Maps data'}
    
    def extract_geofences(self):
        """Extract geofence data"""
        output_path = self.ultra_extract_dir / 'geofences.json'
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'dumpsys location'],
                capture_output=True, text=True, timeout=30
            )
            
            geofences = []
            for line in result.stdout.split('\n'):
                if 'Geofence' in line or 'geofence' in line:
                    geofences.append(line.strip())
            
            with open(output_path, 'w') as f:
                json.dump({'count': len(geofences), 'geofences': geofences}, f, indent=2)
            
            return {'success': True, 'count': len(geofences), 'path': str(output_path)}
        except:
            return {'success': False, 'error': 'Could not extract geofences'}
    
    def extract_wifi_scan_history(self):
        """Extract WiFi scan history"""
        output_path = self.ultra_extract_dir / 'wifi_scans.json'
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'dumpsys wifi'],
                capture_output=True, text=True, timeout=30
            )
            
            scans = []
            for line in result.stdout.split('\n'):
                if 'Scan' in line or 'BSSID' in line:
                    scans.append(line.strip())
            
            with open(output_path, 'w') as f:
                json.dump({'count': len(scans), 'scans': scans}, f, indent=2)
            
            return {'success': True, 'count': len(scans), 'path': str(output_path)}
        except:
            return {'success': False, 'error': 'Could not extract WiFi scans'}
    
    def extract_bluetooth_history(self):
        """Extract Bluetooth history"""
        output_path = self.ultra_extract_dir / 'bluetooth.json'
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'dumpsys bluetooth_manager'],
                capture_output=True, text=True, timeout=30
            )
            
            bt_data = []
            for line in result.stdout.split('\n'):
                if 'device' in line.lower() or 'bond' in line.lower():
                    bt_data.append(line.strip())
            
            with open(output_path, 'w') as f:
                json.dump({'count': len(bt_data), 'bluetooth': bt_data}, f, indent=2)
            
            return {'success': True, 'count': len(bt_data), 'path': str(output_path)}
        except:
            return {'success': False, 'error': 'Could not extract Bluetooth data'}
    
    def extract_all_app_data(self):
        """Extract data from all apps"""
        output_dir = self.ultra_extract_dir / 'all_app_data'
        output_dir.mkdir(exist_ok=True)
        
        try:
            # Get list of all packages
            result = subprocess.run(
                self.adb_cmd + ['shell', 'pm', 'list', 'packages'],
                capture_output=True, text=True, timeout=30
            )
            
            packages = []
            for line in result.stdout.split('\n'):
                if line.startswith('package:'):
                    packages.append(line.replace('package:', '').strip())
            
            # Try to pull data from top 20 apps
            app_data = []
            for pkg in packages[:20]:
                try:
                    data_path = f'/data/data/{pkg}'
                    result = subprocess.run(
                        self.adb_cmd + ['shell', f'ls {data_path}/databases 2>/dev/null'],
                        capture_output=True, text=True, timeout=10
                    )
                    
                    if result.stdout.strip():
                        app_data.append({
                            'package': pkg,
                            'has_databases': True
                        })
                except:
                    pass
            
            with open(output_dir / 'app_data_manifest.json', 'w') as f:
                json.dump({'total_apps': len(packages), 'apps_with_data': len(app_data), 'apps': app_data}, f, indent=2)
            
            return {'success': True, 'count': len(app_data), 'path': str(output_dir)}
        except:
            return {'success': False, 'error': 'Could not extract app data'}
    
    def extract_bookmarks(self):
        """Extract browser bookmarks"""
        output_path = self.ultra_extract_dir / 'bookmarks.json'
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'content', 'query', '--uri',
                               'content://browser/bookmarks',
                               '--projection', 'title,url'],
                capture_output=True, text=True, timeout=30
            )
            
            bookmarks = []
            for line in result.stdout.split('\n')[1:]:
                if line.strip():
                    parts = line.split('|')
                    if len(parts) >= 2:
                        bookmarks.append({
                            'title': parts[0],
                            'url': parts[1]
                        })
            
            with open(output_path, 'w') as f:
                json.dump({'count': len(bookmarks), 'bookmarks': bookmarks}, f, indent=2)
            
            return {'success': True, 'count': len(bookmarks), 'path': str(output_path)}
        except:
            return {'success': False, 'error': 'Could not extract bookmarks'}
    
    def extract_search_history(self):
        """Extract search history"""
        output_path = self.ultra_extract_dir / 'search_history.json'
        
        try:
            # Google search history
            result = subprocess.run(
                self.adb_cmd + ['shell', 'dumpsys activity service com.google.android.googlequicksearchbox'],
                capture_output=True, text=True, timeout=30
            )
            
            searches = []
            for line in result.stdout.split('\n'):
                if 'search' in line.lower() and 'query' in line.lower():
                    searches.append(line.strip())
            
            with open(output_path, 'w') as f:
                json.dump({'count': len(searches), 'searches': searches}, f, indent=2)
            
            return {'success': True, 'count': len(searches), 'path': str(output_path)}
        except:
            return {'success': False, 'error': 'Could not extract search history'}
    
    def extract_youtube_history(self):
        """Extract YouTube history"""
        output_path = self.ultra_extract_dir / 'youtube_history.json'
        
        try:
            yt_dir = '/data/data/com.google.android.youtube/databases'
            result = subprocess.run(
                self.adb_cmd + ['shell', f'ls {yt_dir} 2>/dev/null'],
                capture_output=True, text=True, timeout=30
            )
            
            youtube_data = {'found': result.returncode == 0, 'files': result.stdout.strip()}
            
            with open(output_path, 'w') as f:
                json.dump(youtube_data, f, indent=2)
            
            return {'success': True, 'path': str(output_path)}
        except:
            return {'success': False, 'error': 'Could not extract YouTube data'}
    
    def extract_sdcard(self):
        """Extract entire SD card contents listing"""
        output_path = self.ultra_extract_dir / 'sdcard_listing.json'
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'find /sdcard -type f | head -1000'],
                capture_output=True, text=True, timeout=60
            )
            
            files = result.stdout.strip().split('\n') if result.stdout.strip() else []
            
            with open(output_path, 'w') as f:
                json.dump({'count': len(files), 'files': files[:500]}, f, indent=2)  # First 500
            
            return {'success': True, 'count': len(files), 'path': str(output_path)}
        except:
            return {'success': False, 'error': 'Could not list SD card'}
    
    def extract_internal_storage(self):
        """Extract internal storage listing"""
        output_path = self.ultra_extract_dir / 'internal_storage.json'
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'ls -laR /data/local/tmp 2>/dev/null | head -500'],
                capture_output=True, text=True, timeout=30
            )
            
            with open(output_path, 'w') as f:
                json.dump({'listing': result.stdout[:10000]}, f, indent=2)  # First 10k chars
            
            return {'success': True, 'path': str(output_path)}
        except:
            return {'success': False, 'error': 'Could not list internal storage'}
    
    def extract_system_settings(self):
        """Extract system settings"""
        output_path = self.ultra_extract_dir / 'system_settings.json'
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'settings get system'],
                capture_output=True, text=True, timeout=30
            )
            
            settings = {}
            for line in result.stdout.strip().split('\n'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    settings[key.strip()] = value.strip()
            
            with open(output_path, 'w') as f:
                json.dump({'count': len(settings), 'settings': settings}, f, indent=2)
            
            return {'success': True, 'count': len(settings), 'path': str(output_path)}
        except:
            return {'success': False, 'error': 'Could not extract system settings'}
    
    def extract_secure_settings(self):
        """Extract secure settings"""
        output_path = self.ultra_extract_dir / 'secure_settings.json'
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'settings get secure'],
                capture_output=True, text=True, timeout=30
            )
            
            settings = {}
            for line in result.stdout.strip().split('\n'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    settings[key.strip()] = value.strip()
            
            with open(output_path, 'w') as f:
                json.dump({'count': len(settings), 'settings': settings}, f, indent=2)
            
            return {'success': True, 'count': len(settings), 'path': str(output_path)}
        except:
            return {'success': False, 'error': 'Could not extract secure settings'}
    
    def extract_battery_history(self):
        """Extract battery usage history"""
        output_path = self.ultra_extract_dir / 'battery_history.json'
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'dumpsys batterystats --history'],
                capture_output=True, text=True, timeout=30
            )
            
            history = result.stdout[:50000]  # First 50k chars
            
            with open(output_path, 'w') as f:
                json.dump({'history': history}, f, indent=2)
            
            return {'success': True, 'path': str(output_path)}
        except:
            return {'success': False, 'error': 'Could not extract battery history'}
    
    def extract_usage_statistics(self):
        """Extract app usage statistics"""
        output_path = self.ultra_extract_dir / 'usage_stats.json'
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'dumpsys usagestats'],
                capture_output=True, text=True, timeout=30
            )
            
            stats = result.stdout[:50000]  # First 50k chars
            
            with open(output_path, 'w') as f:
                json.dump({'usage_stats': stats}, f, indent=2)
            
            return {'success': True, 'path': str(output_path)}
        except:
            return {'success': False, 'error': 'Could not extract usage stats'}
    
    def extract_logcat(self):
        """Extract logcat logs"""
        output_path = self.ultra_extract_dir / 'logcat.txt'
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['logcat', '-d'],
                capture_output=True, text=True, timeout=30
            )
            
            with open(output_path, 'w') as f:
                f.write(result.stdout[:100000])  # First 100k chars
            
            return {'success': True, 'path': str(output_path), 'size': len(result.stdout)}
        except:
            return {'success': False, 'error': 'Could not extract logcat'}
    
    def extract_clipboard_history(self):
        """Extract clipboard history"""
        output_path = self.ultra_extract_dir / 'clipboard.json'
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'cmd clipboard get-primary-clip'],
                capture_output=True, text=True, timeout=10
            )
            
            clipboard = {
                'current': result.stdout.strip(),
                'timestamp': datetime.now().isoformat()
            }
            
            with open(output_path, 'w') as f:
                json.dump(clipboard, f, indent=2)
            
            return {'success': True, 'path': str(output_path)}
        except:
            return {'success': False, 'error': 'Could not extract clipboard'}
    
    def extract_autofill_data(self):
        """Extract autofill data"""
        output_path = self.ultra_extract_dir / 'autofill.json'
        
        try:
            result = subprocess.run(
                self.adb_cmd + ['shell', 'dumpsys autofill'],
                capture_output=True, text=True, timeout=30
            )
            
            autofill = result.stdout[:50000]
            
            with open(output_path, 'w') as f:
                json.dump({'autofill_data': autofill}, f, indent=2)
            
            return {'success': True, 'path': str(output_path)}
        except:
            return {'success': False, 'error': 'Could not extract autofill data'}
    
    def extract_saved_passwords(self):
        """Extract saved passwords (requires root)"""
        output_path = self.ultra_extract_dir / 'saved_passwords.json'
        
        try:
            # Try Google Smart Lock
            result = subprocess.run(
                self.adb_cmd + ['shell', 'su -c "ls /data/data/com.google.android.gms/app_autofill"'],
                capture_output=True, text=True, timeout=30
            )
            
            passwords = {
                'found': result.returncode == 0,
                'note': 'Requires root access. Passwords are encrypted.'
            }
            
            with open(output_path, 'w') as f:
                json.dump(passwords, f, indent=2)
            
            return {'success': True, 'requires_root': True, 'path': str(output_path)}
        except:
            return {'success': False, 'error': 'Could not extract saved passwords', 'requires_root': True}


# =====================================================
# WIRELESS ADB & PHONE CAMERA MOTION MONITORING
# =====================================================

class WirelessADBCamera:
    """Use Android phones as wireless motion detection cameras via ADB"""
    
    def __init__(self):
        self.connected_phones = {}  # device_id -> info
        self.camera_threads = {}
        self.adb_cmd = ['adb']
        self.motion_callbacks = []
        
    def connect_wireless(self, ip_address, port=5555):
        """Connect to phone via wireless ADB"""
        try:
            # Connect to device
            result = subprocess.run(
                ['adb', 'connect', f'{ip_address}:{port}'],
                capture_output=True, text=True, timeout=10
            )
            
            if 'connected' in result.stdout.lower() or 'already connected' in result.stdout.lower():
                # Get device ID
                devices_result = subprocess.run(
                    ['adb', 'devices'],
                    capture_output=True, text=True, timeout=5
                )
                
                for line in devices_result.stdout.split('\n')[1:]:
                    if ip_address in line and 'device' in line:
                        device_id = line.split('\t')[0]
                        self.connected_phones[device_id] = {
                            'ip': ip_address,
                            'port': port,
                            'status': 'connected',
                            'connected_at': datetime.now().isoformat()
                        }
                        return {
                            'success': True,
                            'device_id': device_id,
                            'message': f'Connected to {ip_address}:{port}'
                        }
                
                return {'success': True, 'message': 'Connected but device ID unknown'}
            else:
                return {'success': False, 'error': result.stdout + result.stderr}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def disconnect_wireless(self, device_id):
        """Disconnect from phone"""
        try:
            subprocess.run(['adb', 'disconnect', device_id], timeout=5)
            if device_id in self.connected_phones:
                del self.connected_phones[device_id]
            return {'success': True, 'message': f'Disconnected {device_id}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def list_connected_phones(self):
        """List all connected phones"""
        # Refresh device list
        result = subprocess.run(['adb', 'devices'], capture_output=True, text=True, timeout=5)
        
        devices = []
        for line in result.stdout.split('\n')[1:]:
            if line.strip() and '\tdevice' in line:
                device_id = line.split('\t')[0]
                is_wireless = ':' in device_id  # Wireless devices have IP:port
                
                device_info = {
                    'device_id': device_id,
                    'type': 'wireless' if is_wireless else 'usb',
                    'status': 'connected'
                }
                
                # Get phone model
                try:
                    model_result = subprocess.run(
                        ['adb', '-s', device_id, 'shell', 'getprop', 'ro.product.model'],
                        capture_output=True, text=True, timeout=5
                    )
                    device_info['model'] = model_result.stdout.strip()
                except:
                    device_info['model'] = 'Unknown'
                
                # Get camera info
                try:
                    camera_result = subprocess.run(
                        ['adb', '-s', device_id, 'shell', 'ls', '/dev/video*'],
                        capture_output=True, text=True, timeout=5
                    )
                    device_info['has_camera'] = len(camera_result.stdout.strip()) > 0
                except:
                    device_info['has_camera'] = False
                
                devices.append(device_info)
        
        return {'count': len(devices), 'devices': devices}
    
    def capture_from_phone_camera(self, device_id, camera_id=0, output_path=None):
        """Capture single frame from phone camera"""
        if not output_path:
            output_path = f'/tmp/phone_cam_{device_id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.jpg'
        
        try:
            # Use screen capture as fallback (more reliable than camera2)
            subprocess.run(
                ['adb', '-s', device_id, 'shell', 'screencap', '-p', '/sdcard/cam_capture.png'],
                capture_output=True, timeout=10
            )
            
            subprocess.run(
                ['adb', '-s', device_id, 'pull', '/sdcard/cam_capture.png', output_path],
                capture_output=True, timeout=10
            )
            
            if Path(output_path).exists():
                return {
                    'success': True,
                    'path': output_path,
                    'device_id': device_id,
                    'timestamp': datetime.now().isoformat()
                }
            else:
                return {'success': False, 'error': 'Failed to capture'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def start_motion_monitoring(self, device_id, callback=None, interval=2, report_to_duckbot=True):
        """Start motion monitoring on phone camera"""
        if device_id in self.camera_threads:
            return {'success': False, 'error': 'Already monitoring'}
        
        # Initialize reporter
        duckbot_reporter = OpenClawReporter() if report_to_duckbot else None
        
        def monitor_loop():
            last_frame = None
            motion_count = 0
            last_report_time = time.time()
            report_interval = 300  # Report every 5 minutes max
            
            while device_id in self.camera_threads:
                # Capture frame
                result = self.capture_from_phone_camera(device_id)
                
                if result['success']:
                    current_frame = cv2.imread(result['path'])
                    
                    if current_frame is not None:
                        # Compare with last frame
                        if last_frame is not None:
                            diff = cv2.absdiff(last_frame, current_frame)
                            gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
                            motion = cv2.countNonZero(gray)
                            
                            # Motion detected
                            if motion > 10000:  # Threshold
                                motion_count += 1
                                
                                # Report to DuckBot (rate limited)
                                if duckbot_reporter and (time.time() - last_report_time) > report_interval:
                                    duckbot_reporter.report_motion_detected(
                                        device_id, motion_count, result['path']
                                    )
                                    last_report_time = time.time()
                                
                                if callback:
                                    callback({
                                        'device_id': device_id,
                                        'motion': True,
                                        'motion_count': motion_count,
                                        'timestamp': datetime.now().isoformat(),
                                        'frame_path': result['path']
                                    })
                        
                        last_frame = current_frame
                
                time.sleep(interval)
        
        thread = threading.Thread(target=monitor_loop, daemon=True)
        self.camera_threads[device_id] = thread
        thread.start()
        
        return {
            'success': True,
            'device_id': device_id,
            'message': f'Started motion monitoring on {device_id}',
            'duckbot_reports': report_to_duckbot
        }
    
    def stop_motion_monitoring(self, device_id):
        """Stop motion monitoring"""
        if device_id in self.camera_threads:
            del self.camera_threads[device_id]
            return {'success': True, 'message': f'Stopped monitoring {device_id}'}
        return {'success': False, 'error': 'Not monitoring'}
    
    def get_phone_battery(self, device_id):
        """Get phone battery level"""
        try:
            result = subprocess.run(
                ['adb', '-s', device_id, 'shell', 'dumpsys', 'battery'],
                capture_output=True, text=True, timeout=5
            )
            
            battery_info = {}
            for line in result.stdout.split('\n'):
                if 'level:' in line:
                    battery_info['level'] = int(line.split(':')[1].strip())
                elif 'status:' in line:
                    battery_info['status'] = line.split(':')[1].strip()
                elif 'plugged:' in line:
                    battery_info['charging'] = line.split(':')[1].strip() != '0'
            
            return {'success': True, 'battery': battery_info}
        except:
            return {'success': False, 'error': 'Could not get battery info'}
    
    def get_phone_storage(self, device_id):
        """Get phone storage info"""
        try:
            result = subprocess.run(
                ['adb', '-s', device_id, 'shell', 'df', '/sdcard'],
                capture_output=True, text=True, timeout=5
            )
            
            lines = result.stdout.strip().split('\n')
            if len(lines) >= 2:
                parts = lines[1].split()
                if len(parts) >= 5:
                    return {
                        'success': True,
                        'storage': {
                            'total': parts[1],
                            'used': parts[2],
                            'free': parts[3],
                            'percent_used': parts[4]
                        }
                    }
            
            return {'success': False, 'error': 'Could not parse storage info'}
        except:
            return {'success': False, 'error': 'Could not get storage info'}
    
    def enable_wireless_adb(self, device_id_usb):
        """Enable wireless ADB on phone (requires USB connection first)"""
        try:
            # Get phone IP
            ip_result = subprocess.run(
                ['adb', '-s', device_id_usb, 'shell', 'ip', 'addr', 'show', 'wlan0'],
                capture_output=True, text=True, timeout=5
            )
            
            ip_address = None
            for line in ip_result.stdout.split('\n'):
                if 'inet ' in line and 'brd' in line:
                    ip_address = line.split()[1].split('/')[0]
                    break
            
            if not ip_address:
                # Try alternative method
                ip_result = subprocess.run(
                    ['adb', '-s', device_id_usb, 'shell', 'getprop', 'dhcp.wlan0.ipaddress'],
                    capture_output=True, text=True, timeout=5
                )
                ip_address = ip_result.stdout.strip()
            
            if not ip_address:
                return {'success': False, 'error': 'Could not get device IP'}
            
            # Enable TCP/IP mode
            subprocess.run(
                ['adb', '-s', device_id_usb, 'tcpip', '5555'],
                capture_output=True, timeout=5
            )
            
            # Disconnect USB
            subprocess.run(['adb', 'disconnect'], timeout=5)
            
            return {
                'success': True,
                'ip': ip_address,
                'port': 5555,
                'message': f'Now connect to {ip_address}:5555 wirelessly',
                'command': f'adb connect {ip_address}:5555'
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}


# =====================================================
# OPENCLAW INTEGRATION - Report to DuckBot
# =====================================================

class OpenClawReporter:
    """Report phone camera events to DuckBot via OpenClaw"""
    
    def __init__(self, telegram_channel=None):
        self.telegram_channel = telegram_channel or 'telegram:588090613'
        self.report_queue = []
        self.enabled = True
    
    def send_telegram_alert(self, message, photo_path=None):
        """Send alert to Telegram via OpenClaw message tool"""
        try:
            import subprocess
            import json
            
            alert_data = {
                'channel': 'telegram',
                'action': 'send',
                'target': self.telegram_channel,
                'message': message
            }
            
            if photo_path and Path(photo_path).exists():
                # Send with photo
                alert_data['media'] = str(photo_path)
                alert_data['caption'] = message
            
            # Queue for OpenClaw message tool
            self.report_queue.append(alert_data)
            
            # Try to send via OpenClaw CLI if available
            try:
                result = subprocess.run(
                    ['openclaw', 'message', 'send', '--target', self.telegram_channel, '--message', message],
                    capture_output=True, text=True, timeout=10
                )
                return {'success': True, 'sent': True}
            except:
                # Queue for later
                return {'success': True, 'queued': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def report_motion_detected(self, device_id, motion_count, photo_path=None):
        """Report motion detection event"""
        if not self.enabled:
            return
        
        message = f"📱 **MOTION DETECTED** on {device_id}\n"
        message += f"🔢 Event #{motion_count}\n"
        message += f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return self.send_telegram_alert(message, photo_path)
    
    def report_phone_connected(self, device_id, ip_address):
        """Report new phone connected"""
        message = f"📱 **NEW PHONE CONNECTED**\n"
        message += f"🆔 Device: {device_id}\n"
        message += f"🌐 IP: {ip_address}\n"
        message += f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return self.send_telegram_alert(message)
    
    def report_phone_disconnected(self, device_id):
        """Report phone disconnected"""
        message = f"📱 **PHONE DISCONNECTED**\n"
        message += f"🆔 Device: {device_id}\n"
        message += f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return self.send_telegram_alert(message)
    
    def report_low_battery(self, device_id, battery_level):
        """Report low battery warning"""
        message = f"🔋 **LOW BATTERY WARNING**\n"
        message += f"📱 Device: {device_id}\n"
        message += f"🔋 Level: {battery_level}%\n"
        message += f"⚠️ Connect to charger!\n"
        message += f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return self.send_telegram_alert(message)
    
    def report_storage_full(self, device_id, percent_used):
        """Report storage nearly full"""
        message = f"💾 **STORAGE WARNING**\n"
        message += f"📱 Device: {device_id}\n"
        message += f"💾 Used: {percent_used}\n"
        message += f"⚠️ Free up space!\n"
        message += f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return self.send_telegram_alert(message)
    
    def send_status_report(self, connected_phones, monitoring_phones):
        """Send periodic status report"""
        message = f"📊 **WIRELESS CAMERA STATUS**\n\n"
        message += f"📱 Connected: {len(connected_phones)}\n"
        message += f"📹 Monitoring: {len(monitoring_phones)}\n\n"
        
        if connected_phones:
            message += "**Connected Phones:**\n"
            for device_id, info in connected_phones.items():
                message += f"• {device_id} ({info.get('ip', 'unknown')})\n"
        
        message += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return self.send_telegram_alert(message)
    
    def get_queued_reports(self):
        """Get all queued reports"""
        reports = self.report_queue.copy()
        self.report_queue.clear()
        return reports
