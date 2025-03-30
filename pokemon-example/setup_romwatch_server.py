#!/usr/bin/env python3
"""
Setup script for creating a Morph Cloud VM with a Pokemon game server that watches for ROM files.
Uses snapshot caching for faster setup and SFTP for file uploads.
The server watches for ROM files and automatically starts when a ROM is detected.
"""

import os
import sys
import time
import glob
import argparse
from pathlib import Path
from dotenv import load_dotenv
from morphcloud.api import MorphCloudClient

# Load environment variables from .env file if it exists
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='Set up a Pokemon Game Server on MorphVM that watches for ROM uploads')
    parser.add_argument('--rom', type=str, default=None, help='Optional: Path to the Pokemon ROM file to upload initially')
    parser.add_argument('--port', type=int, default=9876, help='Port to expose for client connections')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode (no display)')
    parser.add_argument('--sound', action='store_true', help='Enable sound (only applicable with display)')
    parser.add_argument('--watch-dir', type=str, default='roms', help='Directory name to watch for ROM uploads')
    return parser.parse_args()

def upload_files_via_sftp(instance, local_dir="."):
    """Upload project files to the instance using Paramiko SFTP"""
    print(f"\n=== 📤 Uploading project files ===")
    
    # Connect via SSH and create directory
    print("Ensuring project directory exists...")
    instance.exec("mkdir -p /root/pokemon && chmod 777 /root/pokemon")
    
    # Get an SSH client from the instance
    ssh_client = instance.ssh_connect()
    sftp = None
    
    try:
        # Open SFTP session
        sftp = ssh_client.open_sftp()
        
        # Upload Python files
        python_files = glob.glob(os.path.join(local_dir, "*.py"))
        for file_path in python_files:
            filename = os.path.basename(file_path)
            remote_path = f"/root/pokemon/{filename}"
            print(f"Uploading {filename}...")
            sftp.put(file_path, remote_path)
            sftp.chmod(remote_path, 0o644)
        
        # Upload requirements.txt if it exists
        req_path = os.path.join(local_dir, "requirements.txt")
        if os.path.exists(req_path):
            print("Uploading requirements.txt...")
            sftp.put(req_path, "/root/pokemon/requirements.txt")
            sftp.chmod("/root/pokemon/requirements.txt", 0o644)
        
        # Upload .env file if it exists
        env_path = os.path.join(local_dir, ".env")
        if os.path.exists(env_path):
            remote_path = f"/root/pokemon/.env"
            print(f"Uploading .env file...")
            sftp.put(env_path, remote_path)
            sftp.chmod(remote_path, 0o644)
        
        # Create agent directory and upload agent files
        agent_dir = os.path.join(local_dir, "agent")
        if os.path.exists(agent_dir) and os.path.isdir(agent_dir):
            # Create remote agent directory
            instance.exec("mkdir -p /root/pokemon/agent && chmod 777 /root/pokemon/agent")
            
            # Upload all files in agent directory
            agent_files = glob.glob(os.path.join(agent_dir, "*.py"))
            for file_path in agent_files:
                filename = os.path.basename(file_path)
                remote_path = f"/root/pokemon/agent/{filename}"
                print(f"Uploading agent file {filename}...")
                sftp.put(file_path, remote_path)
                sftp.chmod(remote_path, 0o644)
                
            # Create __init__.py if it's not there
            init_path = os.path.join(agent_dir, "__init__.py")
            if not os.path.exists(init_path):
                sftp.open(f"/root/pokemon/agent/__init__.py", 'w').close()
                sftp.chmod(f"/root/pokemon/agent/__init__.py", 0o644)
        
        print(f"✅ All project files uploaded successfully")
        return True
    except Exception as e:
        print(f"❌ Error uploading files: {e}")
        return False
    finally:
        if sftp:
            sftp.close()
        ssh_client.close()

