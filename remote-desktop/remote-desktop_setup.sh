#!/bin/bash
# Setup script for creating a Morph Cloud VM with a remote desktop.
# Bash version that runs commands via SSH using the morphcloud CLI.

set -e  # Exit on error

# Configuration
VCPUS=4
MEMORY=4096  # 4GB
DISK_SIZE=8192  # 8GB
SNAPSHOT_TYPE="base"

# Function to find or create a snapshot with matching configuration
find_or_create_snapshot() {
  echo "Looking for existing snapshot with matching configuration..."
  
  # Try to find an existing snapshot with matching metadata
  EXISTING_SNAPSHOT=$(morphcloud snapshot list -m "type=$SNAPSHOT_TYPE" -m "vcpus=$VCPUS" -m "memory=$MEMORY" -m "disk_size=$DISK_SIZE" --json | grep '"id":' | head -1 | cut -d '"' -f 4)
  
  if [ ! -z "$EXISTING_SNAPSHOT" ]; then
    echo "Found existing snapshot $EXISTING_SNAPSHOT with matching configuration"
    SNAPSHOT_ID="$EXISTING_SNAPSHOT"
  else
    echo "No matching snapshot found. Creating new snapshot..."
    SNAPSHOT_ID=$(morphcloud snapshot create --vcpus "$VCPUS" --memory "$MEMORY" --disk-size "$DISK_SIZE")
    
    # Add metadata to the snapshot
    morphcloud snapshot set-metadata "$SNAPSHOT_ID" "type=$SNAPSHOT_TYPE" "vcpus=$VCPUS" "memory=$MEMORY" "disk_size=$DISK_SIZE" > /dev/null
  fi
  
  echo "$SNAPSHOT_ID"
}

# Main setup script
setup_remote_desktop() {
  INSTANCE_ID=$1
  
  echo "Setting up remote desktop environment..."
  
  # Step 1: Ensure Python3 is installed with non-interactive mode
  echo -e "\n--- 1. Installing Python3 ---"
  morphcloud instance exec "$INSTANCE_ID" "sudo DEBIAN_FRONTEND=noninteractive apt-get update -q && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3"
  
  # Step 2: Install required packages with non-interactive mode
  echo -e "\n--- 2. Installing required packages ---"
  morphcloud instance exec "$INSTANCE_ID" "sudo DEBIAN_FRONTEND=noninteractive apt-get update -q && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q -o Dpkg::Options::=\"--force-confdef\" -o Dpkg::Options::=\"--force-confold\" xfce4 xfce4-goodies tigervnc-standalone-server tigervnc-common python3 python3-pip python3-websockify git net-tools nginx dbus dbus-x11 xfonts-base"
  
  # Step 3: Clone noVNC repository
  echo -e "\n--- 3. Cloning noVNC repository ---"
  morphcloud instance exec "$INSTANCE_ID" "sudo git clone https://github.com/novnc/noVNC.git /opt/noVNC"
  
  # Step 4: Kill any existing VNC processes
  echo -e "\n--- 4. Killing existing VNC processes ---"
  morphcloud instance exec "$INSTANCE_ID" "sudo pkill Xvnc || true; sudo rm -f /tmp/.X1-lock /tmp/.X11-unix/X1 || true"
  
  # Step 5: Create XFCE config directories
  echo -e "\n--- 5. Creating XFCE config directories ---"
  morphcloud instance exec "$INSTANCE_ID" "sudo mkdir -p /root/.config/xfce4 /root/.config/xfce4-session /root/.config/autostart /root/.config/systemd"
  
  # Step 6: Create VNC server service
  echo -e "\n--- 6. Creating VNC server service ---"
  cat > /tmp/vncserver.service << 'EOF'
[Unit]
Description=VNC Server for X11
After=syslog.target network.target

[Service]
Type=simple
User=root
Environment=HOME=/root
Environment=DISPLAY=:1
ExecStartPre=-/bin/rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
ExecStart=/usr/bin/Xvnc :1 -geometry 1280x800 -depth 24 -SecurityTypes None -localhost no
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  morphcloud instance copy /tmp/vncserver.service "$INSTANCE_ID":/tmp/
  morphcloud instance exec "$INSTANCE_ID" "sudo mv /tmp/vncserver.service /etc/systemd/system/"
  
  # Step 7: Create session startup script
  echo -e "\n--- 7. Creating XFCE session startup script ---"
  cat > /tmp/start-xfce-session << 'EOF'
#!/bin/bash
export DISPLAY=:1
export HOME=/root
export XDG_CONFIG_HOME=/root/.config
export XDG_CACHE_HOME=/root/.cache
export XDG_DATA_HOME=/root/.local/share
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/dbus/system_bus_socket

# Start dbus if not running
if [ -z "$DBUS_SESSION_BUS_PID" ]; then
  eval $(dbus-launch --sh-syntax)
fi

# Ensure xfconfd is running
/usr/lib/x86_64-linux-gnu/xfce4/xfconf/xfconfd &

# Wait for xfconfd to start
sleep 2

# Start XFCE session
exec startxfce4
EOF
  morphcloud instance copy /tmp/start-xfce-session "$INSTANCE_ID":/tmp/
  morphcloud instance exec "$INSTANCE_ID" "sudo mv /tmp/start-xfce-session /usr/local/bin/ && sudo chmod +x /usr/local/bin/start-xfce-session"
  
  # Step 8: Create XFCE session service
  echo -e "\n--- 8. Creating XFCE session service ---"
  cat > /tmp/xfce-session.service << 'EOF'
[Unit]
Description=XFCE Session
After=vncserver.service dbus.service
Requires=vncserver.service dbus.service

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/start-xfce-session
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  morphcloud instance copy /tmp/xfce-session.service "$INSTANCE_ID":/tmp/
  morphcloud instance exec "$INSTANCE_ID" "sudo mv /tmp/xfce-session.service /etc/systemd/system/"
  
  # Step 9: Create noVNC service
  echo -e "\n--- 9. Creating noVNC service ---"
  cat > /tmp/novnc.service << 'EOF'
[Unit]
Description=noVNC service
After=vncserver.service
Requires=vncserver.service

[Service]
Type=simple
User=root
ExecStart=/usr/bin/websockify --web=/opt/noVNC 6080 localhost:5901
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  morphcloud instance copy /tmp/novnc.service "$INSTANCE_ID":/tmp/
  morphcloud instance exec "$INSTANCE_ID" "sudo mv /tmp/novnc.service /etc/systemd/system/"
  
  # Step 10: Configure nginx as reverse proxy
  echo -e "\n--- 10. Configuring nginx as reverse proxy ---"
  cat > /tmp/novnc-nginx << 'EOF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://localhost:6080/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
EOF
  morphcloud instance copy /tmp/novnc-nginx "$INSTANCE_ID":/tmp/
  morphcloud instance exec "$INSTANCE_ID" "sudo mv /tmp/novnc-nginx /etc/nginx/sites-available/novnc"
  
  # Step 11: Enable nginx site and disable default
  echo -e "\n--- 11. Enabling nginx site and disabling default ---"
  morphcloud instance exec "$INSTANCE_ID" "sudo ln -sf /etc/nginx/sites-available/novnc /etc/nginx/sites-enabled/novnc && sudo rm -f /etc/nginx/sites-enabled/default"
  
  # Step 12: Start and enable services
  echo -e "\n--- 12. Starting and enabling services ---"
  for SERVICE in vncserver xfce-session novnc nginx; do
    morphcloud instance exec "$INSTANCE_ID" "sudo systemctl daemon-reload && sudo systemctl enable $SERVICE && sudo systemctl restart $SERVICE"
  done
  
  # Step 13: Check service status and retry if needed
  echo -e "\n--- 13. Verifying services are running ---"
  for SERVICE in vncserver xfce-session novnc nginx; do
    cat > /tmp/check_${SERVICE}.sh << EOF
#!/bin/bash
for i in {1..3}; do
  if systemctl is-active ${SERVICE} > /dev/null; then
    echo '${SERVICE} is running'
    break
  fi
  echo 'Waiting for ${SERVICE} to start...'
  systemctl restart ${SERVICE}
  sleep 3
done
EOF
    morphcloud instance copy /tmp/check_${SERVICE}.sh "$INSTANCE_ID":/tmp/
    morphcloud instance exec "$INSTANCE_ID" "chmod +x /tmp/check_${SERVICE}.sh && sudo /tmp/check_${SERVICE}.sh"
  done
  
  # Step 14: Expose HTTP service
  echo -e "\n--- 14. Exposing HTTP service ---"
  morphcloud instance expose-http "$INSTANCE_ID" desktop 80
  
  # Allow time for services to fully start
  echo -e "\nWaiting for services to fully start..."
  sleep 10
  
  echo -e "\nRemote desktop setup complete!"
}

