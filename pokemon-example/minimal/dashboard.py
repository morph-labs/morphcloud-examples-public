#!/usr/bin/env python3
"""
Pokemon Agent Dashboard - Single File Version

This script provides a web interface for managing Pokemon agents.
Just run this file and open your browser to http://localhost:5000.

Dependencies: flask
"""
import os
import sys
import time
import signal
import subprocess
import threading
import re
from collections import deque
import webbrowser
from flask import Flask, request, jsonify

# The HTML interface as a string constant
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pokemon Agent Dashboard</title>
    <style>
        body, html {
            margin: 0;
            padding: 0;
            height: 100%;
            font-family: Arial, sans-serif;
        }
        .container {
            display: flex;
            height: 100vh;
        }
        .sidebar {
            width: 300px;
            background-color: #f5f5f5;
            padding: 15px;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .controls {
            flex: 0 0 auto;
        }
        .console {
            flex: 1;
            margin-top: 15px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }
        .console-title {
            font-weight: bold;
            margin-bottom: 5px;
        }
        .console-output {
            flex: 1;
            background-color: #222;
            color: #f0f0f0;
            font-family: monospace;
            padding: 10px;
            overflow-y: auto;
            white-space: pre-wrap;
            font-size: 12px;
            border-radius: 4px;
        }
        .main-view {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .game-frame {
            flex: 1;
            border: none;
        }
        label {
            display: block;
            margin-top: 10px;
            font-weight: bold;
        }
        input {
            width: 100%;
            padding: 8px;
            margin-top: 4px;
            box-sizing: border-box;
        }
        button {
            margin-top: 10px;
            padding: 8px;
            width: 100%;
            background-color: #4CAF50;
            color: white;
            border: none;
            cursor: pointer;
            border-radius: 4px;
        }
        button:hover {
            background-color: #45a049;
        }
        button:disabled {
            background-color: #cccccc;
            cursor: not-allowed;
        }
        button.stop {
            background-color: #f44336;
        }
        button.stop:hover {
            background-color: #d32f2f;
        }
        .status {
            margin-top: 10px;
            padding: 8px;
            background-color: #e0e0e0;
            border-radius: 4px;
        }
        .clear-logs {
            margin-top: 5px;
            font-size: 12px;
            padding: 4px;
            background-color: #666;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="sidebar">
            <div class="controls">
                <h2>Pokemon Agent</h2>
                
                <form id="agentForm">
                    <label for="snapshotId">Snapshot ID:</label>
                    <input type="text" id="snapshotId" required>
                    
                    <label for="steps">Steps:</label>
                    <input type="number" id="steps" value="10" min="1">
                    
                    <button type="submit" id="startButton">Start Agent</button>
                    <button type="button" id="stopButton" class="stop" disabled>Stop Agent</button>
                </form>
                
                <div id="statusDisplay" class="status">Status: Idle</div>
                
                <div style="margin-top: 10px; display: flex; gap: 10px; align-items: center;">
                    <label for="autoRefresh" style="margin-top: 0; display: flex; align-items: center; font-weight: normal;">
                        <input type="checkbox" id="autoRefresh" checked style="width: auto; margin-right: 5px;">
                        Auto-refresh
                    </label>
                    <select id="refreshRate" style="width: 100px;">
                        <option value="500">0.5s</option>
                        <option value="1000" selected>1s</option>
                        <option value="2000">2s</option>
                        <option value="5000">5s</option>
                        <option value="10000">10s</option>
                    </select>
                    <button id="manualRefresh" style="width: auto; margin-top: 0;">Refresh</button>
                </div>
            </div>
            
            <div class="console">
                <div class="console-title">Agent Output</div>
                <button class="clear-logs" id="clearLogsButton">Clear Logs</button>
                <div class="console-output" id="consoleOutput"></div>
            </div>
        </div>
        
        <div class="main-view">
            <iframe id="gameFrame" class="game-frame" src="about:blank"></iframe>
        </div>
    </div>

    <script>
        let agentRunning = false;
        let logPollingInterval = null;
        let logPosition = 0;
        let refreshRate = 1000; // Default refresh rate in milliseconds
        let autoRefreshEnabled = true;
        
        // Handle refresh control changes
        document.getElementById('autoRefresh').addEventListener('change', function(e) {
            autoRefreshEnabled = e.target.checked;
            if (autoRefreshEnabled && agentRunning) {
                startLogPolling();
            } else {
                stopLogPolling();
            }
        });
        
        document.getElementById('refreshRate').addEventListener('change', function(e) {
            refreshRate = parseInt(e.target.value);
            if (logPollingInterval) {
                stopLogPolling();
                if (autoRefreshEnabled && agentRunning) {
                    startLogPolling();
                }
            }
        });
        
        document.getElementById('manualRefresh').addEventListener('click', function() {
            fetchLogs();
        });
        
        // Form submission handler
        document.getElementById('agentForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            if (agentRunning) return;
            
            const snapshotId = document.getElementById('snapshotId').value;
            const steps = document.getElementById('steps').value;
            
            // Update UI
            document.getElementById('statusDisplay').textContent = "Status: Starting agent...";
            document.getElementById('startButton').disabled = true;
            document.getElementById('stopButton').disabled = false;
            agentRunning = true;
            
            try {
                // Start the agent
                const response = await fetch('/start', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        snapshotId,
                        steps
                    })
                });
                
                const result = await response.json();
                
                if (result.success) {
                    document.getElementById('statusDisplay').textContent = "Status: Agent running";
                    
                    // Reset the log position counter
                    logPosition = 0;
                    
                    // Start polling for logs
                    startLogPolling();
                } else {
                    document.getElementById('statusDisplay').textContent = "Status: Error - " + result.error;
                    resetAgentState();
                }
            } catch (error) {
                document.getElementById('statusDisplay').textContent = "Status: Connection error";
                console.error(error);
                resetAgentState();
            }
        });
        
        // Stop button handler
        document.getElementById('stopButton').addEventListener('click', async function() {
            if (!agentRunning) return;
            
            document.getElementById('statusDisplay').textContent = "Status: Stopping agent...";
            
            try {
                const response = await fetch('/stop', {
                    method: 'POST'
                });
                
                const result = await response.json();
                
                if (result.success) {
                    document.getElementById('statusDisplay').textContent = "Status: Agent stopped";
                } else {
                    document.getElementById('statusDisplay').textContent = "Status: Failed to stop agent";
                }
            } catch (error) {
                document.getElementById('statusDisplay').textContent = "Status: Connection error";
                console.error(error);
            }
            
            resetAgentState();
        });
        
        // Clear logs button handler
        document.getElementById('clearLogsButton').addEventListener('click', function() {
            document.getElementById('consoleOutput').textContent = '';
        });
        
        // Helper function to reset UI state
        function resetAgentState() {
            agentRunning = false;
            document.getElementById('startButton').disabled = false;
            document.getElementById('stopButton').disabled = true;
            
            // Stop polling for logs
            stopLogPolling();
        }
        
        // Start polling for new log entries
        function startLogPolling() {
            if (logPollingInterval) {
                clearInterval(logPollingInterval);
            }
            
            if (autoRefreshEnabled) {
                logPollingInterval = setInterval(fetchLogs, refreshRate);
            }
        }
        
        // Stop polling for logs
        function stopLogPolling() {
            if (logPollingInterval) {
                clearInterval(logPollingInterval);
                logPollingInterval = null;
            }
        }
        
        // Fetch new log entries from the server
        async function fetchLogs() {
            try {
                const response = await fetch(`/logs?position=${logPosition}`);
                const data = await response.json();
                
                if (data.logs) {
                    appendLogs(data.logs);
                    logPosition = data.nextPosition;
                }
                
                // Check if the agent is still running
                if (data.agentRunning === false) {
                    document.getElementById('statusDisplay').textContent = "Status: Agent finished";
                    resetAgentState();
                }
                
                // Check for VNC URL
                if (data.vncUrl && data.vncUrl !== 'null' && data.vncUrl !== '') {
                    const gameFrame = document.getElementById('gameFrame');
                    // Only update the iframe if it's not already showing this URL
                    if (gameFrame.src !== data.vncUrl) {
                        console.log("Setting game frame URL to: " + data.vncUrl);
                        gameFrame.src = data.vncUrl;
                    }
                }
            } catch (error) {
                console.error("Error fetching logs:", error);
            }
        }
        
        // Append new log entries to the console output
        function appendLogs(logs) {
            if (!logs || logs.length === 0) return;
            
            const consoleOutput = document.getElementById('consoleOutput');
            
            // Add each log line
            logs.forEach(line => {
                // Create a new div for each line
                const logLine = document.createElement('div');
                logLine.textContent = line;
                
                // Add color based on log content
                if (line.includes('[ERROR]') || line.includes('Error')) {
                    logLine.style.color = '#ff5252';
                } else if (line.includes('[WARNING]') || line.includes('Warning')) {
                    logLine.style.color = '#ffb142';
                } else if (line.includes('[Claude]')) {
                    logLine.style.color = '#4fc3f7';
                } else if (line.includes('[Tool Use]') || line.includes('[Claude Action]')) {
                    logLine.style.color = '#66bb6a';
                }
                
                consoleOutput.appendChild(logLine);
            });
            
            // Auto-scroll to bottom
            consoleOutput.scrollTop = consoleOutput.scrollHeight;
        }
    </script>
