#!/usr/bin/env python3
import argparse
import logging
import os
import json
import queue
import threading
import time
import io
import signal
import sys
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from flask import Flask, jsonify, request, Response
from flask_cors import CORS

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

logger = logging.getLogger(__name__)

# Create queues for communication between threads
command_queue = queue.Queue()
result_queue = queue.Queue()

# Global variables
app = Flask(__name__)
CORS(app)  # Add CORS support
emulator = None
emulator_ready = False  # Startup flag to track emulator readiness
server_start_time = time.time()
shutdown_requested = False  # Flag to coordinate shutdown across threads
rom_path = None  # Will be set when a ROM is detected
rom_watch_dir = None  # Directory to watch for ROM files
rom_detected = threading.Event()  # Event to signal when a ROM file is found

# ROM File handler class
class RomFileHandler(FileSystemEventHandler):
    def __init__(self, watch_dir, file_extension=".gb"):
        self.watch_dir = watch_dir
        self.file_extension = file_extension
        self.check_existing_roms()  # Check for existing ROMs on startup
    
    def check_existing_roms(self):
        """Check if a ROM already exists in the watch directory"""
        global rom_path
        
        logger.info(f"Checking for existing ROMs in {self.watch_dir}")
        for filename in os.listdir(self.watch_dir):
            if filename.lower().endswith(self.file_extension):
                rom_path = os.path.join(self.watch_dir, filename)
                logger.info(f"Found existing ROM file: {rom_path}")
                rom_detected.set()
                return
                
        logger.info(f"No existing ROMs found in {self.watch_dir}")
    
    def on_created(self, event):
        """Handle file creation events"""
        global rom_path
        
        if not event.is_directory and event.src_path.lower().endswith(self.file_extension):
            logger.info(f"New ROM file detected: {event.src_path}")
            rom_path = event.src_path
            rom_detected.set()
    
    def on_moved(self, event):
        """Handle file move events (for uploads that create temp files)"""
        global rom_path
        
        if not event.is_directory and event.dest_path.lower().endswith(self.file_extension):
            logger.info(f"ROM file moved/renamed: {event.dest_path}")
            rom_path = event.dest_path
            rom_detected.set()

# Flask API routes
@app.route('/api/status', methods=['GET'])
def get_status():
    """Check if the emulator is ready and return ROM status"""
    uptime = time.time() - server_start_time
    
    status = {
        "ready": emulator_ready,
        "uptime": uptime,
        "uptime_formatted": f"{int(uptime // 60)}m {int(uptime % 60)}s",
        "rom_status": "detected" if rom_detected.is_set() else "waiting",
    }
    
    if rom_path:
        status["rom_file"] = os.path.basename(rom_path)
    
    return jsonify(status)

@app.route('/api/upload_rom', methods=['POST'])
def upload_rom():
    """Upload a ROM file"""
    global rom_path
    
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    if not file.filename.lower().endswith('.gb'):
        return jsonify({"error": "File must be a Game Boy ROM (.gb)"}), 400
    
    # Save the file
    filename = file.filename
    save_path = os.path.join(rom_watch_dir, filename)
    
    try:
        file.save(save_path)
        logger.info(f"ROM uploaded successfully: {save_path}")
        
        # Set the ROM path and trigger the event
        rom_path = save_path
        rom_detected.set()
        
        return jsonify({
            "success": True,
            "message": "ROM uploaded successfully",
            "filename": filename
        })
    except Exception as e:
        logger.error(f"Error uploading ROM: {e}")
        return jsonify({"error": f"Error uploading ROM: {str(e)}"}), 500

@app.route('/api/screenshot', methods=['GET'])
def get_screenshot():
    """Get the current screenshot as a PNG image"""
    logger.debug("Received request for screenshot")
    
    # Check if ROM is detected
    if not rom_detected.is_set():
        logger.warning("No ROM detected yet")
        return jsonify({"error": "No ROM detected yet, please upload a ROM file"}), 503
    
    # Check if emulator is ready
    if not emulator_ready:
        logger.warning("Emulator not ready yet for screenshot request")
        return jsonify({"error": "Emulator still initializing, please try again in a few seconds"}), 503
    
    command_queue.put(('screenshot', None))
    logger.debug("Added screenshot command to queue")
    try:
        result = result_queue.get(timeout=10)
        logger.debug("Got screenshot result from queue")
    except queue.Empty:
        logger.error("Timeout waiting for screenshot result")
        return jsonify({"error": "Timeout waiting for screenshot"}), 500
    
    if isinstance(result, Exception):
        logger.error(f"Error processing screenshot: {result}")
        return jsonify({"error": str(result)}), 500
    
    logger.debug("Returning screenshot response")
    return Response(result, mimetype='image/png')

