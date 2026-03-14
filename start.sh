#!/bin/bash
# Palantir at Home - Installation & Launch Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "👁️  PALANTIR AT HOME - Installer"
echo "================================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.8+"
    exit 1
fi

echo "✅ Python: $(python3 --version)"

# Check OpenCV
if ! python3 -c "import cv2" &> /dev/null; then
    echo "📦 Installing Python dependencies..."
    pip3 install -r requirements.txt --break-system-packages
fi

# Create directories
mkdir -p snapshots

# Show configuration
echo ""
echo "📋 Configuration:"
echo "   Camera: 0 = Logitech C170, 1 = iPhone Camera"
echo "   Port: 5555"
echo "   Dashboard: http://localhost:5555"
echo ""

# Camera test
echo "📷 Testing camera access..."
python3 << 'EOF'
import cv2
cap = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)
if cap.isOpened():
    print("✅ Camera 0 (Logitech) accessible")
    cap.release()
else:
    print("⚠️  Camera 0 not accessible")

cap = cv2.VideoCapture(1, cv2.CAP_AVFOUNDATION)
if cap.isOpened():
    print("✅ Camera 1 (iPhone) accessible")
    cap.release()
else:
    print("⚠️  Camera 1 not accessible")
EOF

echo ""
echo "🚀 Starting Palantir..."
echo "   Dashboard: http://localhost:5555"
echo "   Remote Access: http://$(hostname -I | awk '{print $1}'):5555"
echo ""
echo "Press Ctrl+C to stop"
echo "================================"
echo ""

python3 palantir.py
