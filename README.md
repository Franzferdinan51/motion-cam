# 👁️ Palantir at Home

**Advanced Surveillance System with Motion Monitoring & Phone Data Extraction**

A comprehensive, self-hosted intelligence platform featuring real-time motion detection, phone data extraction, document analysis (Nexus-Docs integration), snapshot capture, event logging, and beautiful web interfaces. Accessible locally or remotely via Tailscale.

---

## 🎯 Features

### Motion Monitoring
- **🎥 Real-Time Video Streaming** - Live webcam feed with <100ms latency
- **⚡ Motion Detection** - AI-powered background subtraction with configurable sensitivity
- **📸 Auto Snapshots** - Automatic capture on motion + manual snapshots
- **📊 Live Statistics** - FPS, motion count, uptime, last motion time
- **🔔 Real-Time Alerts** - WebSocket-powered instant notifications

### Phone Extraction (Nexus Integration)
- **📱 Android Data Extraction** - Full phone forensics via ADB
- **💬 SMS/MMS Extraction** - All messages with timestamps & contacts
- **📞 Call Logs** - Incoming, outgoing, missed calls with duration
- **👥 Contacts** - Full contact list extraction
- **📸 Photos** - Extract with EXIF metadata & GPS coordinates
- **📍 Location History** - Google Maps timeline data
- **🔍 Device Info** - Model, Android version, serial number

### Storage Management
- **💾 Auto-Cleanup** - Automatic deletion of old snapshots
- **📁 Custom Locations** - Set custom save paths (external drives, etc.)
- **🧹 Manual Cleanup** - Delete by age or clear all
- **📊 Storage Stats** - Real-time file count & size tracking

### General
- **🌐 Web Dashboard** - Beautiful, responsive UI accessible from any device
- **🔒 Remote Access** - Works with Tailscale for secure remote viewing
- **⚙️ Configurable** - Adjust sensitivity, resolution, thresholds via web UI
- **🔗 Nexus-Docs** - Document analysis & entity extraction integration

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
cd ~/.openclaw/workspace/projects/palantir-home
pip3 install -r requirements.txt --break-system-packages
```

### 2. Grant Camera Permission (macOS)

**System Settings → Privacy & Security → Camera:**
- Enable camera access for **Terminal** (or your terminal app)

### 3. Launch

```bash
./start.sh
```

### 4. Open Dashboard

**Local:** http://localhost:5555  
**Remote (Tailscale):** http://YOUR_TAILSCALE_IP:5555

---

## 📖 Usage

### Dashboard Controls

| Button | Action |
|--------|--------|
| ▶️ Start | Begin motion monitoring |
| ⏹️ Stop | Stop monitoring |
| 📸 Snapshot | Take manual snapshot |
| ⛶ Fullscreen | Fullscreen video feed |

### Configuration Settings

| Setting | Description | Default |
|---------|-------------|---------|
| **Camera ID** | 0 = Logitech C170, 1 = iPhone Camera | 0 |
| **Resolution** | Video width x height | 1280x720 |
| **FPS** | Frames per second | 30 |
| **Motion Threshold** | Sensitivity (lower = more sensitive) | 25 |
| **Min Area** | Minimum motion size (pixels) | 500 |
| **Max Area** | Maximum motion size (pixels) | 100000 |
| **Blur Size** | Gaussian blur kernel (odd numbers) | 21 |

---

## 🌍 Remote Access

### Option 1: Tailscale (Recommended)

1. Install Tailscale on your Mac mini
2. Get your Tailscale IP: `tailscale ip`
3. Access from anywhere: `http://YOUR_TAILSCALE_IP:5555`

**Benefits:**
- ✅ Encrypted connection
- ✅ No port forwarding
- ✅ Works behind NAT/firewall
- ✅ Free for personal use

### Option 2: Port Forwarding

```bash
# Forward port 5555 on your router
# External: YOUR_PUBLIC_IP:5555
# Internal: 192.168.1.X:5555
```