def upload_rom_via_sftp(instance, local_path, watch_dir):
    """Upload a ROM file to the instance using Paramiko SFTP"""
    if not os.path.exists(local_path):
        print(f"Error: ROM file not found at {local_path}")
        return False
    
    filename = os.path.basename(local_path)
    remote_dir = f"/root/pokemon/{watch_dir}"
    remote_path = f"{remote_dir}/{filename}"
    
    print(f"\n=== 📤 Uploading ROM file: {local_path} ===")
    
    # Connect via SSH and create directory
    print(f"Ensuring ROM watch directory exists: {remote_dir}")
    instance.exec(f"mkdir -p {remote_dir} && chmod 777 {remote_dir}")
    
    # Get an SSH client from the instance
    ssh_client = instance.ssh_connect()
    sftp = None
    
    try:
        # Open SFTP session
        sftp = ssh_client.open_sftp()
        
        # Upload the file
        print(f"Uploading {filename} to {remote_path}...")
        sftp.put(local_path, remote_path)
        
        # Set permissions
        sftp.chmod(remote_path, 0o644)
        
        print(f"✅ ROM file uploaded successfully")
        return True
    except Exception as e:
        print(f"❌ Error uploading ROM file: {e}")
        return False
    finally:
        if sftp:
            sftp.close()
        ssh_client.close()

def setup_startup_script(instance, args):
    """Create a startup script to run the ROM watch server"""
    print("\n=== 🎮 Creating startup script ===")
    
    # Handle options
    headless_opt = "" if args.headless else "--display"
    sound_opt = "--sound" if args.sound and not args.headless else ""
    
    # Create the startup script file with watch directory
    script_content = f"""#!/bin/bash
cd /root/pokemon
export PATH="/root/.local/bin:$PATH"
source /root/pokemon/.venv/bin/activate
python rom_watch_server.py --host 0.0.0.0 --port {args.port} {headless_opt} {sound_opt} --watch-dir "{args.watch_dir}"
"""
    
    # Write the script content to a file on the instance
    result = instance.exec(f"cat > /root/start-pokemon-server.sh << 'EOFSCRIPT'\n{script_content}EOFSCRIPT")
    if result.exit_code != 0:
        print(f"❌ Error creating startup script: {result.stderr}")
        return False
    
    # Make the script executable
    result = instance.exec("chmod +x /root/start-pokemon-server.sh")
    if result.exit_code != 0:
        print(f"❌ Error making script executable: {result.stderr}")
        return False
    
    # Create service file
    service_content = """[Unit]
Description=Pokemon Game Server (ROM Watch)
After=xfce-session.service network.target
"""
    
    # Add dependency on XFCE if using display mode
    if not args.headless:
        service_content += "Requires=xfce-session.service\n"
    
    service_content += """
[Service]
Type=simple
User=root
"""
    
    # Add DISPLAY environment if using display
    if not args.headless:
        service_content += "Environment=DISPLAY=:1\n"
    
    service_content += """WorkingDirectory=/root/pokemon
ExecStart=/root/start-pokemon-server.sh
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
    
    # Write the service file
    result = instance.exec(f"cat > /etc/systemd/system/pokemon-server.service << 'EOFSERVICE'\n{service_content}EOFSERVICE")
    if result.exit_code != 0:
        print(f"❌ Error creating service file: {result.stderr}")
        return False
    
    # Enable the service
    result = instance.exec("systemctl daemon-reload && systemctl enable pokemon-server")
    if result.exit_code != 0:
        print(f"❌ Error enabling service: {result.stderr}")
        return False
    
    # ===== ADD MCP SERVER SETUP HERE =====
    print("\n=== 🎮 Creating MCP server startup script ===")
    
    # Create MCP server startup script
    mcp_script_content = f"""#!/bin/bash