@app.route('/api/game_state', methods=['GET'])
def get_game_state():
    """Get the current game state from memory"""
    logger.debug("Received request for game state")
    
    # Check if ROM is detected
    if not rom_detected.is_set():
        logger.warning("No ROM detected yet")
        return jsonify({"error": "No ROM detected yet, please upload a ROM file"}), 503
    
    # Check if emulator is ready
    if not emulator_ready:
        logger.warning("Emulator not ready yet for game_state request")
        return jsonify({"error": "Emulator still initializing, please try again in a few seconds"}), 503
    
    command_queue.put(('game_state', None))
    logger.debug("Added game_state command to queue, size: %d", command_queue.qsize())
    
    try:
        logger.debug("Waiting for game_state result from queue")
        result = result_queue.get(timeout=10)
        logger.debug("Got game_state result from queue")
    except queue.Empty:
        logger.error("Timeout waiting for game_state result from queue")
        return jsonify({"error": "Timeout waiting for game state"}), 500
    
    if isinstance(result, Exception):
        logger.error(f"Error processing game state request: {result}")
        return jsonify({"error": str(result)}), 500
    
    logger.debug(f"Returning game state JSON of size: {len(json.dumps(result))} bytes")
    return jsonify(result)

@app.route('/api/press_buttons', methods=['POST'])
def press_buttons():
    """Press a sequence of buttons"""
    data = request.json
    if not data or 'buttons' not in data:
        logger.warning("Missing 'buttons' parameter in request")
        return jsonify({"error": "Missing 'buttons' parameter"}), 400
    
    # Check if ROM is detected
    if not rom_detected.is_set():
        logger.warning("No ROM detected yet")
        return jsonify({"error": "No ROM detected yet, please upload a ROM file"}), 503
    
    # Check if emulator is ready
    if not emulator_ready:
        logger.warning("Emulator not ready yet for press_buttons request")
        return jsonify({"error": "Emulator still initializing, please try again in a few seconds"}), 503
    
    buttons = data['buttons']
    wait = data.get('wait', True)
    include_state = data.get('include_state', False)
    include_screenshot = data.get('include_screenshot', False)
    
    logger.info(f"Queueing button press: {buttons}, wait={wait}")
    command_queue.put(('press_buttons', (buttons, wait)))
    logger.debug(f"Added press_buttons command to queue, size: {command_queue.qsize()}")
    
    try:
        logger.debug("Waiting for press_buttons result from queue")
        result = result_queue.get(timeout=15)
        logger.debug("Got press_buttons result from queue")
    except queue.Empty:
        logger.error("Timeout waiting for press_buttons result")
        return jsonify({"error": "Timeout waiting for button press"}), 500
    
    if isinstance(result, Exception):
        logger.error(f"Error pressing buttons: {result}")
        return jsonify({"error": str(result)}), 500
    
    # Build response object
    response = {"result": result}
    
    # Add game state if requested
    if include_state:
        try:
            command_queue.put(('game_state', None))
            state_result = result_queue.get(timeout=10)
            if not isinstance(state_result, Exception):
                response["game_state"] = state_result
            else:
                logger.error(f"Error getting game state: {state_result}")
        except queue.Empty:
            logger.error("Timeout waiting for game state")
    
    # Add screenshot if requested
    if include_screenshot:
        try:
            command_queue.put(('screenshot', None))
            screenshot_result = result_queue.get(timeout=10)
            if not isinstance(screenshot_result, Exception):
                import base64
                # Convert bytes to base64
                response["screenshot"] = base64.b64encode(screenshot_result).decode('utf-8')
            else:
                logger.error(f"Error getting screenshot: {screenshot_result}")
        except queue.Empty:
            logger.error("Timeout waiting for screenshot")
    
    return jsonify(response)

