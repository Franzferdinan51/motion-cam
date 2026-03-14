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
