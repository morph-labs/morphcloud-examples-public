#!/usr/bin/env python3
# /// script
# dependencies = [
#   "morphcloud",
#   "requests",
#   "pillow",
#   "rich",
#   "anthropic",
#   "flask",
# ]
# ///


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

# Try to import MorphCloudClient for snapshot operations
try:
    from morphcloud.api import MorphCloudClient
except ImportError:
    print("Warning: morphcloud package not found. Some snapshot features may not work.")
    MorphCloudClient = None

# The HTML interface with enhanced snapshot viewer tab
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
            width: 320px;
            background-color: #f5f5f5;
            padding: 15px;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .controls {
            flex: 0 0 auto;
        }
        .console, .snapshots {
            flex: 1;
            margin-top: 15px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }
        .console-title, .snapshots-title {
            font-weight: bold;
            margin-bottom: 5px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .console-output, .snapshots-list {
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
        .tabs {
            display: flex;
            margin-bottom: 10px;
        }
        .tab {
            padding: 8px 16px;
            cursor: pointer;
            background-color: #e0e0e0;
            border: 1px solid #ccc;
            border-bottom: none;
            border-radius: 4px 4px 0 0;
            margin-right: 5px;
        }
        .tab.active {
            background-color: #f0f0f0;
            font-weight: bold;
        }
        .tab-content {
            display: none;
            flex: 1;
            overflow: hidden;
            flex-direction: column;
        }
        .tab-content.active {
            display: flex;
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
        .clear-logs, .refresh-snapshots {
            margin-top: 5px;
            font-size: 12px;
            padding: 4px;
            background-color: #666;
            width: auto;
        }
        /* Snapshot tree styling */
        .snapshot-node {
            margin-bottom: 8px;
            padding: 5px;
            background-color: #333;
            border-radius: 3px;
            cursor: pointer;
        }
        .snapshot-node:hover {
            background-color: #444;
        }
        .snapshot-node.current {
            background-color: #1e5922;
        }
        .snapshot-node .title {
            font-weight: bold;
            color: #4CAF50;
        }
        .snapshot-node .id {
            color: #aaa;
            font-size: 10px;
        }
        .snapshot-node .metadata {
            color: #888;
            font-size: 11px;
            margin-top: 2px;
        }
        .snapshot-actions {
            margin-top: 10px;
            display: flex;
            gap: 5px;
        }
        .snapshot-action {
            font-size: 12px;
            padding: 4px 8px;
            margin: 0;
            flex: 1;
        }
        .info-panel {
            margin-top: 10px;
            padding: 8px;
            background-color: #444;
            border-radius: 4px;
            font-size: 12px;
            color: #ddd;
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
                    
                    <div style="display: flex; gap: 10px; margin-top: 10px;">
                        <div style="flex: 1;">
                            <button type="submit" id="startButton">Start Agent</button>
                        </div>
                        <div style="flex: 1;">
                            <button type="button" id="stopButton" class="stop" disabled>Stop Agent</button>
                        </div>
                    </div>
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
            
            <div class="tabs">
                <div class="tab active" data-tab="console">Console</div>
                <div class="tab" data-tab="snapshots">Snapshots</div>
            </div>
            
            <div class="tab-content active" id="console-tab">
                <div class="console">
                    <div class="console-title">
                        <span>Agent Output</span>
                        <button class="clear-logs" id="clearLogsButton">Clear</button>
                    </div>
                    <div class="console-output" id="consoleOutput"></div>
                </div>
            </div>
            
            <div class="tab-content" id="snapshots-tab">
                <div class="snapshots">
                    <div class="snapshots-title">
                        <span>Snapshots</span>
                        <button class="refresh-snapshots" id="refreshSnapshotsButton">Refresh</button>
                    </div>
                    <div class="snapshots-list" id="snapshotsList"></div>
                    
                    <div class="snapshot-actions">
                        <button class="snapshot-action" id="loadSnapshotButton" disabled>Load Selected</button>
                        <button class="snapshot-action" id="viewSnapshotButton" disabled>View Details</button>
                    </div>
                    
                    <div class="info-panel" id="snapshotInfoPanel">
                        Select a snapshot to view details
                    </div>
                </div>
            </div>
        </div>
        
        <div class="main-view">
            <div style="display: flex; justify-content: flex-end; padding: 5px; background-color: #333;">
                <button id="reloadVncButton" style="margin: 0; padding: 5px 10px; width: auto; font-size: 12px; background-color: #666;">
                    🔄 Reload VNC
                </button>
            </div>
            <iframe id="gameFrame" class="game-frame" src="about:blank"></iframe>
        </div>
    </div>

    <script>
        let agentRunning = false;
        let logPollingInterval = null;
        let logPosition = 0;
        let refreshRate = 1000; // Default refresh rate in milliseconds
        let autoRefreshEnabled = true;
        let currentSnapshotId = null;
        let selectedSnapshotId = null;
        let snapshots = []; // Store snapshot data
        let currentVncUrl = null;
        
        // Tab switching
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', function() {
                // Remove active class from all tabs and contents
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                
                // Add active class to clicked tab and corresponding content
                this.classList.add('active');
                document.getElementById(this.dataset.tab + '-tab').classList.add('active');
            });
        });
        
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
            
            // Store as the current snapshot ID
            currentSnapshotId = snapshotId;
            
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
                    
                    // Also fetch snapshots after a short delay to let them start being created
                    setTimeout(fetchSnapshots, 5000);
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
                    // Fetch snapshots one more time to ensure we have the final ones
                    fetchSnapshots();
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
        
        // Refresh snapshots button handler
        document.getElementById('refreshSnapshotsButton').addEventListener('click', function() {
            fetchSnapshots();
        });
        
        // Load snapshot button handler
        document.getElementById('loadSnapshotButton').addEventListener('click', async function() {
            if (!selectedSnapshotId) return;
            
            // Set the selected snapshot as the current one in the form
            document.getElementById('snapshotId').value = selectedSnapshotId;
            
            // Highlight the selection as current
            updateSnapshotDisplay();
            
            // Display a message
            document.getElementById('snapshotInfoPanel').textContent = 
                `Snapshot ${selectedSnapshotId} loaded into form. Click 'Start Agent' to begin from this snapshot.`;
        });
        
        // View snapshot details button handler
        document.getElementById('viewSnapshotButton').addEventListener('click', function() {
            if (!selectedSnapshotId) return;
            
            // Find the selected snapshot
            const snapshot = snapshots.find(s => s.id === selectedSnapshotId);
            if (!snapshot) return;
            
            // Display detailed information
            const infoPanel = document.getElementById('snapshotInfoPanel');
            let details = `Snapshot: ${snapshot.name}\n`;
            details += `ID: ${snapshot.id}\n`;
            details += `Created: ${new Date(snapshot.created * 1000).toLocaleString()}\n\n`;
            
            details += `Lineage:\n`;
            details += `- Parent: ${snapshot.metadata?.parent_snapshot || 'None'}\n`;
            details += `- Previous: ${snapshot.metadata?.prev_snapshot || 'None'}\n`;
            details += `- Step: ${snapshot.metadata?.step_number || 'Unknown'}\n`;
            details += `- Dashboard Run: ${snapshot.metadata?.dashboard_run_id || 'None'}\n`;
            
            infoPanel.textContent = details;
        });
        
        // Helper function to reset UI state
        function resetAgentState() {
            agentRunning = false;
            document.getElementById('startButton').disabled = false;
            document.getElementById('stopButton').disabled = true;
            
            // Stop polling for logs
            stopLogPolling();
        }
        
        // Snapshot selection handler
        function handleSnapshotClick(snapshotId) {
            selectedSnapshotId = snapshotId;
            updateSnapshotDisplay();
            
            // Enable action buttons
            document.getElementById('loadSnapshotButton').disabled = false;
            document.getElementById('viewSnapshotButton').disabled = false;
            
            // Show basic info
            const snapshot = snapshots.find(s => s.id === snapshotId);
            if (snapshot) {
                const infoPanel = document.getElementById('snapshotInfoPanel');
                infoPanel.textContent = `Selected: ${snapshot.name} (${snapshot.id})\nStep: ${snapshot.metadata?.step_number || 'Unknown'}\nRun: ${snapshot.metadata?.dashboard_run_id ? snapshot.metadata.dashboard_run_id.substring(0, 8) + '...' : 'None'}\n\nClick 'View Details' for more information.`;
            }
        }
        
        // Update snapshot display highlighting
        function updateSnapshotDisplay() {
            // Remove highlighting from all nodes
            document.querySelectorAll('.snapshot-node').forEach(node => {
                node.classList.remove('current');
            });
            
            // Add current class to current snapshot
            if (currentSnapshotId) {
                const currentNode = document.querySelector(`.snapshot-node[data-id="${currentSnapshotId}"]`);
                if (currentNode) {
                    currentNode.classList.add('current');
                }
            }
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
                if (data.agentRunning === false && agentRunning) {
                    document.getElementById('statusDisplay').textContent = "Status: Agent finished";
                    resetAgentState();
                    
                    // Fetch snapshots one more time to get final state
                    fetchSnapshots();
                }
                
                // Check for VNC URL
                if (data.vncUrl && data.vncUrl !== 'null' && data.vncUrl !== '') {
                    const gameFrame = document.getElementById('gameFrame');
                    // Store the URL for reload button usage
                    currentVncUrl = data.vncUrl;
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
        
        // Fetch snapshots from the server
        async function fetchSnapshots() {
            try {
                const response = await fetch('/snapshots');
                const data = await response.json();
                
                if (data.snapshots) {
                    snapshots = data.snapshots;
                    renderSnapshots(data.snapshots);
                }
            } catch (error) {
                console.error("Error fetching snapshots:", error);
            }
        }
        
        // Render snapshots in the UI
        function renderSnapshots(snapshotsList) {
            const snapshotsContainer = document.getElementById('snapshotsList');
            snapshotsContainer.innerHTML = '';
            
            if (snapshotsList.length === 0) {
                snapshotsContainer.textContent = 'No snapshots available for this session';
                return;
            }
            
            // Organize snapshots by step
            const snapshotsByStep = {};
            
            // First, create the parent snapshot entry
            snapshotsList.forEach(snapshot => {
                const step = snapshot.metadata?.step_number ? parseInt(snapshot.metadata.step_number) : null;
                
                if (!snapshotsByStep[step]) {
                    snapshotsByStep[step] = [];
                }
                
                snapshotsByStep[step].push(snapshot);
            });
            
            // Sort steps numerically
            const sortedSteps = Object.keys(snapshotsByStep)
                .filter(step => step !== 'null')
                .map(step => parseInt(step))
                .sort((a, b) => a - b);
            
            // Add parent snapshots (those without step numbers) at the top
            if (snapshotsByStep['null']) {
                sortedSteps.unshift('null');
            }
            
            // Create nodes for each snapshot, grouped by step
            sortedSteps.forEach(step => {
                const group = snapshotsByStep[step];
                
                group.forEach(snapshot => {
                    const node = document.createElement('div');
                    node.className = 'snapshot-node';
                    node.dataset.id = snapshot.id;
                    
                    // Mark current snapshot
                    if (snapshot.id === currentSnapshotId) {
                        node.classList.add('current');
                    }
                    
                    // Create snapshot content
                    let nodeHtml = '';
                    
                    // Title (step number or parent)
                    if (step === 'null') {
                        nodeHtml += `<div class="title">Parent</div>`;
                    } else {
                        nodeHtml += `<div class="title">Step ${step}</div>`;
                    }
                    
                    // ID
                    nodeHtml += `<div class="id">${snapshot.id}</div>`;
                    
                    // Metadata
                    const metadata = snapshot.metadata || {};
                    let metadataText = [];
                    
                    if (snapshot.name) {
                        metadataText.push(`Name: ${snapshot.name}`);
                    }
                    
                    if (metadata.timestamp) {
                        const date = new Date(parseInt(metadata.timestamp) * 1000);
                        metadataText.push(`Time: ${date.toLocaleTimeString()}`);
                    }
                    
                    if (metadata.dashboard_run_id) {
                        metadataText.push(`Run: ${metadata.dashboard_run_id.substring(0, 8)}...`);
                    }
                    
                    nodeHtml += `<div class="metadata">${metadataText.join(' | ')}</div>`;
                    
                    node.innerHTML = nodeHtml;
                    
                    // Add click handler
                    node.addEventListener('click', () => handleSnapshotClick(snapshot.id));
                    
                    snapshotsContainer.appendChild(node);
                });
            });
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
                } else if (line.includes('Snapshot created')) {
                    logLine.style.color = '#ba68c8';
                }
                
                consoleOutput.appendChild(logLine);
            });
            
            // Auto-scroll to bottom
            consoleOutput.scrollTop = consoleOutput.scrollHeight;
        }
        
        // Fetch snapshots periodically when agent is running
        if (autoRefreshEnabled) {
            setInterval(() => {
                if (agentRunning) {
                    fetchSnapshots();
                }
            }, 5000);  // Check for new snapshots every 5 seconds
        }
        
        // Reload VNC button handler
        document.getElementById('reloadVncButton').addEventListener('click', function() {
            const gameFrame = document.getElementById('gameFrame');
            
            // Store the current URL
            if (gameFrame.src && gameFrame.src !== 'about:blank') {
                currentVncUrl = gameFrame.src;
            }
            
            // If we have a VNC URL, reload it
            if (currentVncUrl) {
                console.log("Reloading VNC iframe with URL: " + currentVncUrl);
                // First clear the frame
                gameFrame.src = 'about:blank';
                
                // Then after a brief delay, set it back to the VNC URL
                setTimeout(() => {
                    gameFrame.src = currentVncUrl;
                }, 500);
                
                // Log to console
                const timestamp = new Date().toLocaleTimeString();
                const consoleOutput = document.getElementById('consoleOutput');
                const logLine = document.createElement('div');
                logLine.textContent = `[${timestamp}] VNC display manually reloaded`;
                logLine.style.color = '#ffb142';
                consoleOutput.appendChild(logLine);
                consoleOutput.scrollTop = consoleOutput.scrollHeight;
            } else {
                console.log("No VNC URL available to reload");
            }
        });
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
parent_snapshot_id = None
morph_client = None

