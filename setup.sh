#!/bin/bash

# 1. System Update
echo "Updating system..."
sudo apt update && sudo apt upgrade -y

# 2. Python & Dependencies Installation
echo "Installing Python and dependencies..."
sudo apt install python3 python3-pip python3-venv -y

# 3. Virtual Environment Setup
echo "Setting up virtual environment..."
python3 -m venv venv
source venv/bin/activate

# 4. Python Packages Installation
echo "Installing Python packages..."
pip install --upgrade pip
pip install pyupbit streamlit pandas plotly python-dotenv requests websocket-client streamlit-autorefresh PyJWT

# 5. Systemd Service Registration
echo "Registering upbit-bot service..."
SERVICE_FILE="/etc/systemd/system/upbit-bot.service"
WORKING_DIR=$(pwd)
USER_NAME=$(whoami)

sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=Upbit Auto Trading Bot (Streamlit)
After=network.target

[Service]
User=$USER_NAME
WorkingDirectory=$WORKING_DIR
ExecStart=$WORKING_DIR/venv/bin/streamlit run app.py --server.port 8501 --server.address 0.0.0.0
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# 6. Reload Systemd and Enable Service
echo "Enabling and starting service..."
sudo systemctl daemon-reload
sudo systemctl enable upbit-bot
sudo systemctl start upbit-bot

# 7. Register Auto-Update Service & Timer (Checks every 1 minute)
echo "Registering auto-updater service and timer..."
UPDATE_SERVICE="/etc/systemd/system/upbit-update.service"
UPDATE_TIMER="/etc/systemd/system/upbit-update.timer"

sudo bash -c "cat > $UPDATE_SERVICE" <<EOF
[Unit]
Description=Upbit Bot Auto-Updater
After=network.target

[Service]
Type=oneshot
User=$USER_NAME
WorkingDirectory=$WORKING_DIR
ExecStart=/bin/bash $WORKING_DIR/update_bot.sh
EOF

sudo bash -c "cat > $UPDATE_TIMER" <<EOF
[Unit]
Description=Run Upbit Bot Auto-Updater every minute

[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
Unit=upbit-update.service

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable upbit-update.timer
sudo systemctl start upbit-update.timer

echo "------------------------------------------------"
echo "Setup & Auto-Updater Enabled!"
echo "The bot will automatically update every minute when you push to GitHub."
echo "Check bot status: sudo systemctl status upbit-bot"
echo "Check updater info: sudo systemctl status upbit-update.timer"
echo "Your dashboard: http://YOUR_VM_IP:8501"
echo "------------------------------------------------"