@app.route('/api/navigate', methods=['POST'])
def navigate():
    """Navigate to a specific grid position"""
    data = request.json
    if not data or 'row' not in data or 'col' not in data:
        logger.warning("Missing 'row' or 'col' parameter in request")
        return jsonify({"error": "Missing 'row' or 'col' parameter"}), 400
    
    # Check if ROM is detected
    if not rom_detected.is_set():
        logger.warning("No ROM detected yet")
        return jsonify({"error": "No ROM detected yet, please upload a ROM file"}), 503
    
    # Check if emulator is ready
    if not emulator_ready:
        logger.warning("Emulator not ready yet for navigate request")
        return jsonify({"error": "Emulator still initializing, please try again in a few seconds"}), 503
    
    row = data['row']
    col = data['col']
    include_state = data.get('include_state', False)
    include_screenshot = data.get('include_screenshot', False)
    
    logger.info(f"Queueing navigation to position: ({row}, {col})")
    command_queue.put(('navigate', (row, col)))
    logger.debug(f"Added navigate command to queue, size: {command_queue.qsize()}")
    
    try:
        logger.debug("Waiting for navigate result from queue")
        result = result_queue.get(timeout=30)
        logger.debug("Got navigate result from queue")
    except queue.Empty:
        logger.error("Timeout waiting for navigate result")
        return jsonify({"error": "Timeout waiting for navigation"}), 500
    
    if isinstance(result, Exception):
        logger.error(f"Error navigating: {result}")
        return jsonify({"error": str(result)}), 500
    
    # Make a copy of the result for our response
    response = result.copy() if isinstance(result, dict) else {"result": result}
    
    # Add game state if requested
    if include_state:
        try:
            command_queue.put(('game_state', None))
            state_result = result_queue.get(timeout=10)
            if not isinstance(state_result, Exception):
                response["game_state"] = state_result
            else:
                logger.error(f"Error getting game state: {state_result}")
        except queue.Empty:
            logger.error("Timeout waiting for game state")
    
    # Add screenshot if requested
    if include_screenshot:
        try:
            command_queue.put(('screenshot', None))
            screenshot_result = result_queue.get(timeout=10)
            if not isinstance(screenshot_result, Exception):
                import base64
                # Convert bytes to base64
                response["screenshot"] = base64.b64encode(screenshot_result).decode('utf-8')
            else:
                logger.error(f"Error getting screenshot: {screenshot_result}")
        except queue.Empty:
            logger.error("Timeout waiting for screenshot")
    
    return jsonify(response)

@app.route('/api/memory/<address>', methods=['GET'])
def read_memory(address):
    """Read a specific memory address or range"""
    logger.debug(f"Received request to read memory at {address}")
    
    # Check if ROM is detected
    if not rom_detected.is_set():
        logger.warning("No ROM detected yet")
        return jsonify({"error": "No ROM detected yet, please upload a ROM file"}), 503
    
    # Check if emulator is ready
    if not emulator_ready:
        logger.warning(f"Emulator not ready yet for memory read request: {address}")
        return jsonify({"error": "Emulator still initializing, please try again in a few seconds"}), 503
    
    command_queue.put(('read_memory', address))
    logger.debug(f"Added read_memory command to queue, size: {command_queue.qsize()}")
    
    try:
        logger.debug("Waiting for read_memory result from queue")
        result = result_queue.get(timeout=10)
        logger.debug("Got read_memory result from queue")
    except queue.Empty:
        logger.error("Timeout waiting for read_memory result")
        return jsonify({"error": "Timeout waiting for memory read"}), 500
    
    if isinstance(result, Exception):
        logger.error(f"Error reading memory: {result}")
        return jsonify({"error": str(result)}), 500
    
    return jsonify(result)

