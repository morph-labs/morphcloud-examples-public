import argparse
import base64
import json
import os
import sys
import requests
from PIL import Image
import io
import logging

logger = logging.getLogger(__name__)

class EmulatorClient:
    def __init__(self, host='127.0.0.1', port=9876):
        # Check if host already includes the protocol, if not add http://
        if host.startswith('http://') or host.startswith('https://'):
            # For MorphVM URLs, don't append port as it's handled by the URL routing
            if "cloud.morph.so" in host:
                self.base_url = host
            # For other URLs, handle port as before
            elif ":" not in host.split('/')[-1]:
                self.base_url = f"{host}:{port}"
            else:
                # Host already has port, use it as is
                self.base_url = host
        else:
            # For MorphVM URLs, don't append port
            if "cloud.morph.so" in host:
                self.base_url = f"https://{host}"
            else:
                self.base_url = f"http://{host}:{port}"
        logger.info(f"Initialized client connecting to {self.base_url}")
        
    def get_screenshot(self):
        """Get current screenshot as PIL Image"""
        response = requests.get(f"{self.base_url}/api/screenshot")
        if response.status_code != 200:
            logger.error(f"Error getting screenshot: {response.status_code}")
            return None
        return Image.open(io.BytesIO(response.content))
    
    def get_screenshot_base64(self):
        """Get current screenshot as base64 string"""
        response = requests.get(f"{self.base_url}/api/screenshot")
        if response.status_code != 200:
            logger.error(f"Error getting screenshot: {response.status_code}")
            return ""
        return base64.b64encode(response.content).decode('utf-8')
    
    def get_game_state(self):
        """Get complete game state from server"""
        response = requests.get(f"{self.base_url}/api/game_state")
        if response.status_code != 200:
            logger.error(f"Error response from server: {response.status_code} - {response.text}")
            return {}
        try:
            return response.json()
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            logger.error(f"Response content: {response.text[:100]}...")
            return {}
    
    # Compatibility methods to match Emulator interface
    def get_state_from_memory(self):
        """Get game state string - mimics Emulator.get_state_from_memory()"""
        state_data = self.get_game_state()
        return state_data.get('game_state', '')
    
    def get_collision_map(self):
        """Get collision map - mimics Emulator.get_collision_map()"""
        state_data = self.get_game_state()
        return state_data.get('collision_map', '')
    
    def get_valid_moves(self):
        """Get valid moves - mimics Emulator.get_valid_moves()"""
        state_data = self.get_game_state()
        return state_data.get('valid_moves', [])
    
    def find_path(self, row, col):
        """Find path to position - mimics Emulator.find_path()"""
        result = self.navigate(row, col)
        if not isinstance(result, dict):
            return "Failed to navigate", []
        return result.get('status', 'Navigation failed'), result.get('path', [])
    
    def press_buttons(self, buttons, wait=True, include_state=False, include_screenshot=False):
        """Press a sequence of buttons on the Game Boy
        
        Args:
            buttons: List of buttons to press
            wait: Whether to pause briefly after each button press
            include_state: Whether to include game state in response
            include_screenshot: Whether to include screenshot in response
            
        Returns:
            dict: Response data which may include button press result, game state, and screenshot
        """
        data = {
            "buttons": buttons,
            "wait": wait,
            "include_state": include_state,
            "include_screenshot": include_screenshot
        }
        response = requests.post(f"{self.base_url}/api/press_buttons", json=data)
        if response.status_code != 200:
            logger.error(f"Error pressing buttons: {response.status_code} - {response.text}")
            return {"error": f"Error: {response.status_code}"}
        
        return response.json()
    
    def navigate(self, row, col, include_state=False, include_screenshot=False):
        """Navigate to a specific position on the grid
        
        Args:
            row: Target row coordinate
            col: Target column coordinate
            include_state: Whether to include game state in response
            include_screenshot: Whether to include screenshot in response
            
        Returns:
            dict: Response data which may include navigation result, game state, and screenshot
        """
        data = {
            "row": row,
            "col": col,
            "include_state": include_state,
            "include_screenshot": include_screenshot
        }
        response = requests.post(f"{self.base_url}/api/navigate", json=data)
        if response.status_code != 200:
            logger.error(f"Error navigating: {response.status_code} - {response.text}")
            return {"status": f"Error: {response.status_code}", "path": []}
        
        return response.json()
    
    def read_memory(self, address):
        """Read a specific memory address"""
        response = requests.get(f"{self.base_url}/api/memory/{address}")
        if response.status_code != 200:
            logger.error(f"Error reading memory: {response.status_code} - {response.text}")
            return {"error": f"Error: {response.status_code}"}
        return response.json()
    
    def load_state(self, state_path):
        """Load a saved state"""
        data = {
            "state_path": state_path
        }
        response = requests.post(f"{self.base_url}/api/load_state", json=data)
        if response.status_code != 200:
            logger.error(f"Error loading state: {response.status_code} - {response.text}")
            return {"error": f"Error: {response.status_code}"}
        return response.json()
    
    def save_screenshot(self, filename="screenshot.png"):
        """Save current screenshot to a file"""
        screenshot = self.get_screenshot()
        if screenshot:
            screenshot.save(filename)
            logger.info(f"Screenshot saved as {filename}")
            return True
        return False
    
    def initialize(self):
        """Empty initialize method for compatibility with Emulator"""
        logger.info("Client initialization requested (compatibility method)")
        # Check if server is ready
        try:
            response = requests.get(f"{self.base_url}/api/status")
            status = response.json()
            ready = status.get('ready', False)
            if ready:
                logger.info("Server reports ready status")
            else:
                logger.warning("Server reports not ready")
            return ready
        except Exception as e:
            logger.error(f"Error checking server status: {e}")
            return False
    
    def stop(self):
        """Empty stop method for compatibility with Emulator"""
        logger.info("Client stop requested (compatibility method)")
        # Nothing to do for client
        pass

