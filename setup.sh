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

echo "------------------------------------------------"
echo "Setup Complete!"
echo "You can check status using: sudo systemctl status upbit-bot"
echo "Your dashboard will be at: http://YOUR_VM_IP:8501"
echo "------------------------------------------------"
