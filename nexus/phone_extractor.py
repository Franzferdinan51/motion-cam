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