@app.route('/api/load_state', methods=['POST'])
def load_state():
    """Load a saved state"""
    data = request.json
    if not data or 'state_path' not in data:
        logger.warning("Missing 'state_path' parameter in request")
        return jsonify({"error": "Missing 'state_path' parameter"}), 400
    
    # Check if ROM is detected
    if not rom_detected.is_set():
        logger.warning("No ROM detected yet")
        return jsonify({"error": "No ROM detected yet, please upload a ROM file"}), 503
    
    # Check if emulator is ready
    if not emulator_ready:
        logger.warning("Emulator not ready yet for load_state request")
        return jsonify({"error": "Emulator still initializing, please try again in a few seconds"}), 503
    
    state_path = data['state_path']
    logger.info(f"Queueing state load from: {state_path}")
    command_queue.put(('load_state', state_path))
    logger.debug(f"Added load_state command to queue, size: {command_queue.qsize()}")
    
    try:
        logger.debug("Waiting for load_state result from queue")
        result = result_queue.get(timeout=15)
        logger.debug("Got load_state result from queue")
    except queue.Empty:
        logger.error("Timeout waiting for load_state result")
        return jsonify({"error": "Timeout waiting for state load"}), 500
    
    if isinstance(result, Exception):
        logger.error(f"Error loading state: {result}")
        return jsonify({"error": str(result)}), 500
    
    return jsonify({"result": result})

def flask_thread(host, port):
    """Run Flask in a separate thread"""
    logger.info(f"Starting Flask server on {host}:{port}")
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
    logger.info("Flask server thread exited")