cd /root/pokemon
export PATH="/root/.local/bin:$PATH"
source /root/pokemon/.venv/bin/activate
python pokemon_mcp_server.py --host 0.0.0.0 --port 8000 {"--headless" if args.headless else ""} {sound_opt}
"""
    
    # Write the MCP script
    result = instance.exec(f"cat > /root/start-mcp-server.sh << 'EOFSCRIPT'\n{mcp_script_content}EOFSCRIPT")
    if result.exit_code != 0:
        print(f"❌ Error creating MCP server startup script: {result.stderr}")
        return False
    
    # Make the script executable
    result = instance.exec("chmod +x /root/start-mcp-server.sh")
    if result.exit_code != 0:
        print(f"❌ Error making MCP script executable: {result.stderr}")
        return False
    
    # Create MCP service file
    mcp_service_content = """[Unit]
Description=Pokemon MCP Server
After=pokemon-server.service
Requires=pokemon-server.service

[Service]
Type=simple
User=root
"""
    
    # Add DISPLAY environment if using display
    if not args.headless:
        mcp_service_content += "Environment=DISPLAY=:1\n"
    
    mcp_service_content += """WorkingDirectory=/root/pokemon
ExecStart=/root/start-mcp-server.sh
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
    
    # Write the MCP service file
    result = instance.exec(f"cat > /etc/systemd/system/pokemon-mcp.service << 'EOFSERVICE'\n{mcp_service_content}EOFSERVICE")
    if result.exit_code != 0:
        print(f"❌ Error creating MCP service file: {result.stderr}")
        return False
    
    # Enable the MCP service
    result = instance.exec("systemctl daemon-reload && systemctl enable pokemon-mcp")
    if result.exit_code != 0:
        print(f"❌ Error enabling MCP service: {result.stderr}")
        return False
    
    print("✅ MCP server startup configured successfully")
    # ===== END MCP SERVER SETUP =====
    
    print("✅ All startup scripts configured successfully")
    return True


def setup_rom_watcher(instance, watch_dir):
    """Set up a ROM file watcher that automatically restarts the server when ROMs are uploaded"""
    print("\n=== 🔄 Setting up ROM file watcher service ===")
    
    # Create the watcher script
    watcher_script = f"""#!/bin/bash
# Script to watch for new ROMs and restart the Pokemon server

WATCH_DIR="/root/pokemon/{watch_dir}"
LOG_FILE="/var/log/rom_watcher.log"

echo "$(date): ROM watcher started for directory $WATCH_DIR" >> $LOG_FILE

while true; do
    inotifywait -e create,moved_to -e close_write --format '%f' "$WATCH_DIR" | while read FILENAME
    do
        if [[ "$FILENAME" == *.gb ]]; then
            echo "$(date): New ROM detected: $FILENAME" >> $LOG_FILE
            echo "$(date): Restarting pokemon-server service" >> $LOG_FILE
            systemctl restart pokemon-server
            echo "$(date): Service restart initiated" >> $LOG_FILE
        fi
    done
done
"""
    
    # Create systemd service file content
    service_file = """[Unit]
Description=ROM file watcher for Pokemon server
After=network.target

[Service]
Type=simple
User=root
ExecStart=/root/pokemon/rom_watcher.sh
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
    
    try:
        # Write the watcher script
        result = instance.exec(f"cat > /root/pokemon/rom_watcher.sh << 'EOFSCRIPT'\n{watcher_script}EOFSCRIPT")
        if result.exit_code != 0:
            print(f"❌ Error creating watcher script: {result.stderr}")
            return False
        
        # Make script executable
        instance.exec("chmod +x /root/pokemon/rom_watcher.sh")
        
        # Create the service file
        result = instance.exec(f"cat > /etc/systemd/system/rom-watcher.service << 'EOFSERVICE'\n{service_file}EOFSERVICE")
        if result.exit_code != 0:
            print(f"❌ Error creating watcher service: {result.stderr}")
            return False
            
        # Enable and start the service
        result = instance.exec("systemctl daemon-reload && systemctl enable rom-watcher && systemctl start rom-watcher")
        if result.exit_code != 0:
            print(f"❌ Error starting watcher service: {result.stderr}")
            return False
            
        print("✅ ROM watcher service configured successfully")
        return True
    except Exception as e:
        print(f"❌ Error setting up ROM watcher: {e}")
        return False

def setup_upload_helper(instance, watch_dir):
    """Create helper scripts for easy ROM uploads"""
    print("\n=== 📤 Setting up ROM upload helper ===")
    
    # Create upload helper HTML page
    upload_html = """<!DOCTYPE html>
