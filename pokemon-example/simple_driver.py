#!/usr/bin/env python3
import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
import re
import threading
import time
import queue
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global variables
active_process = None
process_lock = threading.Lock()
novnc_url = None  # Store the NoVNC URL
eva_log_position = 0  # Track position in EVA log file

# HTML template for the UI
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pokemon EVA Agent</title>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        
        body {
            font-family: 'Courier New', monospace;
            background-color: #000;
            color: #fff;
            height: 100vh;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }

        .container {
            display: flex;
            flex-direction: column;
            height: 100vh;
            overflow: hidden;
        }

        .header {
            text-align: center;
            padding: 1rem;
            border-bottom: 1px solid #333;
            height: 4rem;
        }

        .main-content {
            display: grid;
            grid-template-columns: 30% 70%;
            flex: 1;
            overflow: hidden;
        }

        .chat-container {
            border-right: 1px solid #333;
            display: flex;
            flex-direction: column;
            height: 100%;
            overflow: hidden;
        }

        .chat-header {
            padding: 1rem;
            border-bottom: 1px solid #333;
        }

        .messages-container {
            flex: 1;
            overflow-y: auto;
            padding: 0.5rem;
            height: 100%;
        }

        .message {
            padding: 0.5rem;
            margin-bottom: 0.5rem;
            border-left: 2px solid;
            background-color: rgba(30, 30, 30, 0.7);
            word-break: break-word;
        }

        .timestamp {
            font-size: 0.75rem;
            opacity: 0.7;
            margin-bottom: 0.25rem;
        }

        .claude-text { border-color: #ff3e3e; }
        .tool-call { border-color: #ffa500; }
        .tool-result { border-color: #00ff00; }

        .game-container {
            display: flex;
            flex-direction: column;
            height: 100%;
            padding: 1rem;
            overflow: hidden;
        }

        .game-header {
            padding-bottom: 0.5rem;
            border-bottom: 1px solid #333;
            margin-bottom: 1rem;
        }

        .game-display {
            flex: 1;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            background-color: rgba(20, 20, 20, 0.7);
            border: 1px solid #333;
            position: relative;
            overflow: hidden;
        }

        iframe {
            position: absolute;
            width: 1200px; 
            height: 800px;
            border: none;
            top: -100px;
            left: -300px;
        }

        .controls-container {
            padding: 1rem;
            border-top: 1px solid #333;
        }

        button {
            padding: 0.75rem;
            margin-bottom: 0.5rem;
            background-color: transparent;
            border: 1px solid #ff3e3e;
            color: #ff3e3e;
            font-family: 'Courier New', monospace;
            cursor: pointer;
            transition: background-color 0.3s;
            width: 100%;
        }

        button:hover {
            background-color: rgba(255, 62, 62, 0.2);
        }

        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        button.primary {
            border-color: #00ff00;
            color: #00ff00;
        }

        button.primary:hover {
            background-color: rgba(0, 255, 0, 0.2);
        }

        button.stop {
            border-color: #ff0000;
            color: #ff0000;
        }

        .form-group {
            margin-bottom: 1rem;
        }

        label {
            display: block;
            margin-bottom: 0.5rem;
            color: #aaa;
        }

        input, select {
            width: 100%;
            padding: 0.5rem;
            background-color: #1a1a1a;
            border: 1px solid #333;
            color: #ddd;
            font-family: 'Courier New', monospace;
        }

        .snapshots-container {
            border-top: 1px solid #333;
            padding: 1rem;
            overflow-x: auto;
            white-space: nowrap;
            height: 100px;
        }

        .snapshot-item {
            display: inline-block;
            padding: 0.5rem;
            margin-right: 0.5rem;
            background-color: rgba(30, 30, 30, 0.7);
            border: 1px solid #333;
            cursor: pointer;
            transition: background-color 0.3s;
        }

        .snapshot-item:hover {
            background-color: rgba(255, 62, 62, 0.2);
            border-color: #ff3e3e;
        }

        .status {
            padding: 0.5rem;
            margin-top: 0.5rem;
            color: #aaa;
        }

        .status.running {
            color: #00ff00;
        }

        .status.stopped {
            color: #ff0000;
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <h1>CLAUDE PLAYS POKEMON</h1>
        </div>

        <!-- Main content area -->
        <div class="main-content">
            <!-- Left sidebar / Chat container -->
            <div class="chat-container">
                <div class="chat-header">
                    <h2>CONVERSATION</h2>
                    <button id="refresh-logs-btn">REFRESH LOGS</button>
                </div>
                <div id="messages" class="messages-container">
                    <!-- Messages will be populated here -->
                </div>
            </div>

            <!-- Game container -->
            <div class="game-container">
                <div class="game-header">
                    <h2>GAME VIEW</h2>
                </div>
                <div class="game-display">
                    <iframe id="game-iframe" src="about:blank"></iframe>
                </div>
                
                <!-- Controls container -->
                <div class="controls-container">
                    <div class="form-group">
                        <label for="snapshot-id">SNAPSHOT ID:</label>
                        <input type="text" id="snapshot-id" placeholder="e.g., snapshot_yigk8b5d">
                    </div>
                    
                    <div class="form-group">
                        <label for="steps">NUMBER OF STEPS:</label>
                        <input type="number" id="steps" value="10" min="1">
                    </div>
                    
                    <div class="control-buttons">
                        <button id="play-btn" class="primary">PLAY</button>
                        <button id="stop-btn" class="stop" disabled>STOP</button>
                    </div>

                    <div id="status-display" class="status">Status: Ready</div>
                </div>
            </div>
        </div>

        <!-- Snapshots container -->
        <div class="snapshots-container">
            <h3>SNAPSHOTS:</h3>
            <div id="snapshots-list">
                <!-- Snapshots will be populated here -->
            </div>
        </div>
    </div>

    <script>
        // DOM elements
        const messagesContainer = document.getElementById('messages');
        const gameIframe = document.getElementById('game-iframe');
        const playBtn = document.getElementById('play-btn');
        const stopBtn = document.getElementById('stop-btn');
        const refreshLogsBtn = document.getElementById('refresh-logs-btn');
        const snapshotsList = document.getElementById('snapshots-list');
        const statusDisplay = document.getElementById('status-display');
        
        let logUpdateInterval;
        let allMessages = [];
        let allSnapshots = [];
        let autoScroll = true;
        
        // Format timestamp for display
        const formatTime = (timestamp) => {
            if (!timestamp) return new Date().toLocaleTimeString();
            return new Date(timestamp).toLocaleTimeString([], { 
                hour: '2-digit', 
                minute: '2-digit', 
                second: '2-digit' 
            });
        };

        // Add a message to the container
        function addMessageToContainer(message, index) {
            const messageEl = document.createElement('div');
            messageEl.className = `message ${message.type}`;
            
            // Add timestamp
            const timestamp = document.createElement('div');
            timestamp.className = 'timestamp';
            timestamp.textContent = formatTime(message.timestamp);
            messageEl.appendChild(timestamp);
            
            // Create message content
            const contentEl = document.createElement('div');
            contentEl.className = 'message-content';
            
            // Set content based on message type
            if (message.type === 'claude-text') {
                contentEl.innerHTML = `> ${message.content}`;
            } 
            else if (message.type === 'tool-call') {
                contentEl.innerHTML = `
                    <div><strong>USING TOOL:</strong> ${message.tool}</div>
                    <div><pre>${JSON.stringify(message.input, null, 2)}</pre></div>
                `;
            } 
            else if (message.type === 'tool-result') {
                contentEl.innerHTML = `<div>${message.content || ''}</div>`;
                
                if (message.screenshot) {
                    contentEl.innerHTML += `<img src="data:image/png;base64,${message.screenshot}" style="max-width: 100%;" />`;
                }
            }
            
            messageEl.appendChild(contentEl);
            messagesContainer.appendChild(messageEl);
            
            // Auto-scroll
            if (autoScroll) {
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
            }
        }

        // Add a snapshot to the list
        function addSnapshotToList(snapshot) {
            const item = document.createElement('div');
            item.className = 'snapshot-item';
            item.textContent = `Step ${snapshot.step}: ${snapshot.id.substring(9, 17)}`;
            
            item.addEventListener('click', () => {
                document.getElementById('snapshot-id').value = snapshot.id;
            });
            
            snapshotsList.appendChild(item);
        }

        // Update game iframe
        function updateGameIframe(url) {
            if (!url) return;
            
            console.log(`Updating game iframe to URL: ${url}`);
            const gameIframe = document.getElementById('game-iframe');
            
            if (gameIframe.src !== url) {
                gameIframe.src = url;
                console.log("Iframe source updated");
                
                // Add event listeners to monitor iframe loading
                gameIframe.onload = () => console.log("Iframe loaded successfully");
                gameIframe.onerror = (e) => console.error("Iframe error:", e);
            }
        }

        // Fetch logs from the server
        async function fetchLogs() {
            try {
                const response = await fetch('/api/logs');
                const data = await response.json();
                
                if (data.success) {
                    // Update status display
                    statusDisplay.textContent = `Status: ${data.status === 'running' ? 'Running' : 'Stopped'}`;
                    statusDisplay.className = `status ${data.status}`;
                    
                    // Process new messages
                    if (data.messages && data.messages.length > 0) {
                        const currentCount = allMessages.length;
                        const newMessages = data.messages.filter(msg => {
                            // Check if message already exists
                            return !allMessages.some(existingMsg => 
                                existingMsg.type === msg.type && 
                                existingMsg.timestamp === msg.timestamp && 
                                existingMsg.content === msg.content
                            );
                        });
                        
                        if (newMessages.length > 0) {
                            console.log(`Adding ${newMessages.length} new messages`);
                            allMessages = [...allMessages, ...newMessages];
                            
                            newMessages.forEach((message, index) => {
                                addMessageToContainer(message, currentCount + index);
                            });
                        }
                    }
                    
                    // Update iframe if needed
                    if (data.webUrl && gameIframe.src !== data.webUrl) {
                        updateGameIframe(data.webUrl);
                    }
                    
                    // Update snapshots if available
                    if (data.snapshots && data.snapshots.length > 0) {
                        const currentSnapshotIds = allSnapshots.map(s => s.id);
                        const newSnapshots = data.snapshots.filter(s => !currentSnapshotIds.includes(s.id));
                        
                        if (newSnapshots.length > 0) {
                            console.log(`Adding ${newSnapshots.length} new snapshots`);
                            allSnapshots = [...allSnapshots, ...newSnapshots];
                            
                            // Clear snapshots list and rebuild
                            snapshotsList.innerHTML = '';
                            allSnapshots.forEach(snapshot => {
                                addSnapshotToList(snapshot);
                            });
                        }
                    }
                    
                    // Update UI if process is stopped
                    if (data.status === 'stopped' && stopBtn.disabled === false) {
                        resetPlayState();
                        clearInterval(logUpdateInterval);
                    }
                }
            } catch (error) {
                console.error('Error fetching logs:', error);
            }
        }

        // Reset play button state
        function resetPlayState() {
            playBtn.disabled = false;
            stopBtn.disabled = true;
            statusDisplay.textContent = 'Status: Ready';
            statusDisplay.className = 'status';
        }

        // Play button click handler
        playBtn.addEventListener('click', async () => {
            const snapshotId = document.getElementById('snapshot-id').value;
            const steps = document.getElementById('steps').value;
            
            if (!snapshotId) {
                alert('Please enter a snapshot ID');
                return;
            }
            
            try {
                // Update UI
                playBtn.disabled = true;
                stopBtn.disabled = false;
                statusDisplay.textContent = 'Status: Starting...';
                statusDisplay.className = 'status running';
                
                // Start the script
                const response = await fetch('/api/start', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        snapshotId,
                        steps
                    })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    // Start fetching logs
                    logUpdateInterval = setInterval(fetchLogs, 2000);
                    statusDisplay.textContent = 'Status: Running';
                } else {
                    alert(`Failed to start: ${data.error}`);
                    resetPlayState();
                }
            } catch (error) {
                console.error('Error starting script:', error);
                alert(`Error: ${error.message}`);
                resetPlayState();
            }
        });

        // Stop button click handler
        stopBtn.addEventListener('click', async () => {
            try {
                statusDisplay.textContent = 'Status: Stopping...';
                
                const response = await fetch('/api/stop', {
                    method: 'POST'
                });
                
                const data = await response.json();
                
                if (data.success) {
                    resetPlayState();
                    
                    // Stop fetching logs
                    clearInterval(logUpdateInterval);
                } else {
                    alert(`Failed to stop: ${data.error}`);
                    statusDisplay.textContent = 'Status: Error stopping';
                }
            } catch (error) {
                console.error('Error stopping script:', error);
                alert(`Error: ${error.message}`);
                statusDisplay.textContent = 'Status: Error stopping';
            }
        });

        // Refresh logs button click handler
        refreshLogsBtn.addEventListener('click', () => {
            fetchLogs();
        });

        // Scroll event handler
        messagesContainer.addEventListener('scroll', () => {
            const isScrolledToBottom = 
                messagesContainer.scrollHeight - messagesContainer.clientHeight <= 
                messagesContainer.scrollTop + 50;
            
            autoScroll = isScrolledToBottom;
        });

        if (data.success) {
            // Clear existing messages and snapshots
            allMessages = [];
            allSnapshots = [];
            messagesContainer.innerHTML = '';
            snapshotsList.innerHTML = '';
            
            // Start fetching logs
            logUpdateInterval = setInterval(fetchLogs, 2000);
            statusDisplay.textContent = 'Status: Running';
        }

    </script>
</body>
</html>
"""

# Get the latest EVA log file
def get_latest_eva_log_file():
    """Find the most recent EVA log file."""
    log_dir = os.path.join(os.getcwd(), "logs")
    if not os.path.exists(log_dir):
        logger.warning(f"EVA logs directory not found at {log_dir}")
        return None
        
    log_files = [f for f in os.listdir(log_dir) if f.startswith("eva_") and f.endswith(".jsonl")]
    if not log_files:
        logger.warning("No EVA log files found")
        return None
        
    # Sort by creation time, newest first
    log_files.sort(key=lambda f: os.path.getctime(os.path.join(log_dir, f)), reverse=True)
    latest_file = os.path.join(log_dir, log_files[0])
    logger.info(f"Found latest EVA log file: {latest_file}")
    return latest_file

# Read logs from the EVA log file
def read_eva_logs(last_position=0):
    """Read new logs from the EVA log file since the last position.
    
    Args:
        last_position: The last file position we read to
        
    Returns:
        tuple: (new_logs, new_position)
    """
    log_file_path = get_latest_eva_log_file()
    if not log_file_path:
        return [], last_position
        
    logs = []
    new_position = last_position
    
    try:
        with open(log_file_path, 'r') as f:
            # Skip to the last position we read
            f.seek(last_position)
            
            # Read new content
            for line in f:
                logs.append(line.strip())
            
            # Get current position
            new_position = f.tell()
            
        logger.info(f"Read {len(logs)} new log lines from EVA log file")
    except Exception as e:
        logger.error(f"Error reading EVA log file: {e}")
        
    return logs, new_position

# Extract NoVNC URL from logs
def extract_novnc_url_from_logs(logs):
    """Extract NoVNC URL from logs."""
    global novnc_url
    
    for line in logs:
        try:
            entry = json.loads(line)
            
            # Look for explicit novnc_url event
            if entry.get("event_type") == "novnc_url":
                novnc_url = entry.get("url")
                logger.info(f"Found NoVNC URL: {novnc_url}")
                return
            
            # Look for HTTP service details
            if "extra" in entry:
                extra = entry.get("extra", {})
                
                # Check for service URLs
                if extra.get("service_port") == 6080 and extra.get("service_url"):
                    novnc_url = f"{extra['service_url']}/vnc_lite.html"
                    logger.info(f"Constructed NoVNC URL: {novnc_url}")
                    return
                    
                # Look for MCP URL
                if "mcp_url" in extra and extra.get("mcp_url"):
                    base_url = extra.get("mcp_url").replace("/sse", "")
                    logger.info(f"Found MCP base URL: {base_url}")
                    
                # Look for HTTP service logs
                if "service_url" in extra and "service_port" in extra:
                    logger.info(f"Found service: {extra.get('service_name', 'unknown')} on port {extra.get('service_port')} at {extra.get('service_url')}")
                    
                    # If it's a NoVNC service (typically on port 6080)
                    if extra.get("service_port") == 6080:
                        novnc_url = f"{extra['service_url']}/vnc_lite.html"
                        logger.info(f"Found NoVNC URL: {novnc_url}")
                        return
            
            # Check message text
            message = entry.get("message", "")
            if ("novnc" in message.lower() or "vnc" in message.lower()) and "url" in message.lower():
                # Try to extract URL from message
                urls = re.findall(r'https?://[^\s"\']+', message)
                if urls:
                    url = urls[0]
                    if not url.endswith('/vnc_lite.html'):
                        if url.endswith('/'):
                            url += 'vnc_lite.html'
                        else:
                            url += '/vnc_lite.html'
                    novnc_url = url
                    logger.info(f"Extracted NoVNC URL from message: {novnc_url}")
                    return
            
            # Check if this is an HTTP service message
            if ("http service" in message.lower() or "service exposed" in message.lower()) and "extra" in entry:
                extra = entry.get("extra", {})
                if "service_port" in extra and extra.get("service_port") == 6080 and "service_url" in extra:
                    novnc_url = f"{extra['service_url']}/vnc_lite.html"
                    logger.info(f"Found NoVNC URL from HTTP service: {novnc_url}")
                    return
                    
        except json.JSONDecodeError:
            continue
        except Exception as e:
            logger.error(f"Error extracting NoVNC URL: {e}")

# Parse JSONL logs into structured messages
def parse_jsonl_logs(log_entries):
    """Parse JSONL log entries into structured messages for display."""
    messages = []
    snapshots = []
    
    # Try to extract NoVNC URL first
    extract_novnc_url_from_logs(log_entries)
    
    for line in log_entries:
        try:
            # Parse JSON log entry
            entry = json.loads(line)
            
            # Extract common fields
            timestamp = entry.get("timestamp", "")
            message = entry.get("message", "")
            level = entry.get("level", "")
            event_type = entry.get("event_type", "")
            
            # Process based on event type
            if event_type == "claude_text":
                messages.append({
                    "type": "claude-text",
                    "content": entry.get("text_content", "No content"),
                    "timestamp": timestamp
                })
            elif event_type == "claude_tool_use":
                messages.append({
                    "type": "tool-call",
                    "tool": entry.get("tool_name", "unknown-tool"),
                    "input": entry.get("tool_input_data", {}),
                    "timestamp": timestamp
                })
            elif event_type == "tool_result":
                # Include game state in tool result display if available
                game_state = entry.get("game_state", "")
                content = f"Tool executed successfully"
                if game_state:
                    content += f"\n\nGame State:\n{game_state}"
                
                messages.append({
                    "type": "tool-result",
                    "content": content,
                    "timestamp": timestamp
                })
            
            # Process snapshot creation - check both message and snapshot_id field
            if level == "SUCCESS" and "Created snapshot" in message:
                snapshot_id = entry.get("snapshot_id", "")
                if snapshot_id:
                    # Try to find step count from nearby log entries or messages
                    step_count = 0  # Default
                    # You could search recent messages to estimate step count here
                    
                    snapshots.append({
                        "id": snapshot_id,
                        "step": step_count,
                        "timestamp": timestamp
                    })
            
            # Process snapshot created event type (as in your example snippets)
            if event_type == "snapshot_created":
                snapshots.append({
                    "id": entry.get("snapshot_id", "unknown"),
                    "step": entry.get("step_count", 0),
                    "timestamp": timestamp
                })
                
        except json.JSONDecodeError:
            # Skip invalid JSON lines
            continue
        except Exception as e:
            logger.error(f"Error parsing log entry: {e}")
    
    logger.info(f"Parsed {len(messages)} messages and {len(snapshots)} snapshots")
    return messages, snapshots


# API handler for the web server
class APIHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        """Handle GET requests"""
        if self.path == '/':
            # Serve the embedded HTML content
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode())
            return
        
        elif self.path == '/api/logs':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()

            # Get status
            with process_lock:
                status = 'running' if active_process and active_process.poll() is None else 'stopped'
            
            # Only read logs if a process is running
            messages = []
            snapshots = []
            
            if status == 'running':
                # Get logs from EVA log file
                global eva_log_position
                logs, eva_log_position = read_eva_logs(eva_log_position)
                
                # Parse logs into structured messages
                messages, snapshots = parse_jsonl_logs(logs)
            
            response = {
                'success': True,
                'status': status,
                'messages': messages,
                'snapshots': snapshots,
                'webUrl': novnc_url if novnc_url else None
            }
            
            self.wfile.write(json.dumps(response).encode())

        else:
            # Serve static files
            return SimpleHTTPRequestHandler.do_GET(self)
    
    def do_POST(self):
        """Handle POST requests"""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        
        try:
            if self.path == '/api/start':
                # Parse the request data
                params = json.loads(post_data)
                
                # Start the Pokemon agent
                result = start_pokemon_agent(
                    snapshot_id=params.get('snapshotId'),
                    steps=params.get('steps', 10)
                )
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
                
            elif self.path == '/api/stop':
                result = stop_pokemon_agent()
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
                
            else:
                self.send_response(404)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': 'Endpoint not found'}).encode())
                
        except Exception as e:
            logger.error(f"Error handling POST request: {e}")
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())

# Start the Pokemon agent
def start_pokemon_agent(snapshot_id, steps=10):
    """Start the Pokemon agent with the given parameters."""
    global active_process, novnc_url, eva_log_position
    
    # Reset NoVNC URL and log position
    novnc_url = None
    eva_log_position = 0
    
    # Check if there's already a process running
    with process_lock:
        if active_process and active_process.poll() is None:
            return {'success': False, 'error': 'An agent is already running'}
    
    try:
        # Build command
        cmd = [
            sys.executable,  # Use the current Python interpreter
            'pokemon_eva_agent.py',  # The EVA agent script
            '--snapshot-id', snapshot_id,
            '--steps', str(steps)
        ]
        
        # Log the command
        logger.info(f"Starting Pokemon agent: {' '.join(cmd)}")
        
        # Check if script exists
        agent_script_path = Path(os.path.abspath('pokemon_eva_agent.py'))
        if not agent_script_path.exists():
            logger.error(f"Error: script not found at {agent_script_path}")
            return {'success': False, 'error': f'Agent script not found at {agent_script_path}'}
        
        # Start the process
        with process_lock:
            logger.info(f"Launching process")
            active_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1  # Line buffered
            )
            
            # Log the process ID
            logger.info(f"Process started with PID: {active_process.pid}")
        
        # Check if process is still running after a brief delay
        time.sleep(1)
        with process_lock:
            if active_process and active_process.poll() is not None:
                logger.error(f"Process exited immediately with code: {active_process.poll()}")
                return {'success': False, 'error': f'Process exited immediately with code: {active_process.poll()}'}
        
        # Start reading EVA logs immediately
        logs, eva_log_position = read_eva_logs(0)
        if logs:
            logger.info(f"Found {len(logs)} initial log entries")
            parse_jsonl_logs(logs)
        
        return {'success': True}
    except Exception as e:
        logger.error(f"Error starting Pokemon agent: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return {'success': False, 'error': str(e)}

# Stop the Pokemon agent
def stop_pokemon_agent():
    """Stop the currently running Pokemon agent."""
    global active_process
    
    with process_lock:
        if active_process is None or active_process.poll() is not None:
            return {'success': False, 'error': 'No agent is currently running'}
        
        try:
            # Send termination signal to the process
            active_process.terminate()
            
            # Wait for a short time for it to exit gracefully
            for _ in range(5):  # Wait up to 5 seconds
                if active_process.poll() is not None:
                    break
                time.sleep(1)
            
            # Force kill if still running
            if active_process.poll() is None:
                active_process.kill()
                active_process.wait()
            
            logger.info("Pokemon agent stopped")
            
            return {'success': True}
        except Exception as e:
            logger.error(f"Error stopping Pokemon agent: {e}")
            return {'success': False, 'error': str(e)}

# Main function
def main():
    parser = argparse.ArgumentParser(description="Pokemon EVA Agent Driver")
    parser.add_argument('--port', type=int, default=8000, help='Port for the web server')
    args = parser.parse_args()
    
    # Ensure the script directory is the working directory
    script_dir = Path(__file__).parent.absolute()
    os.chdir(script_dir)
    
    # Make sure the EVA log directory exists
    os.makedirs(os.path.join(script_dir, "logs"), exist_ok=True)
    
    # Make sure pokemon_eva_agent.py exists
    agent_script_path = Path(script_dir) / 'pokemon_eva_agent.py'
    if not agent_script_path.exists():
        logger.error(f"Error: pokemon_eva_agent.py not found in {script_dir}")
        logger.error("Please make sure the Pokemon EVA agent script exists in the same directory.")
        sys.exit(1)
    
    # Set up HTTP server
    server_address = ('', args.port)
    httpd = HTTPServer(server_address, APIHandler)
    
    logger.info(f"Starting web server at http://localhost:{args.port}")
    logger.info("Press Ctrl+C to stop the server")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server stopped")
        # Ensure any running processes are terminated
        stop_pokemon_agent()

if __name__ == "__main__":
    main()