def emulator_thread(headless, sound):
    """Main emulator thread that processes commands from the queue"""
    global emulator, emulator_ready, shutdown_requested
    
    try:
        # Wait for a ROM file to be detected
        logger.info(f"Emulator thread started, waiting for ROM file...")
        rom_detected.wait()  # Block until a ROM is detected
        
        # Import the emulator module only when needed
        from agent.emulator import Emulator
        from agent.memory_reader import PokemonRedReader
        
        # Initialize emulator with the detected ROM
        logger.info(f"===== EMULATOR THREAD STARTING WITH ROM: {rom_path} =====")
        
        try:
            emulator = Emulator(rom_path, headless, sound)
            logger.info("Created emulator instance successfully")
        except Exception as e:
            logger.error(f"FAILED to create emulator instance: {e}", exc_info=True)
            raise
            
        try:
            logger.info("Calling emulator.initialize()")
            emulator.initialize()
            logger.info("Emulator initialized successfully")
        except Exception as e:
            logger.error(f"FAILED to initialize emulator: {e}", exc_info=True)
            raise
            
        # Set the ready flag to true
        emulator_ready = True
        logger.info("===== EMULATOR READY FLAG SET TO TRUE =====")
        
        # Process commands from the queue
        logger.info("===== STARTING COMMAND PROCESSING LOOP =====")
        while not shutdown_requested:
            try:
                # Check for commands, but don't block to ensure SDL gets regular updates
                try:
                    command, args = command_queue.get(block=False)
                    logger.info(f"Got command from queue: {command}")
                    
                    # Process the command
                    if command == 'exit':
                        logger.info("Received exit command, breaking command loop")
                        break
                        
                    elif command == 'screenshot':
                        try:
                            logger.debug("Processing screenshot command")
                            screenshot = emulator.get_screenshot()
                            img_byte_arr = io.BytesIO()
                            screenshot.save(img_byte_arr, format='PNG')
                            logger.debug("Screenshot captured, putting in result queue")
                            result_queue.put(img_byte_arr.getvalue())
                            logger.debug("Screenshot result added to queue")
                        except Exception as e:
                            logger.error(f"Error getting screenshot: {e}", exc_info=True)
                            result_queue.put(e)
                    
                    elif command == 'game_state':
                        try:
                            logger.info("Processing game_state command")
                            logger.debug("Calling get_state_from_memory()")
                            game_state = emulator.get_state_from_memory()
                            logger.debug("Calling get_collision_map()")
                            collision_map = emulator.get_collision_map()
                            logger.debug("Calling get_valid_moves()")
                            valid_moves = emulator.get_valid_moves()
                            logger.debug("Calling get_coordinates()")
                            coordinates = emulator.get_coordinates()
                            
                            response_data = {
                                "game_state": game_state,
                                "collision_map": collision_map,
                                "valid_moves": valid_moves,
                                "coordinates": coordinates
                            }
                            logger.debug(f"Game state response prepared with keys: {response_data.keys()}")
                            logger.debug("Putting game state in result queue")
                            result_queue.put(response_data)
                            logger.info("Game state response sent to queue")
                        except Exception as e:
                            logger.error(f"Error getting game state: {e}", exc_info=True)
                            result_queue.put(e)
                    
                    elif command == 'press_buttons':
                        try:
                            buttons, wait = args
                            logger.info(f"Processing press_buttons command: {buttons}, wait={wait}")
                            result = emulator.press_buttons(buttons, wait)
                            logger.debug(f"Buttons pressed, result: {result}")
                            logger.debug("Putting press_buttons result in queue")
                            result_queue.put(result)
                            logger.debug("Press buttons result added to queue")
                        except Exception as e:
                            logger.error(f"Error pressing buttons: {e}", exc_info=True)
                            result_queue.put(e)
                    
                    elif command == 'navigate':
                        try:
                            row, col = args
                            logger.info(f"Processing navigate command to position: ({row}, {col})")
                            logger.debug("Calling find_path()")
                            status, path = emulator.find_path(row, col)
                            logger.info(f"Navigation path found: {path}")
                            
                            if path:
                                for direction in path:
                                    logger.debug(f"Pressing button: {direction}")
                                    emulator.press_buttons([direction], True)
                            
                            logger.debug("Putting navigate result in queue")        
                            result_queue.put({"status": status, "path": path})
                            logger.debug("Navigate result added to queue")
                        except Exception as e:
                            logger.error(f"Error navigating: {e}", exc_info=True)
                            result_queue.put(e)
                    
                    elif command == 'read_memory':
                        try:
                            address = args
                            logger.info(f"Processing read_memory command at address: {address}")
                            reader = PokemonRedReader(emulator.pyboy.memory)
                            
                            # Parse hex address
                            if isinstance(address, str) and address.startswith("0x"):
                                addr = int(address, 16)
                                result = {"address": address, "value": emulator.pyboy.memory[addr]}
                            else:
                                result = {"error": "Invalid address format. Use 0xXXXX"}
                            
                            logger.debug(f"Memory read result: {result}")
                            logger.debug("Putting read_memory result in queue")
                            result_queue.put(result)
                            logger.debug("Read memory result added to queue")
                        except Exception as e:
                            logger.error(f"Error reading memory: {e}", exc_info=True)
                            result_queue.put(e)
                    
                    elif command == 'load_state':
                        try:
                            state_path = args
                            logger.info(f"Processing load_state command from: {state_path}")
                            emulator.load_state(state_path)
                            logger.debug("State loaded successfully")
                            logger.debug("Putting load_state result in queue")
                            result_queue.put("State loaded successfully")
                            logger.debug("Load state result added to queue")
                        except Exception as e:
                            logger.error(f"Error loading state: {e}", exc_info=True)
                            result_queue.put(e)
                    
                    # Always mark the task as done
                    logger.debug(f"Marking command {command} as done")
                    command_queue.task_done()
                    
                except queue.Empty:
                    # No commands, just tick the emulator by 1 frame to keep SDL event loop running
                    if emulator_ready:
                        emulator.tick(1)
                    continue
                
                # Run a tick to process SDL events (advancing 1 frame)
                if emulator_ready:
                    emulator.tick(1)
                
            except Exception as e:
                logger.error(f"Error processing command: {e}", exc_info=True)
                # Try to respond with the error if possible
                try:
                    logger.debug("Putting error in result queue")
                    result_queue.put(e)
                    logger.debug("Error added to result queue")
                except:
                    logger.error("Failed to put error in result queue", exc_info=True)
        
        logger.info("Exiting emulator command processing loop")
    except Exception as e:
        logger.error(f"Fatal emulator error: {e}", exc_info=True)
        # Make sure to exit the thread properly
        try:
            logger.debug("Putting fatal error in result queue")
            result_queue.put(Exception(f"Fatal emulator error: {e}"))
            logger.debug("Fatal error added to result queue")
        except:
            logger.error("Failed to put fatal error in result queue", exc_info=True)
    finally:
        # Reset the emulator ready flag
        emulator_ready = False
        logger.info("Emulator ready flag reset to False")