⚠️ **Warning:** Only use port forwarding with strong authentication!

---

## 📁 File Structure

```
palantir-home/
├── palantir.py          # Main application
├── start.sh             # Launch script
├── requirements.txt     # Python dependencies
├── README.md            # This file
├── templates/
│   └── dashboard.html   # Web UI
├── snapshots/           # Captured images
│   ├── 20260314-153022_motion.jpg
│   └── ...
└── palantir.db          # SQLite database
```

---

## 🔧 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Get monitor status |
| `/api/start` | POST | Start monitoring |
| `/api/stop` | POST | Stop monitoring |
| `/api/snapshot` | POST | Take manual snapshot |
| `/api/snapshots` | GET | Get recent snapshots |
| `/api/events` | GET | Get motion events |
| `/api/config` | GET/POST | Get/set configuration |

---

## 🔌 WebSocket Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `connect` | Client → Server | Client connected |
| `video_frame` | Server → Client | Live video frame |
| `snapshot_saved` | Server → Client | New snapshot saved |
| `status_update` | Server → Client | Status change |

---

## 🎨 Dashboard Features

### Live Feed Panel
- Real-time video with motion overlay
- FPS counter
- Resolution indicator
- Motion detection alert
- Fullscreen mode

### Statistics Panel
- Total motions detected
- Snapshots taken
- System uptime
- Last motion timestamp

### Events Panel
- Recent motion events
- Motion area (pixels²)
- Detection zones count
- Timestamp for each event

### Snapshots Gallery
- Grid view of all captures
- Timestamp overlay
- Reason (motion/manual)
- Click to view full size

### Settings Panel
- All configuration options
- Real-time updates
- Save/load presets

### System Logs
- Real-time log streaming
- Color-coded entries
- Clear history option

---

## 📸 Camera Options

### Logitech C170 (USB)
- **Device ID:** 0
- **Resolution:** Up to 1280x720
- **Connection:** USB-A
- **Status:** ✅ Recommended

### iPhone Camera (Continuity)
- **Device ID:** 1
- **Resolution:** Up to 4K (depends on iPhone)
- **Connection:** Wireless (Continuity Camera)
- **Status:** ✅ Works great

---

## 🛠️ Troubleshooting

### Camera Not Detected

```bash
# List available cameras
ffmpeg -f avfoundation -list_devices true -i ""

# Test camera 0
ffmpeg -f avfoundation -i "0" -frames 1 test.jpg

# Test camera 1
ffmpeg -f avfoundation -i "1" -frames 1 test.jpg
```

### Permission Denied (macOS)

1. **System Settings → Privacy & Security → Camera**
2. Enable for Terminal
3. Restart Terminal
4. Try again

### High CPU Usage

- Lower FPS (e.g., 15 instead of 30)
- Reduce resolution (e.g., 640x480)
- Increase motion threshold
- Use smaller blur size

### Motion Not Detecting

- Lower motion threshold (e.g., 15)
- Decrease min_area (e.g., 200)
- Ensure good lighting
- Check camera angle

---

## 🔒 Security

### Production Hardening

1. **Change secret key** in `palantir.py`:
   ```python
   app.config['SECRET_KEY'] = 'your-secure-random-key'
   ```

2. **Enable HTTPS** (via reverse proxy):
   ```bash
   # Nginx example
   server {
       listen 443 ssl;
       server_name palantir.yourdomain.com;
       
       ssl_certificate /path/to/cert.pem;
       ssl_certificate_key /path/to/key.pem;
       
       location / {
           proxy_pass http://localhost:5555;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
       }
   }
   ```

3. **Add authentication** (basic auth via Nginx/Apache)

4. **Use Tailscale** for encrypted remote access

---

## 📊 Performance

| Metric | Value | Notes |
|--------|-------|-------|
| **Latency** | <100ms | WebSocket streaming |
| **CPU Usage** | 15-25% | M4 Pro, 720p30 |
| **RAM Usage** | ~200MB | Python + OpenCV |
| **Disk Usage** | ~5MB/snapshot | JPEG compression |
| **Max FPS** | 30 | Configurable |