<html>
<head>
    <title>Pokemon ROM Uploader</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            line-height: 1.6;
        }
        h1 {
            color: #333;
            border-bottom: 2px solid #eee;
            padding-bottom: 10px;
        }
        .section {
            background-color: #f9f9f9;
            border: 1px solid #ddd;
            padding: 20px;
            border-radius: 5px;
            margin-bottom: 20px;
        }
        .button {
            background-color: #4CAF50;
            border: none;
            color: white;
            padding: 10px 20px;
            text-align: center;
            text-decoration: none;
            display: inline-block;
            font-size: 16px;
            margin: 4px 2px;
            cursor: pointer;
            border-radius: 4px;
        }
        .status {
            margin-top: 20px;
            padding: 10px;
            border-radius: 5px;
        }
        .success {
            background-color: #d4edda;
            border: 1px solid #c3e6cb;
            color: #155724;
        }
        .error {
            background-color: #f8d7da;
            border: 1px solid #f5c6cb;
            color: #721c24;
        }
        .command {
            background-color: #f8f9fa;
            border: 1px solid #ddd;
            padding: 10px;
            border-radius: 4px;
            font-family: monospace;
            margin: 10px 0;
            white-space: nowrap;
            overflow-x: auto;
        }
        .tab {
            overflow: hidden;
            border: 1px solid #ccc;
            background-color: #f1f1f1;
            margin-bottom: 10px;
        }
        .tab button {
            background-color: inherit;
            float: left;
            border: none;
            outline: none;
            cursor: pointer;
            padding: 14px 16px;
            transition: 0.3s;
        }
        .tab button:hover {
            background-color: #ddd;
        }
        .tab button.active {
            background-color: #ccc;
        }
        .tabcontent {
            display: none;
            padding: 12px;
            border: 1px solid #ccc;
            border-top: none;
        }
        #webUpload {
            display: block;
        }
    </style>
