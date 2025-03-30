#!/usr/bin/env python3
import argparse
import json
import logging
import os
import requests
import sys
import time
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# We assume your back-end is on localhost:8000 by default:
API_BASE_URL = "http://127.0.0.1:8000"
POLL_INTERVAL = 1.0  # seconds

# We will store NoVNC URL if we discover it from your back-end. This is optional.
novnc_url = None

# ------------------------------------------------------------------------------
# HTML Template
# ------------------------------------------------------------------------------
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Claude Plays Pokemon (Trajectory Edition)</title>
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
            height: calc(100vh - 160px);
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
            min-height: 500px;
        }

        iframe {
            position: absolute;
            width: 100%;
            height: 100%;
            transform: scale(0.9);
            transform-origin: center;
            border: none;
        }

        .controls-container {
            padding: 0.5rem;
            border-top: 1px solid #333;
            max-height: 200px;
            overflow-y: auto;
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

        button.secondary {
            border-color: #00ccff;
            color: #00ccff;
        }

        button.secondary:hover {
            background-color: rgba(0, 204, 255, 0.2);
        }

        button.stop {
            border-color: #ff0000;
            color: #ff0000;
        }

        .form-group {
            margin-bottom: 0.5rem;
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
            height: 80px;
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

        .status.paused {
            color: #ffff00;
        }

        .status.stopped {
            color: #ff0000;
        }
        
        .trajectory-container {
            margin-top: 1rem;
            border-top: 1px solid #333;
            padding-top: 1rem;
            max-height: 200px;
        }
        
        .trajectory-step {
            display: flex;
            justify-content: space-between;
            padding: 0.5rem;
            margin-bottom: 0.5rem;
            background-color: rgba(30, 30, 30, 0.7);
            border: 1px solid #333;
            cursor: pointer;
            transition: background-color 0.3s;
        }
        
        .trajectory-step:hover {
            background-color: rgba(0, 204, 255, 0.2);
            border-color: #00ccff;
        }
        
        .trajectory-step.selected {
            background-color: rgba(0, 204, 255, 0.4);
            border-color: #00ccff;
        }
        
        .step-info {
            font-size: 0.8rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <h1>CLAUDE PLAYS POKEMON: TRAJECTORY EDITION</h1>
        </div>

        <!-- Main content area -->
        <div class="main-content">
            <!-- Left sidebar / Chat container -->
            <div class="chat-container">
                <div class="chat-header">
                    <h2>CONVERSATION</h2>
                    <button id="refresh-btn" class="secondary">REFRESH DATA</button>
                </div>
                <div id="messages" class="messages-container">
                    <!-- Messages will be populated here -->
                </div>
                
                <!-- Trajectory steps -->
                <div class="trajectory-container">
                    <h3>TRAJECTORY STEPS</h3>
                    <div id="trajectory-steps" class="messages-container" style="height: 200px; overflow-y: auto;">
                        <!-- Trajectory steps will be populated here -->
                    </div>
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
                        <input type="number" id="steps" value="100" min="1">
                    </div>
                    
                    <div class="form-group">
                        <label for="task-select">CHOOSE A TASK:</label>
                        <select id="task-select">
                            <!-- We'll populate from /tasks below -->
                        </select>
                    </div>
                    
                    <div class="control-buttons">
                        <button id="play-btn" class="primary">PLAY</button>
                        <button id="pause-btn" class="secondary" disabled>PAUSE</button>
                        <button id="resume-btn" class="secondary" disabled>RESUME</button>
                        <button id="rollback-btn" class="secondary" disabled>ROLLBACK TO SELECTED</button>
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
        const trajectoryStepsContainer = document.getElementById('trajectory-steps');
        const gameIframe = document.getElementById('game-iframe');
        const playBtn = document.getElementById('play-btn');
        const pauseBtn = document.getElementById('pause-btn');
        const resumeBtn = document.getElementById('resume-btn');
        const rollbackBtn = document.getElementById('rollback-btn');
        const stopBtn = document.getElementById('stop-btn');
        const refreshBtn = document.getElementById('refresh-btn');
        const snapshotsList = document.getElementById('snapshots-list');
        const statusDisplay = document.getElementById('status-display');
        
        // We'll dynamically set these from Python (in do_GET)
        window.API_BASE_URL = "%API_BASE_URL%";  // replaced dynamically
        window.POLL_INTERVAL = 1.0;
        window.NOVNC_URL = null; // replaced dynamically if needed

        let pollingInterval;
        let selectedStepIndex = null;
        let autoScroll = true;
        let currentTrajectory = { steps: [], snapshots: [] };

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
        function addMessageToContainer(message) {
            const messageEl = document.createElement('div');
            // message.type might be 'claude-text', 'tool-call', 'tool-result'
            messageEl.className = 'message ' + (message.type || '');

            // Add timestamp
            const timestampEl = document.createElement('div');
            timestampEl.className = 'timestamp';
            timestampEl.textContent = formatTime(message.timestamp);
            messageEl.appendChild(timestampEl);

            // Create message content
            const contentEl = document.createElement('div');
            contentEl.className = 'message-content';

            // Set content based on message type
            if (message.type === 'claude-text') {
                contentEl.textContent = message.content;
            } else if (message.type === 'tool-call') {
                contentEl.innerHTML = `
                  <div><strong>USING TOOL:</strong> ${message.tool.name}</div>
                  <div><pre>${JSON.stringify(message.tool.input, null, 2)}</pre></div>
                `;
            } else if (message.type === 'tool-result') {
                contentEl.innerHTML = `<div>${message.content || ''}</div>`;
            } else {
                // fallback
                contentEl.textContent = message.content || '';
            }

            messageEl.appendChild(contentEl);
            messagesContainer.appendChild(messageEl);

            // Auto-scroll
            if (autoScroll) {
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
            }
        }

        // Add a trajectory step
        function addTrajectoryStepToContainer(step, index) {
            const stepEl = document.createElement('div');
            stepEl.className = 'trajectory-step';
            stepEl.dataset.index = index;
            
            if (selectedStepIndex === index) {
                stepEl.classList.add('selected');
            }

            const actionText = step.action || 'Initial State';
            const locationText = step.location ? `at ${step.location}` : '';

            // Add snapshot ID if available
            const snapshotText = step.snapshot ? `[Snapshot: ${step.snapshot.substring(0, 8)}]` : '';
            
            stepEl.innerHTML = `
                <div class="step-info">
                    <strong>Step ${index}:</strong> ${actionText} ${locationText} ${snapshotText}
                </div>
                <div class="step-timestamp">${formatTime(step.timestamp)}</div>
            `;

            // On click, select for rollback
            stepEl.addEventListener('click', () => {
                document.querySelectorAll('.trajectory-step').forEach(el => {
                    el.classList.remove('selected');
                });
                stepEl.classList.add('selected');
                selectedStepIndex = index;
                rollbackBtn.disabled = false;
            });

            trajectoryStepsContainer.appendChild(stepEl);
        }

        // Add a snapshot
        function addSnapshotToList(snapshot) {
            const item = document.createElement('div');
            item.className = 'snapshot-item';
            // Include location if available 
            const locationInfo = snapshot.location ? ` (${snapshot.location})` : '';
            item.textContent = `Step ${snapshot.step}: ${snapshot.id.substring(0, 8)}${locationInfo}`;

            item.addEventListener('click', () => {
                document.getElementById('snapshot-id').value = snapshot.id;
            });

            snapshotsList.appendChild(item);
        }

        // Update the NoVNC iframe
        function updateGameIframe(url) {
            if (!url) return;
            const gameIframe = document.getElementById('game-iframe');
            if (gameIframe.src !== url) {
                console.log("Setting game iframe src to:", url);
                gameIframe.src = url;
            }
            // Adjust scale based on container size
            updateIframeScale();
        }
        
        // Dynamically adjust iframe scale based on container size
        function updateIframeScale() {
            const gameDisplay = document.querySelector('.game-display');
            const gameIframe = document.getElementById('game-iframe');
            if (!gameDisplay || !gameIframe) return;
            
            // Calculate optimal scale based on container dimensions
            const containerWidth = gameDisplay.clientWidth;
            const containerHeight = gameDisplay.clientHeight;
            
            // Calculate scale factor (adjust as needed for your specific game resolution)
            // For Game Boy, a scale between 1.2-2.0 usually works well
            const optimalScale = Math.min(
                containerWidth / 160 * 0.2,  // Game Boy resolution is 160x144
                containerHeight / 144 * 0.2
            );
            
            // Apply the calculated scale, but keep it between 1.0 and 2.0
            const verticalOffset = -containerHeight * 0;

            const scale = Math.max(1.0, Math.min(2.0, optimalScale));
            gameIframe.style.transform = `scale(${scale}) translateY(${verticalOffset}px)`;
            console.log(`Adjusted iframe scale to: ${scale}`);
        }

        // Update UI based on status
        function updateUIForStatus(status) {
            statusDisplay.textContent = `Status: ${status}`;
            statusDisplay.className = 'status ' + status;

            if (status === 'running') {
                playBtn.disabled = true;
                pauseBtn.disabled = false;
                resumeBtn.disabled = true;
                stopBtn.disabled = false;
            } else if (status === 'paused') {
                playBtn.disabled = true;
                pauseBtn.disabled = true;
                resumeBtn.disabled = false;
                stopBtn.disabled = false;
            } else if (status === 'stopped' || status === 'not_initialized') {
                playBtn.disabled = false;
                pauseBtn.disabled = true;
                resumeBtn.disabled = true;
                stopBtn.disabled = true;
                rollbackBtn.disabled = true;
            }
        }

        // Convert trajectory data to messages
        function processTrajectoryData(trajectory) {
            if (!trajectory || !trajectory.steps) return;
            currentTrajectory = trajectory;

            // Clear steps container
            trajectoryStepsContainer.innerHTML = '';
            trajectory.steps.forEach((step, idx) => addTrajectoryStepToContainer(step, idx));

            // Clear snapshots container
            snapshotsList.innerHTML = '';
            if (trajectory.snapshots && trajectory.snapshots.length > 0) {
                trajectory.snapshots.forEach(snap => addSnapshotToList(snap));
            }

            // Build messages array from steps
            const messages = [];
            trajectory.steps.forEach(step => {
                // Claude's text
                if (step.claude_text) {
                    messages.push({
                        type: 'claude-text',
                        content: step.claude_text,
                        timestamp: step.timestamp
                    });
                }
                // If there's a tool call
                if (step.tool_name && step.tool_input) {
                    messages.push({
                        type: 'tool-call',
                        tool: { name: step.tool_name, input: step.tool_input },
                        timestamp: step.timestamp
                    });
                    // Then a tool-result message
                    const resultMsg = `Action executed: ${step.action || step.tool_name}`;
                    messages.push({
                        type: 'tool-result',
                        content: resultMsg,
                        timestamp: step.timestamp
                    });
                }
            });
            
            // Sort messages by timestamp
            messages.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
            
            // Clear messages container
            messagesContainer.innerHTML = '';
            // Add them in
            messages.forEach(m => addMessageToContainer(m));
        }

        // Fetch status + trajectory from the API
        async function fetchData() {
            try {
                // status
                const statusRes = await fetch(`${window.API_BASE_URL}/status`);
                const statusData = await statusRes.json();
                updateUIForStatus(statusData.status);

                // trajectory
                const trajRes = await fetch(`${window.API_BASE_URL}/trajectory`);
                const trajData = await trajRes.json();
                processTrajectoryData(trajData);
                
                // fetch novnc url if we don't have it yet
                if (!window.NOVNC_URL) {
                    const novncRes = await fetch(`${window.API_BASE_URL}/novnc_url`);
                    const novncData = await novncRes.json();
                    if (novncData.url) {
                        window.NOVNC_URL = novncData.url;
                        console.log("NoVNC URL set during polling:", window.NOVNC_URL);
                    }
                }

                // set up NoVNC if available
                if (window.NOVNC_URL) {
                    updateGameIframe(window.NOVNC_URL);
                }
            } catch (error) {
                console.error("Error fetching data:", error);
            }
        }

        // Load tasks into the dropdown
        async function loadTasks() {
            try {
                const resp = await fetch(`${window.API_BASE_URL}/tasks`);
                const tasks = await resp.json();
                const select = document.getElementById('task-select');
                select.innerHTML = ''; // clear out old
                tasks.forEach(t => {
                    const opt = document.createElement('option');
                    opt.value = t.id;
                    opt.textContent = t.instruction;
                    select.appendChild(opt);
                });
            } catch (err) {
                console.error("Failed to load tasks:", err);
            }
        }

        // Listen for clicks
        playBtn.addEventListener('click', async () => {
            const snapshotId = document.getElementById('snapshot-id').value;
            const steps = document.getElementById('steps').value;
            const taskId = document.getElementById('task-select').value;

            if (!snapshotId) {
                alert("Please enter a snapshot ID first!");
                return;
            }

            try {
                statusDisplay.textContent = 'Status: Starting...';
                statusDisplay.className = 'status running';

                const res = await fetch(`${window.API_BASE_URL}/start`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        snapshot_id: snapshotId,
                        steps: parseInt(steps),
                        task_id: taskId
                    })
                });
                const data = await res.json();

                if (data.success) {
                    pollingInterval = setInterval(fetchData, window.POLL_INTERVAL * 1000);
                    statusDisplay.textContent = 'Status: Running';
                    pauseBtn.disabled = false;
                    stopBtn.disabled = false;
                } else {
                    alert(`Failed to start: ${data.error}`);
                    updateUIForStatus('stopped');
                }
            } catch (error) {
                console.error("Error starting agent:", error);
                alert("Error: " + error.message);
                updateUIForStatus('stopped');
            }
        });

        pauseBtn.addEventListener('click', async () => {
            try {
                statusDisplay.textContent = 'Status: Pausing...';
                const r = await fetch(`${window.API_BASE_URL}/pause`, { method: 'POST' });
                const data = await r.json();
                if (data.success) {
                    statusDisplay.textContent = 'Status: Paused';
                    statusDisplay.className = 'status paused';
                    pauseBtn.disabled = true;
                    resumeBtn.disabled = false;
                } else {
                    alert(`Failed to pause: ${data.error}`);
                }
            } catch (err) {
                console.error("Pause error:", err);
                alert("Pause error: " + err.message);
            }
        });

        resumeBtn.addEventListener('click', async () => {
            try {
                statusDisplay.textContent = 'Status: Resuming...';
                const r = await fetch(`${window.API_BASE_URL}/resume`, { method: 'POST' });
                const data = await r.json();
                if (data.success) {
                    statusDisplay.textContent = 'Status: Running';
                    statusDisplay.className = 'status running';
                    resumeBtn.disabled = true;
                    pauseBtn.disabled = false;
                } else {
                    alert(`Failed to resume: ${data.error}`);
                }
            } catch (err) {
                console.error("Resume error:", err);
                alert("Resume error: " + err.message);
            }
        });

        rollbackBtn.addEventListener('click', async () => {
            if (selectedStepIndex === null) {
                alert("Please select a step to roll back to!");
                return;
            }
            try {
                statusDisplay.textContent = 'Status: Rolling back...';
                const r = await fetch(`${window.API_BASE_URL}/rollback`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ step_index: selectedStepIndex })
                });
                const data = await r.json();
                if (data.success) {
                    statusDisplay.textContent = 'Status: Rolled back';
                    rollbackBtn.disabled = true;
                    // Reload data after a short delay
                    setTimeout(fetchData, 2000);
                } else {
                    alert(`Failed to roll back: ${data.error}`);
                }
            } catch (err) {
                console.error("Rollback error:", err);
                alert("Rollback error: " + err.message);
            }
        });

        stopBtn.addEventListener('click', async () => {
            try {
                statusDisplay.textContent = 'Status: Stopping...';
                const r = await fetch(`${window.API_BASE_URL}/stop`, { method: 'POST' });
                const data = await r.json();
                if (data.success) {
                    clearInterval(pollingInterval);
                    updateUIForStatus('stopped');
                    statusDisplay.textContent = 'Status: Stopped';
                } else {
                    alert(`Failed to stop: ${data.error}`);
                }
            } catch (err) {
                console.error("Stop error:", err);
                alert("Stop error: " + err.message);
            }
        });

        refreshBtn.addEventListener('click', () => {
            fetchData();
        });

        // Autoscroll logic
        messagesContainer.addEventListener('scroll', () => {
            const isScrolledToBottom =
                messagesContainer.scrollHeight - messagesContainer.clientHeight <=
                messagesContainer.scrollTop + 50;
            autoScroll = isScrolledToBottom;
        });

        // Handle window resize to adjust iframe scale
        window.addEventListener('resize', updateIframeScale);
        
        // On page load, do initial tasks load + fetchData
        loadTasks();
        fetchData();
        // Initial scale adjustment
        updateIframeScale();
    </script>
