
#!/usr/bin/env python3
# /// script
# dependencies = [
#   "morphcloud",
#   "requests",
#   "pillow",
#   "rich",
#   "anthropic",
# ]
# ///


"""Run a non-interactive server agent that plays Pokemon automatically.

This script combines the EmulatorClient and PokemonAgent to set up a basic agent.
"""
import io
import sys
import json
import copy
import typing
import base64
import logging
import argparse
import time

import requests
import webbrowser

from PIL import Image

from anthropic import Anthropic
from rich.console import Console

from morphcloud.api import MorphCloudClient

# Set up logging - this will be configured properly in main() based on command line args
logger = logging.getLogger(__name__)

# Configuration
MAX_TOKENS = 4096
MODEL_NAME = "claude-3-7-sonnet-20250219"
TEMPERATURE = 0.7
USE_NAVIGATOR = True


class EmulatorClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 9876):
        # Check if host already includes the protocol, if not add http://
        if host.startswith("http://") or host.startswith("https://"):
            # For MorphVM URLs, don't append port as it's handled by the URL routing
            if "cloud.morph.so" in host or port is None:
                self.base_url = host
            # For other URLs, handle port as before
            elif ":" not in host.split("/")[-1]:
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
        return base64.b64encode(response.content).decode("utf-8")

    def get_game_state(self):
        """Get complete game state from server"""
        response = requests.get(f"{self.base_url}/api/game_state")
        if response.status_code != 200:
            logger.error(
                f"Error response from server: {response.status_code} - {response.text}"
            )
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
        return state_data.get("game_state", "")

    def get_collision_map(self):
        """Get collision map - mimics Emulator.get_collision_map()"""
        state_data = self.get_game_state()
        return state_data.get("collision_map", "")

    def get_valid_moves(self):
        """Get valid moves - mimics Emulator.get_valid_moves()"""
        state_data = self.get_game_state()
        return state_data.get("valid_moves", [])

    def find_path(self, row, col):
        """Find path to position - mimics Emulator.find_path()"""
        result = self.navigate(row, col)
        if not isinstance(result, dict):
            return "Failed to navigate", []
        return result.get("status", "Navigation failed"), result.get("path", [])

    def press_buttons(
        self, buttons, wait=True, include_state=False, include_screenshot=False
    ):
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
            "include_screenshot": include_screenshot,
        }
        response = requests.post(f"{self.base_url}/api/press_buttons", json=data)
        if response.status_code != 200:
            logger.error(
                f"Error pressing buttons: {response.status_code} - {response.text}"
            )
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
            "include_screenshot": include_screenshot,
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
            logger.error(
                f"Error reading memory: {response.status_code} - {response.text}"
            )
            return {"error": f"Error: {response.status_code}"}
        return response.json()

    def load_state(self, state_path):
        """Load a saved state"""
        data = {"state_path": state_path}
        response = requests.post(f"{self.base_url}/api/load_state", json=data)
        if response.status_code != 200:
            logger.error(
                f"Error loading state: {response.status_code} - {response.text}"
            )
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

    def initialize(self, max_retries=5, retry_delay=3):
        """
        Initialize method with retry capability for compatibility with Emulator
        
        Args:
            max_retries (int): Maximum number of retry attempts
            retry_delay (int): Delay between retries in seconds
            
        Returns:
            bool: True if server is ready, False otherwise
        """
        logger.info(f"Client initialization requested (compatibility method) with {max_retries} retries")
        
        # Implement retry logic
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Checking server status (attempt {attempt}/{max_retries})")
                response = requests.get(f"{self.base_url}/api/status", timeout=10)
                status = response.json()
                ready = status.get("ready", False)
                
                if ready:
                    logger.info("Server reports ready status")
                    return True
                else:
                    logger.warning(f"Server reports not ready (attempt {attempt}/{max_retries})")
                    
                # If not ready and we have more attempts, wait before trying again
                if attempt < max_retries:
                    logger.info(f"Waiting {retry_delay} seconds before retry...")
                    time.sleep(retry_delay)
                    
            except requests.exceptions.Timeout:
                logger.warning(f"Connection timeout (attempt {attempt}/{max_retries})")
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"Connection error: {e} (attempt {attempt}/{max_retries})")
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    
            except Exception as e:
                logger.error(f"Error checking server status: {e} (attempt {attempt}/{max_retries})")
                if attempt < max_retries:
                    time.sleep(retry_delay)
        
        logger.error(f"Server not ready after {max_retries} attempts")
        return False


    def stop(self):
        """Empty stop method for compatibility with Emulator"""
        logger.info("Client stop requested (compatibility method)")
        # Nothing to do for client
        pass