</head>
<body>
    <h1>Pokemon ROM Uploader</h1>
    
    <div class="tab">
        <button class="tablinks active" onclick="openTab(event, 'webUpload')">Web Upload</button>
        <button class="tablinks" onclick="openTab(event, 'directUpload')">Fast Direct Upload</button>
        <button class="tablinks" onclick="openTab(event, 'serverStatus')">Server Status</button>
    </div>
    
    <div id="webUpload" class="tabcontent">
        <h2>Upload ROM via Web</h2>
        <p>Select a Game Boy ROM file (.gb) to upload and start the Pokemon game server.</p>
        
        <form id="uploadForm" enctype="multipart/form-data">
            <input type="file" id="romFile" name="file" accept=".gb" required>
            <button type="submit" class="button">Upload ROM</button>
        </form>
        
        <div id="status" class="status" style="display: none;"></div>
    </div>
    
    <div id="directUpload" class="tabcontent">
        <h2>Fast Direct Upload Commands</h2>
        <p>For faster uploads, use these commands from your terminal:</p>
        
        <h3>SCP Command (fastest):</h3>
        <div class="command" id="scpCommand">scp /path/to/your-rom.gb root@your-instance-hostname:/root/pokemon/roms/</div>
        <button class="button" onclick="copyToClipboard('scpCommand')">Copy SCP Command</button>
        
        <h3>SFTP Instructions:</h3>
        <ol>
            <li>Connect via SFTP: <div class="command" id="sftpConnect">sftp root@your-instance-hostname</div></li>
            <li>Navigate to ROM directory: <div class="command">cd /root/pokemon/roms</div></li>
            <li>Upload your ROM file: <div class="command">put /path/to/your-rom.gb</div></li>
        </ol>
        <button class="button" onclick="copyToClipboard('sftpConnect')">Copy SFTP Command</button>
        
        <h3>Current Server Information:</h3>
        <div id="serverInfo">
            <p>Loading server information...</p>
        </div>
    </div>
    
    <div id="serverStatus" class="tabcontent">
        <h2>Server Status</h2>
        <p>Check the current status of the Pokemon game server:</p>
        <button id="checkStatus" class="button">Refresh Status</button>
        <div id="statusInfo" style="margin-top: 10px;"></div>
    </div>

    <script>
        // Get the current hostname
        const hostname = window.location.hostname;
        const instanceId = hostname.includes('-') ? hostname.split('-')[1].split('.')[0] : 'your-instance-id';
        
        // Update commands with the current hostname
        document.getElementById('scpCommand').textContent = `scp /path/to/your-rom.gb root@${hostname}:/root/pokemon/roms/`;
        document.getElementById('sftpConnect').textContent = `sftp root@${hostname}`;
        
        // Load server info
        fetch('/api/status')
        .then(response => response.json())
        .then(data => {
            let serverInfoHtml = `
                <p><strong>Hostname:</strong> ${hostname}</p>
                <p><strong>Instance ID:</strong> ${instanceId}</p>
                <p><strong>Server Status:</strong> ${data.ready ? 'Ready' : 'Initializing'}</p>
                <p><strong>ROM Status:</strong> ${data.rom_status}</p>`;
                
            if (data.rom_file) {
                serverInfoHtml += `<p><strong>Current ROM:</strong> ${data.rom_file}</p>`;
            }
            
            document.getElementById('serverInfo').innerHTML = serverInfoHtml;
        })
        .catch(error => {
            document.getElementById('serverInfo').innerHTML = `<p class="error">Error fetching server info: ${error.message}</p>`;
        });
        
        // Tab functionality
        function openTab(evt, tabName) {
            var i, tabcontent, tablinks;
            tabcontent = document.getElementsByClassName("tabcontent");
            for (i = 0; i < tabcontent.length; i++) {
                tabcontent[i].style.display = "none";
            }
            tablinks = document.getElementsByClassName("tablinks");
            for (i = 0; i < tablinks.length; i++) {
                tablinks[i].className = tablinks[i].className.replace(" active", "");
            }
            document.getElementById(tabName).style.display = "block";
            evt.currentTarget.className += " active";
        }
        
        // Copy to clipboard function
        function copyToClipboard(elementId) {
            const el = document.getElementById(elementId);
            const text = el.textContent;
            
            navigator.clipboard.writeText(text).then(() => {
                el.style.backgroundColor = '#d4edda';
                setTimeout(() => {
                    el.style.backgroundColor = '#f8f9fa';
                }, 1000);
            }).catch(err => {
                console.error('Failed to copy: ', err);
            });
        }

        // Form submission
        document.getElementById('uploadForm').addEventListener('submit', function(e) {
            e.preventDefault();
            
            const fileInput = document.getElementById('romFile');
            const file = fileInput.files[0];
            
            if (!file) {
                showStatus('Please select a file.', 'error');
                return;
            }
            
            if (!file.name.toLowerCase().endsWith('.gb')) {
                showStatus('Please select a valid Game Boy ROM file (.gb).', 'error');
                return;
            }
            
            const formData = new FormData();
            formData.append('file', file);
            
            showStatus('Uploading ROM file...', '');
            
            fetch('/api/upload_rom', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showStatus('ROM uploaded successfully! The game server should start automatically.', 'success');
                } else {
                    showStatus(`Error: ${data.error || 'Unknown error'}`, 'error');
                }
            })
            .catch(error => {
                showStatus(`Upload failed: ${error.message}`, 'error');
            });
        });
        
        // Status check
        function checkServerStatus() {
            fetch('/api/status')
            .then(response => response.json())
            .then(data => {
                const statusDiv = document.getElementById('statusInfo');
                
                if (data.rom_status === 'detected') {
                    let html = `<div class="status success">
                        <p><strong>ROM File:</strong> ${data.rom_file || 'Unknown'}</p>
                        <p><strong>Status:</strong> ${data.ready ? 'Ready' : 'Initializing...'}</p>
                        <p><strong>Server uptime:</strong> ${data.uptime_formatted}</p>
                    </div>`;
                    statusDiv.innerHTML = html;
                } else {
                    statusDiv.innerHTML = `<div class="status error">
                        <p><strong>Status:</strong> Waiting for ROM upload</p>
                        <p><strong>Server uptime:</strong> ${data.uptime_formatted}</p>
                        <p>Please upload a ROM file to start the emulator.</p>
                    </div>`;
                }
            })
            .catch(error => {
                document.getElementById('statusInfo').innerHTML = `
                    <div class="status error">
                        <p>Error checking status: ${error.message}</p>
                    </div>`;
            });
        }
        
        document.getElementById('checkStatus').addEventListener('click', checkServerStatus);
        
        // Load initial status
        checkServerStatus();
        
        function showStatus(message, type) {
            const statusDiv = document.getElementById('status');
            statusDiv.textContent = message;
            statusDiv.style.display = 'block';
            
            // Reset classes
            statusDiv.className = 'status';
            
            if (type) {
                statusDiv.classList.add(type);
            }
        }
        
        // Make the web upload tab active by default
        document.getElementsByClassName("tablinks")[0].click();
    </script>