def extract_vnc_url(line):
    """Extract VNC URL from log line"""
    match = re.search(r"(https://novnc-[^\s]*\.http\.cloud\.morph\.so[^\s]*)", line)
    if match:
        return match.group(1)
    return None

def extract_snapshot_id(line):
    """Extract snapshot ID from log line"""
    match = re.search(r"Snapshot created with ID: ([a-zA-Z0-9_]+)", line)
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

def initialize_morph_client():
    """Initialize MorphCloud client if possible"""
    global morph_client
    
    if MorphCloudClient is not None:
        try:
            morph_client = MorphCloudClient()
            print("MorphCloud client initialized successfully")
            return True
        except Exception as e:
            print(f"Error initializing MorphCloud client: {e}")
    
    return False

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

@app.route('/snapshots')
def get_snapshots():
    """Get snapshots for the current session"""
    global morph_client, parent_snapshot_id
    
    if morph_client is None:
        return jsonify({"snapshots": [], "error": "MorphCloud client not available"})
    
    if parent_snapshot_id is None:
        return jsonify({"snapshots": [], "message": "No parent snapshot set for this session"})
    
    try:
        # Get snapshots that have our dashboard run ID in metadata
        # Extract the original snapshot ID if we're using it for tracking
        snapshots = morph_client.snapshots.list(metadata={"dashboard_run_id": parent_snapshot_id})
        
        
        # Convert to dictionaries for JSON serialization
        snapshot_dicts = []
        for snapshot in snapshots:
            snapshot_dict = {
                "id": snapshot.id,
                "name": getattr(snapshot, 'name', None),
                "created": getattr(snapshot, 'created', 0),
                "metadata": getattr(snapshot, 'metadata', {})
            }
            snapshot_dicts.append(snapshot_dict)
        
        return jsonify({"snapshots": snapshot_dicts})
    except Exception as e:
        print(f"Error fetching snapshots: {e}")
        return jsonify({"snapshots": [], "error": str(e)})