def get_screenshot_base64(screenshot, upscale=1):
    """Convert PIL image to base64 string."""
    # Resize if needed
    if upscale > 1:
        new_size = (screenshot.width * upscale, screenshot.height * upscale)
        screenshot = screenshot.resize(new_size)

    # Convert to base64
    buffered = io.BytesIO()
    screenshot.save(buffered, format="PNG")
    return base64.standard_b64encode(buffered.getvalue()).decode()


class PokemonAgent:
    def __init__(
        self,
        server_host="127.0.0.1",
        server_port: typing.Optional[int] = 9876,
        max_history=60,
        display_config=None,
        morph_client=None,  # Add MorphCloudClient as a parameter
        parent_snapshot_id=None,  # Add parent snapshot ID parameter
        dashboard_run_id=None,  # Add dashboard run ID parameter
    ):
        """Initialize the server agent.

        Args:
            server_host: Host where the game server is running
            server_port: Port number of the game server
            max_history: Maximum number of messages in history before summarization
            display_config: Dictionary with display configuration options
            morph_client: Optional MorphCloudClient instance for snapshot creation
            parent_snapshot_id: Optional ID of the parent snapshot for lineage tracking
            dashboard_run_id: Optional ID for grouping snapshots by dashboard run
        """
        self.client = EmulatorClient(host=server_host, port=server_port or 9876)
        self.anthropic = Anthropic()
        self.running = True
        self.message_history = [
            {"role": "user", "content": "You may now begin playing."}
        ]
        self.max_history = max_history
        
        # Store the MorphCloud client and snapshot tracking IDs
        self.morph_client = morph_client
        self.parent_snapshot_id = parent_snapshot_id
        self.dashboard_run_id = dashboard_run_id or parent_snapshot_id  # Use parent as fallback
        self.last_snapshot_id = parent_snapshot_id  # Track the last created snapshot ID

        # Set display configuration with defaults
        self.display_config = display_config or {
            "show_game_state": False,
            "show_collision_map": False,
            "quiet_mode": False,
        }

        # Log initialization with chosen configuration
        logger.debug(f"Agent initialized with display config: {self.display_config}")
        if self.morph_client and self.parent_snapshot_id:
            logger.info(f"Snapshot tracking enabled. Parent snapshot: {self.parent_snapshot_id}")
            if self.dashboard_run_id:
                logger.info(f"Dashboard run ID for grouping snapshots: {self.dashboard_run_id}")

        # Check if the server is ready
        if not self.client.initialize():
            logger.error(
                "Server not ready - please start the server before running the agent"
            )
            raise RuntimeError("Server not ready")

    SYSTEM_PROMPT = """You are playing Pokemon Red. You can see the game screen and control the game by executing emulator commands.

Your goal is to play through Pokemon Red and eventually defeat the Elite Four. Make decisions based on what you see on the screen.

Before each action, explain your reasoning briefly, then use the emulator tool to execute your chosen commands.

The conversation history may occasionally be summarized to save context space. If you see a message labeled "CONVERSATION HISTORY SUMMARY", this contains the key information about your progress so far. Use this information to maintain continuity in your gameplay."""

    SUMMARY_PROMPT = """I need you to create a detailed summary of our conversation history up to this point. This summary will replace the full conversation history to manage the context window.

Please include:
1. Key game events and milestones you've reached
2. Important decisions you've made
3. Current objectives or goals you're working toward
4. Your current location and Pokémon team status
5. Any strategies or plans you've mentioned

The summary should be comprehensive enough that you can continue gameplay without losing important context about what has happened so far."""

    AVAILABLE_TOOLS = [
        {
            "name": "press_buttons",
            "description": "Press a sequence of buttons on the Game Boy.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "buttons": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "a",
                                "b",
                                "start",
                                "select",
                                "up",
                                "down",
                                "left",
                                "right",
                            ],
                        },
                        "description": "List of buttons to press in sequence. Valid buttons: 'a', 'b', 'start', 'select', 'up', 'down', 'left', 'right'",
                    },
                    "wait": {
                        "type": "boolean",
                        "description": "Whether to wait for a brief period after pressing each button. Defaults to true.",
                    },
                },
                "required": ["buttons"],
            },
        }
    ]

    # Add navigation tool if enabled
    if USE_NAVIGATOR:
        AVAILABLE_TOOLS.append(
            {
                "name": "navigate_to",
                "description": "Automatically navigate to a position on the map grid. The screen is divided into a 9x10 grid, with the top-left corner as (0, 0). This tool is only available in the overworld.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "row": {
                            "type": "integer",
                            "description": "The row coordinate to navigate to (0-8).",
                        },
                        "col": {
                            "type": "integer",
                            "description": "The column coordinate to navigate to (0-9).",
                        },
                    },
                    "required": ["row", "col"],
                },
            }
        )

    def process_tool_call(self, tool_call):
        """Process a single tool call."""
        tool_name = tool_call.name
        tool_input = tool_call.input

        # In quiet mode, only log at debug level
        if self.display_config["quiet_mode"]:
            logger.debug(f"Processing tool call: {tool_name}")
        else:
            logger.info(f"Processing tool call: {tool_name}")

        if tool_name == "press_buttons":
            buttons = tool_input["buttons"]
            wait = tool_input.get("wait", True)

            # Log the button press action
            if self.display_config["quiet_mode"]:
                logger.debug(f"[Buttons] Pressing: {buttons} (wait={wait})")
            else:
                logger.info(f"[Buttons] Pressing: {buttons} (wait={wait})")

            # Use enhanced client method to get result, state, and screenshot in one call
            response = self.client.press_buttons(
                buttons, wait=wait, include_state=True, include_screenshot=True
            )

            # Extract results from response
            result = response.get("result", f"Pressed buttons: {', '.join(buttons)}")

            # Get game state from response or fetch it if not included
            if "game_state" in response:
                memory_info = response["game_state"].get("game_state", "")
                if self.display_config["show_game_state"]:
                    logger.info(f"[Memory State from response]")
                    logger.info(memory_info)
                else:
                    logger.debug(f"[Memory State from response]")
                    logger.debug(memory_info)

                collision_map = response["game_state"].get("collision_map", "")
                if collision_map and self.display_config["show_collision_map"]:
                    logger.info(f"[Collision Map from response]\n{collision_map}")
                elif collision_map:
                    logger.debug(f"[Collision Map from response]\n{collision_map}")
            else:
                # Fallback to separate calls if state not included
                memory_info = self.client.get_state_from_memory()
                if self.display_config["show_game_state"]:
                    logger.info(f"[Memory State after action]")
                    logger.info(memory_info)
                else:
                    logger.debug(f"[Memory State after action]")
                    logger.debug(memory_info)

                collision_map = self.client.get_collision_map()
                if collision_map and self.display_config["show_collision_map"]:
                    logger.info(f"[Collision Map after action]\n{collision_map}")
                elif collision_map:
                    logger.debug(f"[Collision Map after action]\n{collision_map}")

            # Get screenshot from response or fetch it if not included
            if "screenshot" in response:
                screenshot_b64 = response["screenshot"]
            else:
                screenshot = self.client.get_screenshot()
                screenshot_b64 = get_screenshot_base64(screenshot, upscale=2)

            # Build response content based on display configuration
            content = [
                {"type": "text", "text": f"Pressed buttons: {', '.join(buttons)}"},
                {
                    "type": "text",
                    "text": "\nHere is a screenshot of the screen after your button presses:",
                },
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": screenshot_b64,
                    },
                },
            ]

            # Add game state to Claude's view if enabled
            content.append(
                {
                    "type": "text",
                    "text": f"\nGame state information from memory after your action:\n{memory_info}",
                }
            )

            # Return tool result as a dictionary
            return {
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": content,
            }
        elif tool_name == "navigate_to":
            row = tool_input["row"]
            col = tool_input["col"]

            # Log the navigation action
            if self.display_config["quiet_mode"]:
                logger.debug(f"[Navigation] Navigating to: ({row}, {col})")
            else:
                logger.info(f"[Navigation] Navigating to: ({row}, {col})")

            # Use enhanced client method to get result, state, and screenshot in one call
            response = self.client.navigate(
                row, col, include_state=True, include_screenshot=True
            )

            # Extract navigation result
            status = response.get("status", "Unknown status")
            path = response.get("path", [])

            if path:
                result = f"Navigation successful: followed path with {len(path)} steps"
            else:
                result = f"Navigation failed: {status}"

            # Get game state from response or fetch it if not included
            if "game_state" in response:
                memory_info = response["game_state"].get("game_state", "")
                if self.display_config["show_game_state"]:
                    logger.info(f"[Memory State from response]")
                    logger.info(memory_info)
                else:
                    logger.debug(f"[Memory State from response]")
                    logger.debug(memory_info)

                collision_map = response["game_state"].get("collision_map", "")
                if collision_map and self.display_config["show_collision_map"]:
                    logger.info(f"[Collision Map from response]\n{collision_map}")
                elif collision_map:
                    logger.debug(f"[Collision Map from response]\n{collision_map}")
            else:
                # Fallback to separate calls if state not included
                memory_info = self.client.get_state_from_memory()
                if self.display_config["show_game_state"]:
                    logger.info(f"[Memory State after action]")
                    logger.info(memory_info)
                else:
                    logger.debug(f"[Memory State after action]")
                    logger.debug(memory_info)

                collision_map = self.client.get_collision_map()
                if collision_map and self.display_config["show_collision_map"]:
                    logger.info(f"[Collision Map after action]\n{collision_map}")
                elif collision_map:
                    logger.debug(f"[Collision Map after action]\n{collision_map}")

            # Get screenshot from response or fetch it if not included
            if "screenshot" in response:
                screenshot_b64 = response["screenshot"]
            else:
                screenshot = self.client.get_screenshot()
                screenshot_b64 = get_screenshot_base64(screenshot, upscale=2)

            # Build response content based on display configuration
            content = [
                {"type": "text", "text": f"Navigation result: {result}"},
                {
                    "type": "text",
                    "text": "\nHere is a screenshot of the screen after navigation:",
                },
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": screenshot_b64,
                    },
                },
            ]

            # Add game state to Claude's view if enabled
            content.append(
                {
                    "type": "text",
                    "text": f"\nGame state information from memory after your action:\n{memory_info}",
                }
            )

            # Return tool result as a dictionary
            return {
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": content,
            }
        else:
            logger.error(f"Unknown tool called: {tool_name}")
            return {
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": [
                    {"type": "text", "text": f"Error: Unknown tool '{tool_name}'"}
                ],
            }

    def run(self, num_steps=1, instance_id=None, snapshot_name_prefix=None):
        """Main agent loop.

        Args:
            num_steps: Number of steps to run for
            instance_id: ID of the current instance for snapshot creation
            snapshot_name_prefix: Prefix for naming snapshots
        """
        if self.display_config["quiet_mode"]:
            logger.debug(f"Starting agent loop for {num_steps} steps")
        else:
            logger.info(f"Starting agent loop for {num_steps} steps")

        steps_completed = 0
        snapshots = []
        
        while self.running and steps_completed < num_steps:
            try:
                messages = copy.deepcopy(self.message_history)

                if len(messages) >= 3:
                    if (
                        messages[-1]["role"] == "user"
                        and isinstance(messages[-1]["content"], list)
                        and messages[-1]["content"]
                    ):
                        messages[-1]["content"][-1]["cache_control"] = {
                            "type": "ephemeral"
                        }

                    if (
                        len(messages) >= 5
                        and messages[-3]["role"] == "user"
                        and isinstance(messages[-3]["content"], list)
                        and messages[-3]["content"]
                    ):
                        messages[-3]["content"][-1]["cache_control"] = {
                            "type": "ephemeral"
                        }

                # Get model response
                response = self.anthropic.messages.create(
                    model=MODEL_NAME,
                    max_tokens=MAX_TOKENS,
                    system=self.SYSTEM_PROMPT,
                    messages=messages,
                    tools=self.AVAILABLE_TOOLS,
                    temperature=TEMPERATURE,
                )

                # Log token usage
                if self.display_config["quiet_mode"]:
                    logger.debug(f"Response usage: {response.usage}")
                else:
                    logger.info(f"Response usage: {response.usage}")

                # Extract tool calls
                tool_calls = [
                    block for block in response.content if block.type == "tool_use"
                ]

                # Display the model's reasoning
                for block in response.content:
                    if block.type == "text":
                        # Claude's thoughts should always be visible, even in quiet mode
                        logger.info(f"[Claude] {block.text}")
                    elif block.type == "tool_use":
                        # Tool calls should be visible at info level by default
                        if self.display_config["quiet_mode"]:
                            logger.info(
                                f"[Claude Action] Using tool: {block.name} with input: {block.input}"
                            )
                        else:
                            logger.info(
                                f"[Tool Use] {block.name} with input: {block.input}"
                            )

                # Process tool calls
                if tool_calls:
                    # Add assistant message to history
                    assistant_content = []
                    for block in response.content:
                        if block.type == "text":
                            assistant_content.append(
                                {"type": "text", "text": block.text}
                            )
                        elif block.type == "tool_use":
                            assistant_content.append(
                                {"type": "tool_use", **dict(block)}
                            )

                    self.message_history.append(
                        {"role": "assistant", "content": assistant_content}
                    )

                    # Process tool calls and create tool results
                    tool_results = []
                    for tool_call in tool_calls:
                        tool_result = self.process_tool_call(tool_call)
                        tool_results.append(tool_result)

                    # Add tool results to message history
                    self.message_history.append(
                        {"role": "user", "content": tool_results}
                    )

                    # Check if we need to summarize the history
                    if len(self.message_history) >= self.max_history:
                        self.summarize_history()

                steps_completed += 1
                if self.display_config["quiet_mode"]:
                    logger.debug(f"Completed step {steps_completed}/{num_steps}")
                else:
                    logger.info(f"Completed step {steps_completed}/{num_steps}")
                
                # Create a snapshot after each step if morph_client and instance_id are provided
                if self.morph_client and instance_id:
                    step_num = steps_completed
                    snapshot_name = f"{snapshot_name_prefix}_step_{step_num}" if snapshot_name_prefix else f"pokemon_step_{step_num}"
                    
                    logger.info(f"Creating snapshot after step {step_num}...")
                    try:
                        # Create metadata dictionary to track lineage
                        metadata = {
                            "step_number": str(step_num),
                            "timestamp": str(int(time.time())),
                        }
                        
                        # Add parent_snapshot if we have one
                        if self.parent_snapshot_id:
                            metadata["parent_snapshot"] = self.parent_snapshot_id
                            
                        # Add dashboard_run_id for filtering in dashboard
                        if self.dashboard_run_id:
                            metadata["dashboard_run_id"] = self.dashboard_run_id
                            
                        # Add previous snapshot if we have one
                        if self.last_snapshot_id:
                            metadata["prev_snapshot"] = self.last_snapshot_id
                            
                        # Create the snapshot with metadata
                        instance = self.morph_client.instances.get(instance_id)
                        
                        snapshot = instance.snapshot()
                        snapshot.set_metadata(metadata)
                        
                        # Update our last snapshot ID
                        self.last_snapshot_id = snapshot.id
                        
                        logger.info(f"✅ Snapshot created with ID: {snapshot.id}")
                        logger.info(f"   Metadata: parent={metadata.get('parent_snapshot', 'None')}, prev={metadata.get('prev_snapshot', 'None')}, step={step_num}, dashboard_run_id={metadata.get('dashboard_run_id', 'None')}")
                        
                        # Keep track of all snapshots
                        snapshots.append({
                            'step': step_num,
                            'snapshot_id': snapshot.id,
                            'name': snapshot_name,
                            'metadata': metadata
                        })
                    except Exception as e:
                        logger.error(f"Failed to create snapshot: {e}")

            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt, stopping")
                self.running = False
            except Exception as e:
                logger.error(f"Error in agent loop: {e}")
                logger.exception(e)
                raise e

        if not self.running:
            self.client.stop()

        return steps_completed, snapshots

    def summarize_history(self):
        """Generate a summary of the conversation history and replace the history with just the summary."""
        if self.display_config["quiet_mode"]:
            logger.debug(f"[Agent] Generating conversation summary...")
        else:
            logger.info(f"[Agent] Generating conversation summary...")

        # Get a new screenshot for the summary
        screenshot = self.client.get_screenshot()
        screenshot_b64 = get_screenshot_base64(screenshot, upscale=2)

        # Create messages for the summarization request - pass the entire conversation history
        messages = copy.deepcopy(self.message_history)

        if len(messages) >= 3:
            if (
                messages[-1]["role"] == "user"
                and isinstance(messages[-1]["content"], list)
                and messages[-1]["content"]
            ):
                messages[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}

            if (
                len(messages) >= 5
                and messages[-3]["role"] == "user"
                and isinstance(messages[-3]["content"], list)
                and messages[-3]["content"]
            ):
                messages[-3]["content"][-1]["cache_control"] = {"type": "ephemeral"}

        messages += [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": self.SUMMARY_PROMPT,
                    }
                ],
            }
        ]

        # Get summary from Claude
        response = self.anthropic.messages.create(
            model=MODEL_NAME,
            max_tokens=MAX_TOKENS,
            system=self.SYSTEM_PROMPT,
            messages=messages,
            temperature=TEMPERATURE,
        )

        # Extract the summary text
        summary_text = " ".join(
            [block.text for block in response.content if block.type == "text"]
        )

        # Log the summary - use info level even in quiet mode as it's important
        logger.info(f"[Claude Summary] Game Progress Summary:")
        logger.info(f"{summary_text}")

        # Replace message history with just the summary
        self.message_history = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"CONVERSATION HISTORY SUMMARY (representing {self.max_history} previous messages): {summary_text}",
                    },
                    {
                        "type": "text",
                        "text": "\n\nCurrent game screenshot for reference:",
                    },
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": screenshot_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": "You were just asked to summarize your playthrough so far, which is the summary you see above. You may now continue playing by selecting your next action.",
                    },
                ],
            }
        ]

        if self.display_config["quiet_mode"]:
            logger.debug(f"[Agent] Message history condensed into summary.")
        else:
            logger.info(f"[Agent] Message history condensed into summary.")

    def stop(self):
        """Stop the agent."""
        self.running = False
        self.client.stop()


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description="Run a Pokemon Game Server Agent")
    parser.add_argument(
        "--snapshot-id", type=str, required=True, help="Morph snapshot ID to run"
    )
    parser.add_argument(
        "--api-key", type=str, help="Morph API key (defaults to MORPH_API_KEY env var)"
    )
    parser.add_argument(
        "--steps", type=int, default=10, help="Number of steps to run (default: 10)"
    )
    parser.add_argument(
        "--max-history",
        type=int,
        default=30,
        help="Maximum history size before summarizing (default: 30)",
    )
    
    # Add parent snapshot tracking option
    parser.add_argument(
        "--parent-snapshot-id",
        type=str,
        help="Parent snapshot ID for lineage tracking (defaults to the starting snapshot-id)"
    )
    parser.add_argument(
        "--dashboard-run-id",
        type=str,
        help="Dashboard run ID for grouping snapshots (defaults to parent-snapshot-id)"
    )
    parser.add_argument(
        "--snapshot-prefix",
        type=str,
        default="pokemon",
        help="Prefix for snapshot names (default: 'pokemon')"
    )

    # Add verbosity and display options
    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="Increase output verbosity (can be used multiple times, e.g. -vv)",
    )
    parser.add_argument(
        "--show-game-state",
        action="store_true",
        help="Show full game state information in the logs",
    )
    parser.add_argument(
        "--show-collision-map",
        action="store_true",
        help="Show collision map in the logs",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        help="Path to log file. If not provided, logs will only go to stderr",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Only show Claude's thoughts and actions, minimal logging",
    )
    parser.add_argument(
        "--no-browser", 
        action="store_true",
        help="Suppress auto-opening the browser to display the game",
    )
    return parser.parse_args()