</body>
</html>"""


    # Create simple nginx configuration for the upload interface
    
    nginx_config = """server {
    listen 80 default_server;
    server_name _;
    
    root /root/pokemon/web;
    index index.html;
    
    location = / {
        try_files /index.html =404;
    }
    
    location /api/ {
        proxy_pass http://localhost:9876/api/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 300s;
    }
}
"""
    try:
        # Create web directory
        instance.exec("mkdir -p /root/pokemon/web")
        
        # Give nginx permission to access
        instance.exec("chmod -R 755 /root")

        # Write the upload HTML page
        instance.exec(f"cat > /root/pokemon/web/index.html << 'EOFHTML'\n{upload_html}EOFHTML")
        
        # Configure nginx
        instance.exec("rm -f /etc/nginx/sites-enabled/default")
        instance.exec(f"cat > /etc/nginx/sites-available/pokemon << 'EOFNGINX'\n{nginx_config}EOFNGINX")
        instance.exec("ln -sf /etc/nginx/sites-available/pokemon /etc/nginx/sites-enabled/")
        instance.exec("systemctl restart nginx")
        
        print("✅ ROM upload web interface configured successfully")
        return True
    except Exception as e:
        print(f"❌ Error setting up upload helper: {e}")
        return False

def main():
    args = parse_arguments()
    
    # Check for required API keys
    if not os.environ.get("MORPH_API_KEY"):
        print("❌ Error: MORPH_API_KEY environment variable not found")
        print("Please set it in your .env file")
        print("Example: MORPH_API_KEY=your_api_key")
        return
    
    # Create client (will use MORPH_API_KEY from environment)
    client = MorphCloudClient()
    
    print("\n=== 🚀 Starting Pokemon ROM Watch Server setup ===")
    
    # Create or get a base snapshot with reasonable specs
    print("\n=== 🔍 Finding or creating base snapshot ===")
    snapshots = client.snapshots.list(
        digest="pokemon-rom-watch-snapshot",
        metadata={"purpose": "pokemon-rom-watch-server"}
    )
    
    if snapshots:
        base_snapshot = snapshots[0]
        print(f"✅ Using existing base snapshot: {base_snapshot.id}")
    else:
        print("⏳ Creating new base snapshot...")
        base_snapshot = client.snapshots.create(
            vcpus=2,
            memory=4096,
            disk_size=8192,
            digest="pokemon-rom-watch-snapshot",
            metadata={"purpose": "pokemon-rom-watch-server"}
        )
        print(f"✅ Created new base snapshot: {base_snapshot.id}")
    
    # Setup desktop environment if not running headless
    if not args.headless:
        print("\n=== 🔧 Setting up desktop environment (cached) ===")
        desktop_setup_script = """