</body>
</html>
"""

# Initialize Flask app
app = Flask(__name__)

# Global variables for agent state
agent_process = None
agent_logs = deque(maxlen=1000)  # Store up to 1000 log lines
log_lock = threading.Lock()
agent_running = False
vnc_url = None

def extract_vnc_url(line):
    """Extract VNC URL from log line"""
    match = re.search(r"Pokemon remote desktop available at: (https?://[^\s]+)", line)
    if match:
        return match.group(1)
    return None

def log_reader(process):
    """Read logs from the process stdout/stderr in real-time"""
    global agent_logs, agent_running, vnc_url
    
    for line in iter(process.stdout.readline, b''):
        try:
            decoded_line = line.decode('utf-8').rstrip()
            
            # Check if this line contains the VNC URL
            extracted_url = extract_vnc_url(decoded_line)
            if extracted_url:
                print(f"Found VNC URL: {extracted_url}")
                vnc_url = extracted_url
            
            # Add timestamp to the log line
            timestamp = time.strftime("%H:%M:%S", time.localtime())
            log_line = f"[{timestamp}] {decoded_line}"
            
            # Add to log buffer with thread safety
            with log_lock:
                agent_logs.append(log_line)
                
            print(log_line)
        except Exception as e:
            print(f"Error processing log line: {e}")
    
    # Process has ended
    with log_lock:
        agent_logs.append(f"[{time.strftime('%H:%M:%S', time.localtime())}] Agent process terminated")
        agent_running = False

@app.route('/')
def index():
    """Serve the main page"""
    return HTML_TEMPLATE

@app.route('/logs')
def get_logs():
    """Get new log entries since the given position"""
    global agent_logs, vnc_url
    
    position = int(request.args.get('position', 0))
    
    with log_lock:
        # Convert deque to list for easier slicing
        all_logs = list(agent_logs)
        
        # Get logs from the requested position
        if position < len(all_logs):
            new_logs = all_logs[position:]
            next_position = len(all_logs)
        else:
            new_logs = []
            next_position = position
    
    return jsonify({
        "logs": new_logs,
        "nextPosition": next_position,
        "agentRunning": agent_running,
        "vncUrl": vnc_url
    })

@app.route('/start', methods=['POST'])
def start_agent():
    """Start the Pokemon agent"""
    global agent_process, agent_running, agent_logs, vnc_url
    
    # Check if agent is already running
    if agent_running:
        return jsonify({"success": False, "error": "Agent is already running"})
    
    try:
        data = request.json
        snapshot_id = data.get('snapshotId')
        steps = data.get('steps', 10)
        
        # Clear previous logs
        with log_lock:
            agent_logs.clear()
            vnc_url = None
        
        # Check if the agent script exists
        if not os.path.exists("minimal_agent.py"):
            return jsonify({
                "success": False, 
                "error": "minimal_agent.py not found. Please ensure the agent file is in the current directory."
            })
        
        # Build command
        cmd = [
            sys.executable, 
            "minimal_agent.py",
            "--snapshot-id", snapshot_id,
            "--steps", str(steps),
            "--no-browser"  # Suppress browser auto-open since we're using the dashboard
        ]
        
        # Start the process with pipes for stdout/stderr
        print(f"Starting agent with command: {' '.join(cmd)}")
        
        agent_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=False
        )
        
        agent_running = True
        
        # Start a thread to read the logs
        log_thread = threading.Thread(target=log_reader, args=(agent_process,))
        log_thread.daemon = True
        log_thread.start()
        
        # Add initial log entry
        with log_lock:
            timestamp = time.strftime("%H:%M:%S", time.localtime())
            agent_logs.append(f"[{timestamp}] Started agent with snapshot {snapshot_id} for {steps} steps")
        
        return jsonify({
            "success": True,
            "message": "Agent started"
        })
        
    except Exception as e:
        print(f"Error starting agent: {e}")
        agent_running = False
        return jsonify({"success": False, "error": str(e)})

@app.route('/stop', methods=['POST'])
def stop_agent():
    """Stop the running agent"""
    global agent_process, agent_running
    
    if not agent_running or agent_process is None:
        return jsonify({"success": False, "error": "No agent is running"})
    
    try:
        # Add log entry
        with log_lock:
            timestamp = time.strftime("%H:%M:%S", time.localtime())
            agent_logs.append(f"[{timestamp}] Stopping agent...")
        
        # Send termination signal to the process
        if os.name == 'nt':  # Windows
            agent_process.terminate()
        else:  # Unix/Linux/Mac
            try:
                os.killpg(os.getpgid(agent_process.pid), signal.SIGTERM)
            except:
                agent_process.terminate()
        
        # Wait for process to terminate (with timeout)
        try:
            agent_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # Force kill if it doesn't terminate
            if os.name == 'nt':  # Windows
                agent_process.kill()
            else:  # Unix/Linux/Mac
                try:
                    os.killpg(os.getpgid(agent_process.pid), signal.SIGKILL)
                except:
                    agent_process.kill()
        
        agent_running = False
        
        return jsonify({
            "success": True,
            "message": "Agent stopped"
        })
        
    except Exception as e:
        print(f"Error stopping agent: {e}")
        return jsonify({"success": False, "error": str(e)})

def main():
    """Main function"""
    print("Pokemon Agent Dashboard")
    print("======================")
    print("1. Make sure your minimal_agent.py file is in the current directory")
    print("2. Opening browser to http://127.0.0.1:5001/")
    print("3. Press Ctrl+C to stop the server")
    
    # Open browser automatically
    webbrowser.open("http://127.0.0.1:5001/")
    
    # Run the Flask app
    app.run(host='0.0.0.0', port=5001, threaded=True)

if __name__ == '__main__':
    main()