def main():
    args = parse_arguments()

    # Configure logging based on command line arguments
    log_handlers = []

    # Set up console handler with formatting
    console_handler = logging.StreamHandler()
    if args.quiet:
        console_format = "%(message)s"  # Minimal format for quiet mode
    else:
        console_format = "%(asctime)s - %(levelname)s - %(message)s"

    console_handler.setFormatter(logging.Formatter(console_format))
    log_handlers.append(console_handler)

    # Add file handler if log file specified
    if args.log_file:
        file_handler = logging.FileHandler(args.log_file)
        # Full detailed format for log files
        file_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        file_handler.setFormatter(logging.Formatter(file_format))
        log_handlers.append(file_handler)

    # Set log level based on verbosity
    if args.quiet:
        log_level = logging.WARNING
    elif args.verbose == 0:
        log_level = logging.INFO
    elif args.verbose == 1:
        log_level = logging.DEBUG
    else:  # args.verbose >= 2
        log_level = logging.DEBUG  # Maximum verbosity

    # Configure the root logger
    logging.basicConfig(level=log_level, handlers=log_handlers, force=True)

    # Create a rich console for nice output
    console = Console()

    console.print(
        f"Starting Pokemon Game Server Agent from snapshot {args.snapshot_id}"
    )
    console.print(
        f"Will run for {args.steps} steps with max history of {args.max_history}"
    )
    
    # Set parent snapshot ID (if not provided, use the starting snapshot as parent)
    parent_snapshot_id = args.parent_snapshot_id or args.snapshot_id
    console.print(f"Parent snapshot ID for lineage tracking: {parent_snapshot_id}")
    
    if not args.quiet:
        console.print(
            f"Log level: {'QUIET' if args.quiet else logging.getLevelName(log_level)}"
        )
        if args.show_game_state:
            console.print("Game state display: Enabled")
        if args.show_collision_map:
            console.print("Collision map display: Enabled")
        if args.log_file:
            console.print(f"Logging to file: {args.log_file}")
    console.print("=" * 50)

    # Create the MorphCloud client
    morph_client = MorphCloudClient(api_key=args.api_key)

    # Start instance from snapshot
    console.print("Starting instance from snapshot...")
    instance = morph_client.instances.start(
        snapshot_id=args.snapshot_id, ttl_seconds=60 * 60 * 24  # 24 hours
    )

    # Wait for instance to be ready
    console.print("Waiting for instance to be ready...")
    instance.wait_until_ready()

    # Get the instance URL
    instance_url = next(
        service.url
        for service in instance.networking.http_services
        if service.name == "web"
    )

    remote_desktop_url = next(
        service.url
        for service in instance.networking.http_services
        if service.name == "novnc"
    )

    novnc_url = f"{remote_desktop_url}/vnc_lite.html"
    console.print(f"Pokemon remote desktop available at: {novnc_url}")

    # Open the NoVNC URL automatically in the default browser if not suppressed
    if not args.no_browser:
        webbrowser.open(novnc_url)
    else:
        console.print("Browser auto-open suppressed. Use the URL above to view the game.")
        
    # Create a "game display" configuration object to pass to the agent
    display_config = {
        "show_game_state": args.show_game_state or args.verbose > 0,
        "show_collision_map": args.show_collision_map or args.verbose > 1,
        "quiet_mode": args.quiet,
    }

    # Run agent with the instance URL
    console.print("Initializing agent...")
    try:
        agent = PokemonAgent(
            server_host=instance_url,
            server_port=None,  # Not needed since URL already includes the port
            max_history=args.max_history,
            display_config=display_config,
            morph_client=morph_client,  # Pass the client for snapshot creation
            parent_snapshot_id=parent_snapshot_id,  # Pass the parent snapshot ID
            dashboard_run_id=args.dashboard_run_id,  # Pass the dashboard run ID
        )

        console.print("✅ Agent initialized successfully!")
        console.print("=" * 50)

        # Run the agent
        console.print(f"Starting agent loop for {args.steps} steps...")
        steps_completed, snapshots = agent.run(
            num_steps=args.steps,
            instance_id=instance.id,
            snapshot_name_prefix=args.snapshot_prefix
        )

        console.print("=" * 50)
        console.print(f"✅ Agent completed {steps_completed} steps")
        
        # Display a summary of created snapshots
        if snapshots:
            console.print(f"\nCreated {len(snapshots)} snapshots:")
            for snapshot in snapshots:
                console.print(f"  - Step {snapshot['step']}: {snapshot['snapshot_id']} ({snapshot['name']})")

    except ConnectionError as e:
        console.print(f"❌ Connection error: {e}")
        console.print(f"Make sure the server is running on the instance")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("Received keyboard interrupt, stopping agent")
    except Exception as e:
        console.print(f"❌ Error: {e}")
        sys.exit(1)
    finally:
        if "agent" in locals():
            agent.stop()

        # Stop the Morph instance
        console.print("Stopping Morph instance...")
        instance.stop()


if __name__ == "__main__":
    main()