# Update and install essential packages
DEBIAN_FRONTEND=noninteractive apt-get update -q
DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
    xfce4 xfce4-goodies tigervnc-standalone-server tigervnc-common \
    python3 python3-pip python3-venv python3-dev \
    python3-websockify git net-tools nginx \
    dbus dbus-x11 xfonts-base \
    libsdl2-2.0-0 libsdl2-dev \
    xdotool imagemagick build-essential inotify-tools

# Clone noVNC repository
rm -rf /opt/noVNC || true
git clone https://github.com/novnc/noVNC.git /opt/noVNC

# Clean any existing VNC processes
pkill Xvnc || true
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1 || true

# Create config directories
mkdir -p /root/.config/xfce4 /root/.config/xfce4-session /root/.config/autostart /root/.config/systemd
"""
        
        start_time = time.time()
        desktop_snapshot = base_snapshot.setup(desktop_setup_script)
        end_time = time.time()
        print(f"⏱️ Desktop environment setup time: {end_time - start_time:.2f} seconds")
        
        # Set up VNC and related services
        print("\n=== 🔧 Setting up VNC services (cached) ===")
        services_setup_script = """
# Create VNC service
cat > /etc/systemd/system/vncserver.service << 'EOF'
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

# Create XFCE session startup script
cat > /usr/local/bin/start-xfce-session << 'EOF'
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

chmod +x /usr/local/bin/start-xfce-session

# Create XFCE service
cat > /etc/systemd/system/xfce-session.service << 'EOF'
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

# Create noVNC service
cat > /etc/systemd/system/novnc.service << 'EOF'
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

# Enable services
systemctl daemon-reload
systemctl enable vncserver xfce-session novnc
"""
        
        start_time = time.time()
        services_snapshot = desktop_snapshot.setup(services_setup_script)
        end_time = time.time()
        print(f"⏱️ Services setup time: {end_time - start_time:.2f} seconds")
        setup_snapshot = services_snapshot
    else:
        setup_snapshot = base_snapshot
    
    # Install Pokemon dependencies - Python packages and PyBoy
    print("\n=== 🔧 Setting up Pokemon server dependencies (cached) ===")
    
    dependencies_setup_script = """
# Create project directory
mkdir -p /root/pokemon
chmod 777 /root/pokemon

# Install Nginx
DEBIAN_FRONTEND=noninteractive apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y nginx

