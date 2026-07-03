#!/bin/bash
#
# Start Parcel Map Annotator — double-click this file (macOS) to launch the web
# app and open it in your default browser. No API keys; runs fully on-device.
#
# Keep this file in the project root next to the `parcelmap/` folder and `.venv`.

# Finder launches scripts from your home directory, so always move into this
# script's own folder first.
cd "$(dirname "$0")" || { echo "Cannot find project folder."; exit 1; }

# Make sure the virtual environment exists before trying to run.
if [ ! -x ".venv/bin/python" ]; then
  echo "Virtual environment (.venv) not found in this folder."
  echo ""
  echo "Set it up once by running these two commands in Terminal:"
  echo "    python3 -m venv .venv"
  echo "    .venv/bin/pip install -r requirements.txt"
  echo ""
  read -n 1 -s -r -p "Press any key to close this window..."
  exit 1
fi

# Port 5050 — macOS AirPlay Receiver occupies the usual 5000.
PORT=5050
URL="http://127.0.0.1:${PORT}/"

echo "============================================================"
echo "  Parcel Map Annotator"
echo "============================================================"
echo "Starting the local web server at:"
echo "    ${URL}"
echo ""

# Launch the Flask app in the background.
.venv/bin/python -m parcelmap.app &
SERVER_PID=$!

# Wait until the server responds, then open it in the default browser.
for _ in $(seq 1 40); do
  if curl -sf -o /dev/null "${URL}" 2>/dev/null; then
    open "${URL}"
    echo "Browser opened. The app is ready to use."
    break
  fi
  sleep 0.25
done

echo ""
echo "Keep this window open while you use the app."
echo "Close this window (or press Ctrl-C) to stop the server."
echo "------------------------------------------------------------"
echo ""

# Run the server in the foreground so Ctrl-C (or closing the window) stops it.
trap 'kill "$SERVER_PID" 2>/dev/null' INT
wait "$SERVER_PID"
echo "Server stopped."