def main():
    parser = argparse.ArgumentParser(description='Pokemon Game Client')
    parser.add_argument('--host', default='127.0.0.1', help='Server host')
    parser.add_argument('--port', type=int, default=9876, help='Server port')
    args = parser.parse_args()
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    client = EmulatorClient(host=args.host, port=args.port)
    
    print("Pokemon Game Interactive Client")
    print("Available commands:")
    print("  screenshot - Get and display game screenshot")
    print("  save_screenshot [filename] - Save screenshot to file")
    print("  state - Get current game state")
    print("  press <button1> [button2] ... - Press buttons (a, b, up, down, left, right, start, select)")
    print("  navigate <row> <col> - Navigate to position")
    print("  memory <address> - Read memory address")
    print("  load <state_path> - Load a saved state")
    print("  help - Show this help")
    print("  exit - Exit the client")
    
    while True:
        try:
            command = input("\nEnter command: ").strip().split()
            if not command:
                continue
                
            if command[0] == "exit":
                break
                
            elif command[0] == "help":
                print("Available commands:")
                print("  screenshot - Get and display game screenshot")
                print("  save_screenshot [filename] - Save screenshot to file")
                print("  state - Get current game state")
                print("  press <button1> [button2] ... - Press buttons (a, b, up, down, left, right, start, select)")
                print("  navigate <row> <col> - Navigate to position")
                print("  memory <address> - Read memory address")
                print("  load <state_path> - Load a saved state")
                print("  help - Show this help")
                print("  exit - Exit the client")
                
            elif command[0] == "screenshot":
                try:
                    screenshot = client.get_screenshot()
                    if screenshot:
                        screenshot.show()
                    else:
                        print("Failed to get screenshot")
                except Exception as e:
                    print(f"Error getting screenshot: {e}")
                    
            elif command[0] == "save_screenshot":
                try:
                    filename = command[1] if len(command) > 1 else "screenshot.png"
                    if client.save_screenshot(filename):
                        print(f"Screenshot saved as {filename}")
                    else:
                        print("Failed to save screenshot")
                except Exception as e:
                    print(f"Error saving screenshot: {e}")
                    
            elif command[0] == "state":
                try:
                    state = client.get_game_state()
                    print(json.dumps(state, indent=2))
                except Exception as e:
                    print(f"Error getting game state: {e}")
                    
            elif command[0] == "press":
                if len(command) < 2:
                    print("Error: Please specify buttons to press")
                    continue
                try:
                    buttons = command[1:]
                    result = client.press_buttons(buttons)
                    print(f"Pressed buttons: {buttons}")
                    print(f"Result: {result}")
                except Exception as e:
                    print(f"Error pressing buttons: {e}")
                    
            elif command[0] == "navigate":
                if len(command) < 3:
                    print("Error: Please specify row and column")
                    continue
                try:
                    row = int(command[1])
                    col = int(command[2])
                    result = client.navigate(row, col)
                    print(f"Navigating to position ({row}, {col})")
                    print(f"Result: {result}")
                except ValueError:
                    print("Error: Row and column must be integers")
                except Exception as e:
                    print(f"Error navigating: {e}")
                    
            elif command[0] == "memory":
                if len(command) < 2:
                    print("Error: Please specify memory address")
                    continue
                try:
                    address = command[1]
                    result = client.read_memory(address)
                    print(f"Memory at {address}: {result}")
                except Exception as e:
                    print(f"Error reading memory: {e}")
                    
            elif command[0] == "load":
                if len(command) < 2:
                    print("Error: Please specify state path")
                    continue
                try:
                    state_path = command[1]
                    result = client.load_state(state_path)
                    print(f"Loaded state from {state_path}")
                    print(f"Result: {result}")
                except Exception as e:
                    print(f"Error loading state: {e}")
                    
            else:
                print(f"Unknown command: {command[0]}")
                
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
    
    print("Exiting client")

if __name__ == "__main__":
    main()