# Create and activate virtual environment
cd /root/pokemon
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install flask pillow anthropic requests python-dotenv pyboy flask_cors watchdog mcp starlette uvicorn
"""
    
    start_time = time.time()
    final_snapshot = setup_snapshot.setup(dependencies_setup_script)
    end_time = time.time()
    print(f"⏱️ Dependencies setup time: {end_time - start_time:.2f} seconds")
    
    # Start an instance from the final snapshot
    print("\n=== 🚀 Starting instance from final snapshot ===")
    print(f"Snapshot ID: {final_snapshot.id}")
    instance = client.instances.start(final_snapshot.id)
    
    try:
        print("⏳ Waiting for instance to be ready...")
        instance.wait_until_ready(timeout=300)
        print(f"✅ Instance {instance.id} is ready")
        
        # Create ROM watch directory
        print(f"\n=== 📁 Creating ROM watch directory: {args.watch_dir} ===")
        instance.exec(f"mkdir -p /root/pokemon/{args.watch_dir} && chmod 777 /root/pokemon/{args.watch_dir}")
        
        # Expose HTTP service for both the API and web interface
        print("\n=== 🌐 Exposing HTTP service ===")
        web_url = instance.expose_http_service("web", 80)
        print(f"✅ Web interface exposed at {web_url}")

        print("\n=== 🌐 Exposing MCP service ===")
        mcp_url = instance.expose_http_service("mcp", 8000)
        print(f"✅ MCP service exposed at {mcp_url}")
        
        # If not headless, expose desktop service as well
        if not args.headless:
            print("\n=== 🌐 Exposing desktop service ===")
            instance.expose_http_service("novnc", 6080)
            print(f"✅ Desktop service exposed")
        
        # Start any desktop services if needed
        if not args.headless:
            print("\n=== 🔄 Starting desktop services ===")
            result = instance.exec("systemctl daemon-reload && systemctl restart vncserver xfce-session novnc")
            if result.exit_code == 0:
                print("✅ All desktop services started successfully")
            else:
                print(f"⚠️ Some services may not have started correctly: {result.stderr}")
        
        # Upload project files
        upload_files_via_sftp(instance)
        
        # Upload the server script
        print("\n=== 📤 Uploading ROM watch server script ===")
        with open("rom_watch_server.py", "r") as f:
            server_script = f.read()
            instance.exec(f"cat > /root/pokemon/rom_watch_server.py << 'EOF'\n{server_script}EOF")
            instance.exec("chmod +x /root/pokemon/rom_watch_server.py")
        
        # Create startup script and service
        setup_startup_script(instance, args)
        
        # Setup upload helper interface
        setup_upload_helper(instance, args.watch_dir)
        
        # Upload initial ROM if specified
        if args.rom:
            upload_rom_via_sftp(instance, args.rom, args.watch_dir)
        
        # Start the server service
        print("\n=== 🎮 Starting the Pokemon ROM Watch Server ===")
        instance.exec("systemctl restart nginx && systemctl start pokemon-server")
        setup_rom_watcher(instance, args.watch_dir)

        # Start the MCP server service
        print("\n=== 🎮 Starting the Pokemon MCP Server ===")
        instance.exec("systemctl start pokemon-mcp")
       

        # Print access information
        print("\n=== 🎮 POKEMON ROM WATCH SERVER READY! ===")
        print(f"Instance ID: {instance.id}")
        
        # Web interface URL
        web_hostname = f"web-{instance.id.replace('_', '-')}.http.cloud.morph.so"
        print(f"\nWeb interface accessible at: https://{web_hostname}")
        print("Use this interface to upload ROM files and check server status")
        
        if not args.headless:
            # Desktop URL
            novnc_hostname = f"novnc-{instance.id.replace('_', '-')}.http.cloud.morph.so"
            print(f"\nRemote desktop accessible at: https://{novnc_hostname}/vnc_lite.html")
        
        # Client connection info
        print(f"\nTo connect from your local machine, run:")
        print(f"python connect_to_server.py --host {web_hostname} --port 80")
        
        # Create a final snapshot with the project files included
        print("\n=== 💾 Creating final snapshot ===")
        final_snapshot = instance.snapshot()
        
        # Add metadata
        metadata = {
            "type": "pokemon-rom-watch-server",
            "description": "Pokemon ROM Watch Server",
            "headless": str(args.headless).lower(),
            "watch_dir": args.watch_dir,
            "has_initial_rom": "true" if args.rom else "false"
        }
        if args.rom:
            metadata["initial_rom_file"] = os.path.basename(args.rom)
        
        final_snapshot.set_metadata(metadata)
        print(f"✅ Final snapshot created: {final_snapshot.id}")
        print(f"To start a new instance from this exact state, run:")
        print(f"morphcloud instance start {final_snapshot.id}")
        
        print("\nThe instance will remain running. To stop it when you're done, run:")
        print(f"morphcloud instance stop {instance.id}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("For troubleshooting, try SSH:")
        print(f"morphcloud instance ssh {instance.id}")
        raise

if __name__ == "__main__":
    main()