def signal_handler(sig, frame):
    """Handle interrupt signals by initiating a clean shutdown"""
    global shutdown_requested
    
    if shutdown_requested:
        logger.warning("Forced exit requested, terminating immediately")
        sys.exit(1)
    
    logger.info("Interrupt received, shutting down server gracefully...")
    shutdown_requested = True
    
    # Put an exit command in the queue to stop the emulator thread
    try:
        command_queue.put(('exit', None))
        logger.info("Exit command queued for emulator thread")
    except:
        logger.error("Failed to queue exit command", exc_info=True)
    
    # Allow up to 5 seconds for graceful shutdown before forcing exit
    signal.alarm(5)  # Set a backup alarm to force exit if needed

def perform_shutdown():
    """Clean up resources before shutdown"""
    global emulator, emulator_ready
    
    logger.info("Performing server shutdown sequence")
    emulator_ready = False
    
    # Clear any pending commands in the queues
    while not command_queue.empty():
        try:
            command_queue.get_nowait()
            command_queue.task_done()
        except queue.Empty:
            break
    
    while not result_queue.empty():
        try:
            result_queue.get_nowait()
        except queue.Empty:
            break
    
    # Shut down the emulator if it exists
    if emulator:
        try:
            logger.info("Stopping emulator")
            emulator.stop()
            logger.info("Emulator stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping emulator: {e}", exc_info=True)
    
    logger.info("Server shutdown complete")

def run_server(watch_dir, host='127.0.0.1', port=5000, headless=False, sound=False):
    """Run the server with the specified configuration"""
    global rom_watch_dir
    
    # Set the ROM watch directory
    rom_watch_dir = os.path.abspath(watch_dir)
    
    # Create watch directory if it doesn't exist
    if not os.path.exists(rom_watch_dir):
        os.makedirs(rom_watch_dir, exist_ok=True)
        logger.info(f"Created ROM watch directory: {rom_watch_dir}")
    
    # Set up file system observer for the watch directory
    event_handler = RomFileHandler(rom_watch_dir)
    observer = Observer()
    observer.schedule(event_handler, rom_watch_dir, recursive=False)
    observer.start()
    logger.info(f"Started watching for ROM files in: {rom_watch_dir}")
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)   # Handle Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Handle termination signal
    if hasattr(signal, 'SIGALRM'):  # Not available on Windows
        signal.signal(signal.SIGALRM, lambda sig, frame: sys.exit(1))  # Force exit after timeout
    
    # Start Flask in a separate thread
    logger.info("Starting server setup")
    server_thread = threading.Thread(target=flask_thread, args=(host, port), daemon=True)
    server_thread.start()
    logger.info(f"Started Flask server thread on {host}:{port}")
    
    # Run emulator in the main thread (required for SDL/macOS compatibility)
    logger.info(f"Starting ROM watch server")
    logger.info(f"Server running on {host}:{port}, watching for ROMs in {rom_watch_dir}")
    
    try:
        # Run the emulator on the main thread
        logger.info("===== CALLING EMULATOR_THREAD ON MAIN THREAD =====")
        emulator_thread(headless, sound)
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
    except Exception as e:
        logger.error(f"FATAL ERROR in emulator thread: {e}", exc_info=True)
    finally:
        # Stop the file observer
        observer.stop()
        observer.join()
        
        # Perform clean shutdown
        perform_shutdown()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pokemon Game Server with ROM watching")
    parser.add_argument(
        "--watch-dir", 
        type=str, 
        default="roms",
        help="Directory to watch for ROM files"
    )
    parser.add_argument(
        "--host", 
        type=str, 
        default="127.0.0.1", 
        help="Host address to bind to"
    )
    parser.add_argument(
        "--port", 
        type=int, 
        default=9876, 
        help="Port to listen on"
    )
    parser.add_argument(
        "--display", 
        action="store_true", 
        help="Run with display (not headless)"
    )
    parser.add_argument(
        "--sound", 
        action="store_true", 
        help="Enable sound (only applicable with display)"
    )
    
    args = parser.parse_args()
    
    logger.info(f"Starting ROM watch server with directory: {args.watch_dir}")
    run_server(
        watch_dir=args.watch_dir,
        host=args.host,
        port=args.port,
        headless=not args.display,
        sound=args.sound if args.display else False
    )