@app.route('/start', methods=['POST'])
def start_agent():
    """Start the Pokemon agent"""
    global agent_process, agent_running, agent_logs, vnc_url, parent_snapshot_id
    
    # Check if agent is already running
    if agent_running:
        return jsonify({"success": False, "error": "Agent is already running"})
    
    try:
        data = request.json
        snapshot_id = data.get('snapshotId')
        steps = data.get('steps', 10)
        
        # Always create a new run ID for each agent start
        # This ensures previous snapshots don't appear in the current run's view
        run_timestamp = int(time.time())
        parent_snapshot_id = f"{snapshot_id}_{run_timestamp}"
        print(f"Setting new run ID for this session: {parent_snapshot_id}")
        
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
        
        # Extract the original snapshot ID if we're using a combined run ID
        actual_snapshot_id = snapshot_id
        actual_parent_id = parent_snapshot_id
        
        # If parent_snapshot_id contains a timestamp, extract the actual snapshot ID
        if '_' in parent_snapshot_id:
            parts = parent_snapshot_id.split('_')
            if len(parts) >= 2:  # Ensure it has the expected format
                actual_parent_id = parts[0]  # First part is the actual snapshot ID
                
        # Build command
        cmd = [
            sys.executable, 
            "minimal_agent.py",
            "--snapshot-id", actual_snapshot_id,
            "--steps", str(steps),
            "--no-browser",  # Suppress browser auto-open since we're using the dashboard
            "--parent-snapshot-id", actual_parent_id,  # The actual snapshot for lineage
            "--dashboard-run-id", parent_snapshot_id,  # The combined run ID for filtering
            "--snapshot-prefix", f"dash_{int(time.time())}"
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
            agent_logs.append(f"[{timestamp}] Using parent snapshot {parent_snapshot_id} for lineage tracking")
            agent_logs.append(f"[{timestamp}] All snapshots will be tagged with dashboard_run_id={parent_snapshot_id}")
        
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
    global agent_process, agent_running
    
    # Wrap everything in try/except to prevent server crashes
    try:
        if not agent_running or agent_process is None:
            return jsonify({"success": False, "error": "No agent is running"})
        
        # Log that we're attempting to stop
        print(f"Attempting to stop agent process (PID: {agent_process.pid})")
        
        # Create a local reference to the process
        process_to_stop = agent_process
        
        # Clear global references first to avoid deadlocks
        agent_running = False
        agent_process = None
        
        # Then terminate the process
        try:
            process_to_stop.terminate()
            process_to_stop.wait(timeout=2)
        except Exception as inner_e:
            print(f"Error during graceful termination: {inner_e}")
            try:
                process_to_stop.kill()
            except:
                pass  # Already dead or can't be killed
        
        # Add log entry
        with log_lock:
            timestamp = time.strftime("%H:%M:%S", time.localtime())
            agent_logs.append(f"[{timestamp}] Agent stopped")
        
        return jsonify({
            "success": True,
            "message": "Agent stopped"
        })
        
    except Exception as e:
        # Critical error handling - log it but don't crash
        print(f"CRITICAL ERROR in stop_agent: {e}")
        import traceback
        traceback.print_exc()
        
        # Reset state to be safe
        agent_running = False
        agent_process = None
        
        # Always return a response
        return jsonify({"success": False, "error": f"Server error: {str(e)}"})


def main():
    """Main function"""
    print("Pokemon Agent Dashboard")
    print("======================")
    print("1. Make sure your minimal_agent.py file is in the current directory")
    print("2. Opening browser to http://127.0.0.1:5001/")
    print("3. Press Ctrl+C to stop the server")
    
    # Initialize MorphCloud client
    initialize_morph_client()
    
    # Open browser automatically
    webbrowser.open("http://127.0.0.1:5001/")
    
    # Run the Flask app
    app.run(host='0.0.0.0', port=5001, threaded=True)

if __name__ == '__main__':
    main()