# Main script execution
echo "Starting setup for Remote Desktop on Morph Cloud..."

# Get or create appropriate snapshot
# Capture only the last line which contains just the ID
SNAPSHOT_ID=$(find_or_create_snapshot | tail -n 1)
echo "Using snapshot $SNAPSHOT_ID"

# Start an instance from the snapshot
echo "Starting instance from snapshot $SNAPSHOT_ID..."
INSTANCE_ID=$(morphcloud instance start "$SNAPSHOT_ID")
echo "Started instance $INSTANCE_ID"

# Instance is ready immediately

# Set up the remote desktop
setup_remote_desktop "$INSTANCE_ID"

# Get the desktop URL
DESKTOP_URL=$(morphcloud instance get "$INSTANCE_ID" | grep -o '"url":"[^"]*"' | grep desktop | cut -d'"' -f4)

echo -e "\nAccess your remote desktop at: "
echo "https://desktop-${INSTANCE_ID//_/-}.http.cloud.morph.so/vnc_lite.html"

echo -e "\nInstance ID: $INSTANCE_ID"
echo "To SSH into this instance: morphcloud instance ssh $INSTANCE_ID"
echo "To stop this instance: morphcloud instance stop $INSTANCE_ID"

# Create a final snapshot
echo -e "\nCreating a final snapshot for future use..."
FINAL_SNAPSHOT_ID=$(morphcloud instance snapshot "$INSTANCE_ID")
morphcloud snapshot set-metadata "$FINAL_SNAPSHOT_ID" "type=remote-desktop" "description=Remote desktop environment with XFCE and noVNC"

echo "Final snapshot created: $FINAL_SNAPSHOT_ID"
echo "To start a new instance from this snapshot, run: morphcloud instance start $FINAL_SNAPSHOT_ID"