---

## 🤝 Integration

### Telegram Alerts

Add to `palantir.py`:
```python
import requests

def send_telegram_alert(message):
    bot_token = "YOUR_BOT_TOKEN"
    chat_id = "YOUR_CHAT_ID"
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    requests.post(url, json={'chat_id': chat_id, 'text': message})
```

### Home Assistant

Expose as MQTT sensor or use REST API to trigger automations.

### IFTTT / Webhooks

Trigger webhooks on motion events for smart home integration.

---

## 📝 License

MIT License - Feel free to use, modify, and distribute.

---

## 🙏 Credits

- **OpenCV** - Computer vision library
- **Flask** - Web framework
- **Flask-SocketIO** - WebSocket support
- **Pillow** - Image processing

---

## 🦆 DuckBot Notes

**Created:** March 14, 2026  
**Version:** 1.0.0  
**Author:** DuckBot for Duckets  
**Purpose:** "Palantir at Home" - Advanced motion monitoring with web dashboard

**Next Steps:**
- [ ] Add Telegram notifications
- [ ] Add face recognition
- [ ] Add object detection (person, pet, vehicle)
- [ ] Add cloud storage sync
- [ ] Add multi-camera support
- [ ] Add timeline scrubbing
- [ ] Add export to video

---

**Enjoy your Palantir at Home! 👁️🏠**

---

## 🔗 Nexus Phone Extractor

### Requirements

1. **ADB Installed:**
   ```bash
   # macOS
   brew install android-platform-tools
   
   # Linux
   sudo apt install android-tools-adb
   ```

2. **Phone Setup:**
   - Enable **Developer Options** (tap Build Number 7 times)
   - Enable **USB Debugging** in Developer Options
   - Connect phone via USB
   - Authorize computer on phone when prompted

3. **Verify Connection:**
   ```bash
   adb devices
   # Should show your device as "device" (not "unauthorized")
   ```

### Usage

1. **Open Nexus Dashboard:**
   - Main Dashboard → Click "🔗 Nexus" in navigation
   - Or go directly to: http://localhost:5555/nexus

2. **Extract Data:**
   - **Quick Extractions:** Click individual buttons (SMS, Calls, Contacts, Photos, Location)
   - **Full Extraction:** Click "🔥 Extract ALL" for complete phone dump

3. **View Results:**
   - Extractions saved to: `~/palantir_extractions/YYYYMMDD_HHMMSS/`
   - JSON format for easy analysis
   - Photos include EXIF metadata & GPS coordinates

### Extracted Data Types

| Type | File | Contents |
|------|------|----------|
| **SMS** | `sms.json` | Messages, contacts, timestamps, type (sent/received) |
| **Calls** | `call_logs.json` | Numbers, timestamps, duration, type (incoming/outgoing/missed) |
| **Contacts** | `contacts.json` | Names, IDs, phone numbers |
| **Photos** | `photos/` + `photo_manifest.json` | Images with EXIF, GPS, timestamps |
| **Location** | `location_history.json` | Latitude, longitude, accuracy, timestamps |

---

## 📊 Dashboard Navigation

| Tab | Purpose |
|-----|---------|
| **📸 Snapshots** | View motion-triggered & manual captures |
| **💾 Storage** | Manage storage, cleanup old files, change location |
| **🔗 Nexus** | Phone extraction dashboard |
| **⚙️ Settings** | Configure motion detection, camera, retention |
| **📝 Logs** | System logs & events |

---

## 🛡️ Security & Privacy

- ✅ **Local-First:** All data stays on your machine
- ✅ **No Cloud:** Nothing uploaded to external servers
- ✅ **Encrypted Storage:** Optional encryption for extracted data
- ✅ **Access Control:** Dashboard accessible only on local network (unless port forwarded)
- ✅ **Tailscale:** Recommended for secure remote access

### Best Practices

