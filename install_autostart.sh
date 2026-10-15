#!/bin/bash
# Makes the TrueView IVR start by itself every time the Raspberry Pi turns on,
# and restart automatically if it ever stops.
#
# Run ONCE, from the folder that holds trueview_ivr.py, as your normal user (not sudo):
#     bash install_autostart.sh
#
# Useful commands afterwards:
#     systemctl --user status trueview-ivr      is it running?
#     journalctl --user -u trueview-ivr -f      watch the live log (Ctrl+C to stop watching)
#     systemctl --user restart trueview-ivr     restart after editing the script
#     systemctl --user stop trueview-ivr        stop it until the next boot
#     systemctl --user disable trueview-ivr     stop it starting at boot

set -e

IVR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="trueview-ivr"
SERVICE_DIR="$HOME/.config/systemd/user"

if [ "$(id -u)" -eq 0 ]; then
    echo "Please run this as your normal user, without sudo: bash install_autostart.sh"
    exit 1
fi
if [ ! -f "$IVR_DIR/trueview_ivr.py" ]; then
    echo "trueview_ivr.py not found in $IVR_DIR. Put this script next to it and run it again."
    exit 1
fi
if [ ! -d "$IVR_DIR/audio" ]; then
    echo "Warning: no audio folder in $IVR_DIR. Unzip audio_draft.zip there, or callers will hear silence."
fi

echo "1/4 Installing Python packages (asks for your password)..."
sudo apt-get update -qq && sudo apt-get install -y python3-serial python3-pygame >/dev/null

echo "2/4 Allowing $USER to use the serial port..."
sudo usermod -aG dialout "$USER"

echo "3/4 Letting the IVR start at boot without anyone logging in..."
sudo loginctl enable-linger "$USER"

echo "4/4 Creating the $SERVICE_NAME service..."
mkdir -p "$SERVICE_DIR"
cat > "$SERVICE_DIR/$SERVICE_NAME.service" <<EOF
[Unit]
Description=TrueView CCTV IVR (Raspberry Pi + SIM800L)
After=default.target

[Service]
WorkingDirectory=$IVR_DIR
ExecStart=/usr/bin/python3 -u "$IVR_DIR/trueview_ivr.py"
Restart=always
RestartSec=5
# Give the SIM800L and sound card a moment to come up after power-on
ExecStartPre=/bin/sleep 10

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable "$SERVICE_NAME" >/dev/null
systemctl --user restart "$SERVICE_NAME"

sleep 3
echo
if systemctl --user is-active --quiet "$SERVICE_NAME"; then
    echo "Done. The IVR is running now and will start by itself on every boot."
else
    echo "The service was created but isn't running yet. See why with:"
    echo "    journalctl --user -u $SERVICE_NAME -n 30"
fi
echo "Watch the live log with:  journalctl --user -u $SERVICE_NAME -f"
echo "If this is the first time, reboot once (sudo reboot) so the serial-port permission applies."
