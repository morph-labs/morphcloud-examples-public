#!/bin/bash
# Setup script for creating a Morph Cloud VM with OpenVSCode Server.
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
setup_vscode_server() {
  INSTANCE_ID=$1
  
  echo "Setting up OpenVSCode Server environment..."
  
  # Step 1: Ensure Python3 is installed - use non-interactive mode
  echo -e "\n--- 1. Installing Python3 ---"
  morphcloud instance exec "$INSTANCE_ID" "sudo DEBIAN_FRONTEND=noninteractive apt-get update -q && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3"
  
  # Step 2: Install Docker and dependencies - use non-interactive mode
  echo -e "\n--- 2. Installing Docker and dependencies ---"
  morphcloud instance exec "$INSTANCE_ID" "sudo DEBIAN_FRONTEND=noninteractive apt-get update -q && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q -o Dpkg::Options::=\"--force-confdef\" -o Dpkg::Options::=\"--force-confold\" docker.io python3-docker python3-requests"
  
  # Step 3: Start and enable Docker service
  echo -e "\n--- 3. Starting and enabling Docker service ---"
  morphcloud instance exec "$INSTANCE_ID" "sudo systemctl start docker && sudo systemctl enable docker"
  
  # Step 4: Create workspace directory
  echo -e "\n--- 4. Creating workspace directory ---"
  morphcloud instance exec "$INSTANCE_ID" "sudo mkdir -p /opt/vscode-workspace && sudo chmod 755 /opt/vscode-workspace"
  
  # Step 5: Run OpenVSCode Server container
  echo -e "\n--- 5. Running OpenVSCode Server container ---"
  # Check if Docker is running before proceeding
  morphcloud instance exec "$INSTANCE_ID" "sudo docker ps > /dev/null || (sudo systemctl restart docker && sleep 3)"
  
  morphcloud instance exec "$INSTANCE_ID" "sudo docker run -d --init --name openvscode-server -p 3000:3000 -v \"/opt/vscode-workspace:/home/workspace:cached\" --restart unless-stopped gitpod/openvscode-server"
  
  # Step 6: Expose HTTP service
  echo -e "\n--- 6. Exposing HTTP service ---"
  morphcloud instance expose-http "$INSTANCE_ID" vscode 3000
  
  # Step 7: Wait for container to be fully running
  echo -e "\nWaiting for VSCode Server to start..."
  cat > /tmp/check_container.sh << 'EOF'
#!/bin/bash
for i in {1..12}; do
  if docker ps | grep -q openvscode-server; then
    echo 'Container is running'
    break
  fi
  echo "Waiting for container to start... (attempt $i/12)"
  sleep 5
done
EOF
  morphcloud instance copy /tmp/check_container.sh "$INSTANCE_ID":/tmp/
  morphcloud instance exec "$INSTANCE_ID" "chmod +x /tmp/check_container.sh && sudo /tmp/check_container.sh"
  
  echo -e "\nOpenVSCode Server setup complete!"
}

# Main script execution
echo "Starting setup for OpenVSCode Server on Morph Cloud..."

# Get or create appropriate snapshot
# Capture only the last line which contains just the ID
SNAPSHOT_ID=$(find_or_create_snapshot | tail -n 1)
echo "Using snapshot $SNAPSHOT_ID"

# Start an instance from the snapshot
echo "Starting instance from snapshot $SNAPSHOT_ID..."
INSTANCE_ID=$(morphcloud instance start "$SNAPSHOT_ID")
echo "Started instance $INSTANCE_ID"

# Instance is ready immediately

# Set up the VSCode server
setup_vscode_server "$INSTANCE_ID"

# Get the VSCode URL
VSCODE_URL=$(morphcloud instance get "$INSTANCE_ID" | grep -o '"url":"[^"]*"' | grep vscode | cut -d'"' -f4)

if [ ! -z "$VSCODE_URL" ]; then
  echo -e "\nAccess your VSCode Server at: $VSCODE_URL"
  echo "Your workspace is mounted at: /home/workspace"
else
  echo -e "\nCould not find VSCode HTTP service URL. You can manually access it at:"
  echo "https://vscode-${INSTANCE_ID//_/-}.http.cloud.morph.so"
fi

echo -e "\nInstance ID: $INSTANCE_ID"
echo "To SSH into this instance: morphcloud instance ssh $INSTANCE_ID"
echo "To stop this instance: morphcloud instance stop $INSTANCE_ID"

# Create a final snapshot
echo -e "\nCreating a final snapshot for future use..."
FINAL_SNAPSHOT_ID=$(morphcloud instance snapshot "$INSTANCE_ID")
morphcloud snapshot set-metadata "$FINAL_SNAPSHOT_ID" "type=openvscode-server" "description=OpenVSCode Server environment"

echo "Final snapshot created: $FINAL_SNAPSHOT_ID"
echo "To start a new instance from this snapshot, run: morphcloud instance start $FINAL_SNAPSHOT_ID"