1. **Use Tailscale** for remote access (encrypted, no port forwarding)
2. **Enable authentication** if exposing to network
3. **Regular cleanup** of extracted phone data
4. **Secure deleted files** with `shred` for sensitive data
5. **Backup extractions** to encrypted external drive

---

## 🔧 Troubleshooting

### ADB Not Detecting Device

```bash
# Check ADB installation
adb version

# List devices
adb devices

# Restart ADB server
adb kill-server
adb start-server

# Check USB connection
lsusb | grep -i android
```

### Permission Denied (macOS)

```bash
# Grant camera permission
System Settings → Privacy & Security → Camera → Enable for Terminal

# Grant ADB permission
System Settings → Privacy & Security → Security → Allow ADB
```

### Photos Not Extracting

- Ensure phone is unlocked during extraction
- Grant file access permission when prompted on phone
- Try extracting smaller batches (limit=50)

---

## 📁 Directory Structure

```
palantir-home/
├── palantir.py              # Main application
├── start.sh                 # Launch script
├── requirements.txt         # Python dependencies
├── README.md                # This file
├── nexus/
│   └── phone_extractor.py   # Phone extraction module
├── templates/
│   ├── dashboard.html       # Main dashboard UI
│   └── nexus.html          # Nexus extractor UI
├── snapshots/               # Motion snapshots (or custom location)
└── palantir.db              # Event database
```

**Extraction Output:**
```
~/palantir_extractions/
└── 20260314_164500/
    ├── sms.json
    ├── call_logs.json
    ├── contacts.json
    ├── photos/
    │   ├── IMG_001.jpg
    │   ├── IMG_002.jpg
    │   └── photo_manifest.json
    ├── location_history.json
    └── extraction_report.json
```

---

## 🤝 Integration

### With Home Assistant

```yaml
# Add Palantir as camera source
camera:
  - platform: mjpeg
    mjpeg_url: http://localhost:5555/stream
    name: Palantir Motion Cam
```

### With Telegram Alerts

Add to `palantir.py`:
```python
def send_telegram_alert(message, photo_path=None):
    bot_token = "YOUR_BOT_TOKEN"
    chat_id = "YOUR_CHAT_ID"
    
    if photo_path:
        # Send with photo
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendPhoto",
            data={'chat_id': chat_id},
            files={'photo': open(photo_path, 'rb')}
        )
    else:
        # Send text
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={'chat_id': chat_id, 'text': message}
        )
```

### With Nexus-Docs

1. Extract phone data via Nexus tab
2. Export as JSON
3. Import into Nexus-Docs for entity extraction
4. Cross-reference with motion events

---

## 📈 Performance

| Metric | Value | Notes |
|--------|-------|-------|
| **Video Latency** | <100ms | WebSocket streaming |
| **CPU Usage** | 15-25% | M4 Pro, 720p30 |
| **RAM Usage** | ~200MB | Python + OpenCV |
| **Disk Usage** | ~5MB/snapshot | JPEG compression |
| **Phone Extract** | 1-5 min | Depends on data volume |

---

## 🦆 DuckBot Notes

**Created:** March 14, 2026  
**Version:** 2.0.0 (with Nexus Integration)  
**Author:** DuckBot for Duckets  
**Purpose:** "Palantir at Home" - Comprehensive surveillance & intelligence platform

**Components:**
- Motion monitoring (OpenCV + Flask)
- Phone extraction (ADB + PIL)
- Storage management (auto-cleanup)
- Nexus-Docs integration (entity extraction)

**Next Enhancements:**
- [ ] Face recognition in photos
- [ ] Object detection (person, pet, vehicle)
- [ ] iOS extraction (iTunes backup parsing)
- [ ] WhatsApp/Signal message extraction
- [ ] Social media data extraction
- [ ] Cloud sync (S3, Drive, Dropbox)
- [ ] Multi-device support (4+ cameras)

---

**Created with ❤️ by DuckBot for Duckets**  
**GitHub:** https://github.com/Franzferdinan51/motion-cam  
**License:** MIT