</body>
</html>"""

# ------------------------------------------------------------------------------
# Handler
# ------------------------------------------------------------------------------
class APIHandler(SimpleHTTPRequestHandler):
    """Serve our UI by returning the embedded HTML in do_GET('/')."""

    def do_GET(self):
        if self.path == '/':
            # Serve the embedded HTML content
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()

            # Replace placeholders with actual values
            base_domain = "127.0.0.1"  # or "localhost"
            html = HTML_TEMPLATE.replace('%API_BASE_URL%', f'http://{base_domain}:{self.api_port}')

            # Add the JavaScript to fetch the novnc_url
            script_to_add = """
            <script>
                // Fetch the NoVNC URL from the API when the page loads
                async function fetchNoVNCUrl() {
                    try {
                        const response = await fetch(`${window.API_BASE_URL}/novnc_url`);
                        const data = await response.json();
                        if (data.url) {
                            window.NOVNC_URL = data.url;
                            console.log("NoVNC URL set:", window.NOVNC_URL);
                            updateGameIframe(window.NOVNC_URL);
                        }
                    } catch (error) {
                        console.error("Error fetching NoVNC URL:", error);
                    }
                }
                
                // Add to onload handlers
                window.addEventListener('load', fetchNoVNCUrl);
            </script>
            """
            
            # Insert the script before the closing body tag
            html = html.replace('</body>', f'{script_to_add}\n</body>')
            
            self.wfile.write(html.encode())
            return
        
        # For all other paths, fall back to normal static file serving
        return super().do_GET()

    def log_message(self, format, *args):
        # Overridden to reduce console noise
        if self.path != '/':
            super().log_message(format, *args)

# ------------------------------------------------------------------------------
# Driver
# ------------------------------------------------------------------------------
class Driver:
    """Driver that starts an HTTP server for the local UI, which points to the API at api_host:api_port."""

    def __init__(self, api_host="127.0.0.1", api_port=8000, ui_port=8080):
        self.api_host = api_host
        self.api_port = api_port
        self.ui_port = ui_port
        self.api_base_url = f"http://{api_host}:{api_port}"
        self.server = None

        # Make sure the handler knows the port we’re using for the back-end
        APIHandler.api_port = api_port

    def start_ui_server(self):
        try:
            server_address = ('', self.ui_port)
            self.server = HTTPServer(server_address, APIHandler)
            logger.info(f"Starting UI server at http://localhost:{self.ui_port}")
            logger.info(f"Connecting to API at {self.api_base_url}")
            logger.info("Press Ctrl+C to stop the server")
            self.server.serve_forever()
        except KeyboardInterrupt:
            logger.info("UI server stopped")

def main():
    parser = argparse.ArgumentParser(description="Pokemon Agent Driver with tasks-based UI")
    parser.add_argument('--api-host', default="127.0.0.1", help="API host (default: 127.0.0.1)")
    parser.add_argument('--api-port', type=int, default=8000, help="API port (default: 8000)")
    parser.add_argument('--ui-port', type=int, default=8080, help="UI server port (default: 8080)")
    args = parser.parse_args()

    driver = Driver(api_host=args.api_host, api_port=args.api_port, ui_port=args.ui_port)
    driver.start_ui_server()

if __name__ == "__main__":
    main()
