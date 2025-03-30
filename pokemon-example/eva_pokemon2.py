import asyncio
import argparse
import base64
import copy
import io
import json
import logging
from typing import Dict, Any, List, Optional, Callable, Sequence
from contextlib import AsyncExitStack
from datetime import datetime
from PIL import Image

from anthropic import Anthropic

# Import from the main E.V.A. framework
from eva import (
    Instance, VerificationResult, VerifiedTask, Agent, run, 
    MorphInstance, log, LogLevel
)


class PokemonInstance(Instance[Dict[str, Any], Dict[str, Any]]):
    """Instance implementation for Pokemon game state."""
    
    def __init__(self, state: Dict[str, Any]):
        super().__init__(state)
    
    def snapshot(self) -> Dict[str, Any]:
        """Create a serializable snapshot of the Pokemon game state."""
        snapshot_data = {
            "timestamp": str(datetime.now()),
            "game_state": self.state.get("game_state", {}),
            "screenshot": self.state.get("screenshot", ""),
            "valid_moves": self.state.get("valid_moves", []),
            "last_action": self.state.get("last_action", "")
        }
        return snapshot_data


class PokemonVerifiedTask(VerifiedTask[Dict[str, Any], str, bool, Dict[str, Any]]):
    """A task for a Pokemon game goal verified by checking game state."""
    
    @staticmethod
    def create(
        instruction: str,
        snapshot_id: str,
        verification_function: Callable[[Dict[str, Any]], bool],
        verification_message: str,
        metadata: Optional[Dict[str, str]] = None
    ) -> 'PokemonVerifiedTask':
        """
        Create a Pokemon verified task.
        
        Args:
            instruction: The goal to accomplish in Pokemon
            snapshot_id: The MorphCloud snapshot ID to start from
            verification_function: Function that determines if the goal was achieved
            verification_message: Message explaining what constitutes success
            metadata: Optional metadata for the task
            
        Returns:
            A PokemonVerifiedTask instance
        """
        log(LogLevel.INFO, f"Creating Pokemon task: {instruction}")
        log(LogLevel.DEBUG, f"  Snapshot ID: {snapshot_id}")
        
        def pokemon_verifier(state: Instance[Dict[str, Any], Dict[str, Any]], 
                          actions: Sequence[str]) -> VerificationResult[bool]:
            log(LogLevel.INFO, f"Verifying Pokemon task: {instruction}")
            
            # Extract game state from the Instance
            game_state = state.state.get("game_state", {})
            log(LogLevel.INFO, f"Game state type: {type(game_state)}")
            log(LogLevel.INFO, f"Game state preview: {str(game_state)[:100]}...")
            
            # Check if the goal is achieved using the verification function
            try:
                success = verification_function(game_state)
                
                if success:
                    log(LogLevel.SUCCESS, f"Goal achieved: {instruction}")
                    return VerificationResult(
                        value=True,
                        success=True,
                        message=f"Goal achieved: {instruction}",
                        details={
                            "game_state": game_state,
                            "actions_taken": len(actions)
                        }
                    )
                else:
                    log(LogLevel.INFO, f"Goal not yet achieved: {instruction}")
                    return VerificationResult(
                        value=False,
                        success=False,
                        message=f"Goal not yet achieved: {instruction}",
                        details={
                            "game_state": game_state,
                            "verification_message": verification_message
                        }
                    )
            except Exception as e:
                log(LogLevel.ERROR, f"Error in verification: {str(e)}")
                return VerificationResult(
                    value=False,
                    success=False,
                    message=f"Verification error: {str(e)}",
                    details={"error": str(e)}
                )
            
        return PokemonVerifiedTask(
            instruction=instruction,
            snapshot_id=snapshot_id,
            verifier=pokemon_verifier,
            metadata=metadata or {}
        )


class PokemonMCPHandler:
    """Handles communication with the MCP server for Pokemon game."""
    
    def __init__(self, server_url: str):
        """
        Initialize the MCP handler.
        
        Args:
            server_url: URL of the MCP server SSE endpoint
        """
        self.server_url = server_url
        self.exit_stack = AsyncExitStack()
        self.session = None
        self.streams = None
        
    async def connect(self):
        """Connect to the MCP server."""
        from mcp import ClientSession
        from mcp.client.sse import sse_client
        
        log(LogLevel.INFO, f"Connecting to MCP server at {self.server_url}...")
        
        try:
            # Connect to the SSE endpoint
            self.streams = await self.exit_stack.enter_async_context(
                sse_client(self.server_url)
            )
            self.session = await self.exit_stack.enter_async_context(
                ClientSession(self.streams[0], self.streams[1])
            )
            
            await self.session.initialize()
            
            # List available tools and store them
            response = await self.session.list_tools()
            self.tools = response.tools
            log(LogLevel.INFO, f"Connected to server with tools: {[tool.name for tool in self.tools]}")
            return True
        except Exception as e:
            log(LogLevel.ERROR, f"Failed to connect to MCP server: {str(e)}")
            return False

    def get_claude_tools(self):
        """Convert MCP tools to Claude-compatible format."""
        if not hasattr(self, 'tools') or not self.tools:
            log(LogLevel.WARNING, "No tools available from MCP server")
            return []
            
        claude_tools = []
        for tool in self.tools:
            # Convert MCP tool definition to Claude format
            claude_tool = {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema if hasattr(tool, 'inputSchema') else {}
            }
            
            log(LogLevel.DEBUG, f"Converted tool: {tool.name}")
            claude_tools.append(claude_tool)
        
        log(LogLevel.INFO, f"Prepared {len(claude_tools)} tools for Claude")
        return claude_tools

    async def call_tool_with_extras(self, tool_name, tool_input, include_state=True, include_screenshot=True):
        """Call a tool and get state and screenshot in a more efficient way."""
        log(LogLevel.INFO, f"Calling tool with extras: {tool_name}, include_state={include_state}, include_screenshot={include_screenshot}")
        
        # Call the primary tool
        log(LogLevel.INFO, f"Calling primary tool: {tool_name}")
        if not self.session:
            raise ValueError("Not connected to MCP server")
        
        primary_result = await self.session.call_tool(tool_name, tool_input)
        
        log(LogLevel.INFO, f"Received primary tool result with {len(primary_result.content)} content items")
        
        # Parse the primary result manually to check if it already contains what we need
        has_state = False
        has_screenshot = False
        
        for content_item in primary_result.content:
            if content_item.type == 'text':
                try:
                    parsed_json = json.loads(content_item.text)
                    if "game_state" in parsed_json:
                        has_state = True
                    if "screenshot" in parsed_json:
                        has_screenshot = True
                except json.JSONDecodeError:
                    pass
        
        log(LogLevel.INFO, f"Primary result analysis: has_state={has_state}, has_screenshot={has_screenshot}")
        
        result_content = self._parse_result(primary_result)
        
        # Get game state if needed and not already included
        if include_state and not has_state:
            log(LogLevel.INFO, "Getting game state")
            state_result = await self.session.call_tool("get_game_state", {})
            state_content = self._parse_result(state_result)
            result_content.update(state_content)
            
            log(LogLevel.INFO, "Added game state to result")
        
        # Get screenshot if needed and not already included
        if include_screenshot and not has_screenshot:
            log(LogLevel.INFO, "Getting screenshot")
            screenshot_result = await self.session.call_tool("get_screenshot", {})
            
            log(LogLevel.INFO, f"Received screenshot result with {len(screenshot_result.content)} content items")
            
            screenshot_content = self._parse_result(screenshot_result)
            result_content.update(screenshot_content)
            
            log(LogLevel.INFO, "Added screenshot to result")
        
        log(LogLevel.INFO, f"Tool with extras result has keys: {list(result_content.keys())}")
        return result_content

    async def get_game_state(self) -> Dict[str, Any]:
        """Get the current game state."""
        if not self.session:
            raise ValueError("Not connected to MCP server")
        
        response = await self.session.call_tool("get_game_state", {})
        return self._parse_result(response)

    async def get_screenshot(self) -> Dict[str, Any]:
        """Get the current screenshot."""
        if not self.session:
            raise ValueError("Not connected to MCP server")
        
        try:
            log(LogLevel.INFO, "Requesting screenshot from MCP server")
            response = await self.session.call_tool("get_screenshot", {})
            log(LogLevel.SUCCESS, "Received response from get_screenshot call")
            
            result = self._parse_result(response)
            
            # Process the screenshot
            if "screenshot" in result:
                log(LogLevel.INFO, f"Screenshot found in result, type: {type(result['screenshot'])}")
                if isinstance(result['screenshot'], str):
                    log(LogLevel.INFO, f"Screenshot string length: {len(result['screenshot'])}")
                    # Log the start and end of the string
                    if len(result['screenshot']) > 20:
                        start = result['screenshot'][:10]
                        end = result['screenshot'][-10:]
                        log(LogLevel.INFO, f"Screenshot starts with: {start}... and ends with: ...{end}")
                    
                result["screenshot"] = self.process_screenshot_data(result["screenshot"])
                log(LogLevel.INFO, f"After processing, screenshot type: {type(result['screenshot'])}, length: {len(result['screenshot']) if isinstance(result['screenshot'], str) else 'N/A'}")
            else:
                log(LogLevel.WARNING, "No screenshot field in response")
                
            return result
        except Exception as e:
            log(LogLevel.ERROR, f"Error getting screenshot: {e}")
            import traceback
            log(LogLevel.ERROR, f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}

    def process_screenshot_data(self, data):
        """Process screenshot data from MCP server."""
        log(LogLevel.INFO, f"Processing screenshot data of type: {type(data)}")
        
        # For string data (expected to be base64)
        if isinstance(data, str):
            log(LogLevel.INFO, f"String data length: {len(data)}")
            
            # Fix the f-string format
            if len(data) > 100:  # Make sure it's substantial
                log(LogLevel.SUCCESS, f"Returning base64 string directly (length: {len(data)})")
                return data
            else:
                log(LogLevel.WARNING, f"String too short to be valid base64: {len(data)} chars")
                # Log the actual content if it's very short
                if len(data) < 50:
                    log(LogLevel.DEBUG, f"Short string content: '{data}'")
        else:
            log(LogLevel.WARNING, f"Unexpected data type: {type(data)}")
        
        # If we got here, just return empty
        log(LogLevel.WARNING, "Screenshot data isn't usable, returning empty")
        return ""

    async def execute_action(self, action: str) -> Dict[str, Any]:
        """Execute a game action."""
        if not self.session:
            raise ValueError("Not connected to MCP server")
        else:
            log(LogLevel.INFO, f"mcp_url: {self.server_url}")
            log(LogLevel.INFO, f"action: {action}")

        parts = action.split(":", 1)
    
        if len(parts) != 2:
            raise ValueError("Invalid action string format. Expected 'tool_name:json_data'")
        
        tool_name = parts[0]
        tool_input_json = parts[1]
        
        log(LogLevel.INFO, f"calling tool against mcp session: {tool_name}: {tool_input_json}")
        
        try:
            tool_input = json.loads(tool_input_json)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON in the action string")

        response = await self.session.call_tool(tool_name, tool_input)
            
        result = self._parse_result(response)
        # log(LogLevel.INFO, f"TOOL RESULT: {json.dumps(result, indent=2)}")
        return result
    
    def _parse_result(self, response) -> Dict[str, Any]:
        """Parse the response from MCP into a usable dictionary."""
        result = {}
        
        log(LogLevel.INFO, f"Parsing response with {len(response.content)} content items")
        
        for i, content_item in enumerate(response.content):
            log(LogLevel.DEBUG, f"Content item {i} type: {content_item.type}")
            
            if content_item.type == 'text':
                # Log the first 100 chars of the text
                preview = content_item.text[:100] + "..." if len(content_item.text) > 100 else content_item.text
                log(LogLevel.DEBUG, f"Text content preview: {preview}")
                
                try:
                    parsed_json = json.loads(content_item.text)
                    # Make sure parsed_json is actually a dict before trying to access keys
                    if isinstance(parsed_json, dict):
                        log(LogLevel.DEBUG, f"Successfully parsed as JSON with keys: {list(parsed_json.keys())}")
                        
                        # Check for screenshot in the parsed JSON
                        if "screenshot" in parsed_json:
                            s_data = parsed_json["screenshot"]
                            s_type = type(s_data)
                            s_len = len(s_data) if isinstance(s_data, (str, bytes, bytearray)) else "N/A"
                            log(LogLevel.INFO, f"Found screenshot in JSON: type={s_type}, length={s_len}")
                        
                        result.update(parsed_json)
                    else:
                        log(LogLevel.WARNING, f"Parsed JSON is not a dictionary but a {type(parsed_json).__name__}")
                        log(LogLevel.INFO, f"{parsed_json}")
                        result["parsed_content"] = parsed_json
                except json.JSONDecodeError:
                    log(LogLevel.INFO, "Content is not valid JSON, checking if it's a game state string")
                    
                    # Check if this looks like the formatted game state string
                    if "Player:" in content_item.text and "Badges:" in content_item.text:
                        log(LogLevel.INFO, "Detected formatted game state string")
                        result["game_state"] = content_item.text
                    else:
                        log(LogLevel.WARNING, "Content is not valid JSON or game state, using as raw text")
                        result["text"] = content_item.text
        
        log(LogLevel.INFO, f"Parsed result has keys: {list(result.keys())}")
        return result

    async def cleanup(self):
        """Clean up resources."""
        if self.exit_stack:
            await self.exit_stack.aclose()


class PokemonAgent(Agent[Dict[str, Any], str, bool, Dict[str, Any]]):
    """An agent that plays Pokemon using the Claude API."""
    
    def __init__(self, mcp_handler: PokemonMCPHandler, model_name="claude-3-7-sonnet-latest", max_tokens=1000):
        """
        Initialize the Pokemon agent.
        
        Args:
            mcp_handler: Handler for MCP communication
            model_name: Claude model to use
            max_tokens: Maximum tokens to generate
        """
        super().__init__()
        self.mcp_handler = mcp_handler
        self.anthropic = Anthropic()
        self.model_name = model_name
        self.max_tokens = max_tokens
        self.temperature = 0.7
        self.message_history = []
        self.objective = None  # Store the objective here
        self.system_prompt = """You are playing Pokemon Red. You can see the game screen and control the game by executing emulator commands. Before each action, explain your reasoning briefly, then use the available actions to control the game"""

    def set_objective(self, objective: str):
        """Set the agent's current objective."""
        log(LogLevel.INFO, f"Setting agent objective: {objective}")
        self.objective = objective

    async def initialize_state(self, morph_instance: 'MorphInstance') -> PokemonInstance:
        """Initialize the state from a MorphCloud instance."""
        log(LogLevel.INFO, "Initializing Pokemon agent state")
        
        # This morph_instance is unused in this implementation because we use MCP directly
        # but we keep it to maintain compatibility with the EVA framework
        
        # Get initial game state
        initial_state = {
            "game_state": {},
            "screenshot": "",
            "valid_moves": [],
            "last_action": ""
        }
        
        # Add a starting message to the history
        initial_message = f"Your current objective is: {self.objective}\n\nYou may now begin playing Pokemon."
    
        self.message_history = [{"role": "user", "content": initial_message}]
        
        return PokemonInstance(initial_state)

    def _parse_tool_result(self, result):
        """Parse tool result into a list of content items."""
        content = []
        
        log(LogLevel.INFO, f"Parsing tool result with {len(result.content) if hasattr(result, 'content') else 0} content items")
        
        # The result.content is a list of Content objects
        for content_item in result.content:
            if content_item.type == 'text':
                try:
                    # Try to parse as JSON
                    parsed_json = json.loads(content_item.text)
                    
                    # Extract screenshot if available
                    if "screenshot" in parsed_json:
                        log(LogLevel.INFO, "Found screenshot in tool result")
                        
                        screenshot_data = parsed_json["screenshot"]
                        if screenshot_data:
                            # Process screenshot
                            processed_data = self.mcp_handler.process_screenshot_data(screenshot_data)
                            
                            if processed_data:
                                log(LogLevel.SUCCESS, "Valid screenshot processed")
                                
                                # Add the text and image
                                content.append({
                                    "type": "text",
                                    "text": "\nHere is a screenshot of the screen:"
                                })
                                
                                content.append({
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": processed_data,
                                    },
                                })
                                
                                log(LogLevel.INFO, "Added screenshot to content")
                        else:
                            log(LogLevel.INFO, "Empty screenshot data")
                    
                    # Extract game state if available
                    if "game_state" in parsed_json:
                        game_state_text = f"\nGame state information:\n{parsed_json['game_state']}"
                        content.append({
                            "type": "text",
                            "text": game_state_text
                        })
                        
                        log(LogLevel.INFO, "Added game state to content")
                        
                        # Add collision map if available
                        if "collision_map" in parsed_json and parsed_json["collision_map"]:
                            collision_map_text = f"\nCollision Map:\n{parsed_json['collision_map']}"
                            content.append({
                                "type": "text",
                                "text": collision_map_text
                            })
                            
                            log(LogLevel.INFO, "Added collision map to content")
                        
                        # Add valid moves if available
                        if "valid_moves" in parsed_json and parsed_json["valid_moves"]:
                            valid_moves_text = f"\nValid Moves:\n{parsed_json['valid_moves']}"
                            content.append({
                                "type": "text",
                                "text": valid_moves_text
                            })
                            
                            log(LogLevel.INFO, "Added valid moves to content")
                    
                    # For button press actions or navigation
                    if "result" in parsed_json:
                        result_text = parsed_json["result"]
                        content.append({
                            "type": "text", 
                            "text": result_text
                        })
                        
                        log(LogLevel.INFO, f"Added result to content: {result_text}")
                    
                    # For navigation status
                    if "status" in parsed_json:
                        status_text = f"Navigation status: {parsed_json['status']}"
                        content.append({
                            "type": "text", 
                            "text": status_text
                        })
                        
                        log(LogLevel.INFO, f"Added navigation status: {parsed_json['status']}")
                    
                    # For navigation path
                    if "path" in parsed_json and parsed_json["path"]:
                        path_steps = len(parsed_json['path'])
                        path_text = f"Navigation path: {path_steps} steps"
                        content.append({
                            "type": "text", 
                            "text": path_text
                        })
                        
                        log(LogLevel.INFO, f"Added navigation path: {path_steps} steps")
                            
                    # Handle errors
                    if "error" in parsed_json:
                        error_text = f"Error: {parsed_json['error']}"
                        content.append({
                            "type": "text", 
                            "text": error_text
                        })
                        
                        log(LogLevel.WARNING, f"Added error: {parsed_json['error']}")
                        
                except json.JSONDecodeError:
                    # If it's not valid JSON, just use the text directly
                    preview = content_item.text[:100] + "..." if len(content_item.text) > 100 else content_item.text
                    log(LogLevel.INFO, f"Non-JSON content: {preview}")
                    
                    content.append({
                        "type": "text",
                        "text": content_item.text
                    })
                    
                    log(LogLevel.INFO, f"Added raw text to content (length: {len(content_item.text)})")
        
        log(LogLevel.INFO, f"Parsed tool result into {len(content)} content items")
        return content

    
    async def _update_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Update the state with the latest game information."""
        # Get game state
        game_state = await self.mcp_handler.get_game_state()
        
        # Get screenshot
        screenshot_result = await self.mcp_handler.get_screenshot()
        
        # Update the state
        new_state = copy.deepcopy(state)
        new_state["game_state"] = game_state.get("game_state", {})
        new_state["screenshot"] = screenshot_result.get("screenshot", "")
        new_state["valid_moves"] = game_state.get("valid_moves", [])
        
        return new_state
    
    
    async def run_step(self, state: Instance[Dict[str, Any], Dict[str, Any]]) -> str:
        """Determine the next action using Claude."""
        log(LogLevel.INFO, "Determining next action with Claude")
        
        # Update state with latest game information
        updated_state = await self._update_state(state.state)
        
        # Create user message with game state and screenshot
        user_content = []
        
        # Add text description
        user_content.append({
            "type": "text",
            "text": "Here is the current game state. Please decide your next action."
        })
        
        # Add screenshot if available
        if updated_state["screenshot"]:
            user_content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": updated_state["screenshot"]
                }
            })
        
        # Add game state info if available
        if updated_state["game_state"]:
            game_state_text = f"\nGame state information:\n{json.dumps(updated_state['game_state'], indent=2)}"
            user_content.append({"type": "text", "text": game_state_text})
        
        # Add valid moves if available
        if updated_state["valid_moves"]:
            valid_moves_text = f"\nValid moves:\n{', '.join(updated_state['valid_moves'])}"
            user_content.append({"type": "text", "text": valid_moves_text})
        
        # Add the message to history
        self.message_history.append({"role": "user", "content": user_content})
        
        # Get Claude's response
        log(LogLevel.INFO, "Calling Claude API")
        response = self.anthropic.messages.create(
            model=self.model_name,
            max_tokens=self.max_tokens,
            system=self.system_prompt,
            messages=self.message_history,
            tools=self.mcp_handler.get_claude_tools(),
            temperature=self.temperature
        )
        
        log(LogLevel.INFO, f"Received Claude response with {len(response.content)} content blocks")
        
        # Log Claude's entire reasoning for better observability
        claude_response_text = " ".join([block.text for block in response.content if block.type == "text"])
        log(LogLevel.INFO, f"AGENT REASONING: {claude_response_text}")
        
        # Extract tool calls
        tool_calls = [
            block for block in response.content if block.type == "tool_use"
        ]
        
        log(LogLevel.INFO, f"Extracted {len(tool_calls)} tool calls")
        
        # Add Claude's response to history with all properties preserved
        assistant_content = []
        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                # Preserve ALL properties including ID
                assistant_content.append({"type": "tool_use", **dict(block)})
                log(LogLevel.INFO, f"AGENT TOOL CALL: {block.name} with input {json.dumps(block.input, indent=2)}")
        
        self.message_history.append({"role": "assistant", "content": assistant_content})

        # Process tool calls
        if tool_calls:
            # Extract the first tool call for action
            tool_call = tool_calls[0]
            tool_name = tool_call.name
            tool_input = tool_call.input
            
            log(LogLevel.INFO, f"ACTION SELECTED: {tool_name} with input: {tool_input}")
            
            # Convert to action string format
            action = f"{tool_name}:{json.dumps(tool_input)}"
            
            return action
        
        # If no tool call found, extract from text as fallback
        text_content = " ".join([block.text for block in response.content if block.type == "text"])
        
        # Look for button press patterns in the text
        button_names = ["a", "b", "start", "select", "up", "down", "left", "right"]
        for button in button_names:
            if f"press {button}" in text_content.lower():
                log(LogLevel.INFO, f"FALLBACK ACTION: Extracted button press '{button}' from text")
                return f"button:{button}"
        
        # Default to pressing A if no action found
        log(LogLevel.WARNING, "No action found in Claude's response, defaulting to 'A'")
        return "button:a"

    
    def _extract_action_from_response(self, response) -> str:
        """Extract the action from Claude's response."""
        # Look for tool calls
        for block in response.content:
            if block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input
                
                if tool_name == "press_button":
                    return f"button:{tool_input['button']}"
                elif tool_name == "navigate_to":
                    return f"navigate:{tool_input['location']}"
        
        # If no tool call found, extract from text
        text_content = " ".join([block.text for block in response.content if block.type == "text"])
        
        # Look for button press patterns in the text
        button_names = ["a", "b", "start", "select", "up", "down", "left", "right"]
        for button in button_names:
            if f"press {button}" in text_content.lower():
                return f"button:{button}"
        
        # Default to pressing A if no action found
        log(LogLevel.WARNING, "No action found in Claude's response, defaulting to 'A'")
        return "button:a"
    
    async def apply_action(self, state: Dict[str, Any], action: str) -> Dict[str, Any]:
        """Apply an action and return the new state."""
        log(LogLevel.INFO, f"Executing action: {action}")
        
        # Execute the action
        action_result = await self.mcp_handler.execute_action(action)
        
        # Create a new state with the result
        new_state = copy.deepcopy(state)
        new_state["last_action"] = action
        
        # Update the state with fresh game information
        new_state = await self._update_state(new_state)
        
        # Create tool results from the action
        tool_results = []
        
        # Extract most recent assistant message to get tool ID
        if self.message_history and self.message_history[-1]["role"] == "assistant":
            assistant_content = self.message_history[-1]["content"]
            tool_use_items = [item for item in assistant_content if isinstance(item, dict) and item.get("type") == "tool_use"]
            
            if tool_use_items:
                tool_use_id = tool_use_items[0].get("id")
                
                if tool_use_id:
                    # Create result content
                    result_content = []
                    
                    # Add text result
                    result_text = f"Action '{action}' executed."
                    if "result" in action_result:
                        result_text += f"\nResult: {action_result['result']}"
                    
                    result_content.append({"type": "text", "text": result_text})
                    
                    # Add screenshot if available
                    if new_state["screenshot"]:
                        result_content.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": new_state["screenshot"]
                            }
                        })
                    
                    # Create a proper tool result
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": result_content
                    })
                    
                    # Log the tool result for observability
                    # log(LogLevel.INFO, f"TOOL RESULT: {action} executed with result: {json.dumps(action_result, indent=2, default=str)}")
                    
                    # Add the tool results to message history
                    self.message_history.append({"role": "user", "content": tool_results})
                    
                    log(LogLevel.INFO, f"Added tool result for action '{action}' with tool_use_id: {tool_use_id}")
        
        return new_state
    
    def summarize_history(self):
        """Summarize the conversation history to save context space."""
        # Create a summary prompt
        summary_prompt = """I need you to create a concise summary of our Pokemon gameplay so far. 
        This summary will replace the full conversation history to manage the context window.
        Include key events, your current Pokemon team, and your current objective."""
        
        # Add the prompt to history
        self.message_history.append({"role": "user", "content": summary_prompt})
        
        # Get the summary from Claude
        response = self.anthropic.messages.create(
            model=self.model_name,
            max_tokens=self.max_tokens,
            system=self.system_prompt,
            messages=self.message_history,
            temperature=0.7
        )
        
        # Extract the summary text
        summary_text = " ".join([block.text for block in response.content if block.type == "text"])
        
        log(LogLevel.INFO, f"HISTORY SUMMARY: {summary_text}")
        
        # Replace message history with just the summary
        self.message_history = [
            {"role": "user", "content": f"GAMEPLAY SUMMARY: {summary_text}\n\nPlease continue playing based on this summary."}
        ]


async def run_pokemon_example(snapshot_id=None):
    """Run a Pokemon Red game using the E.V.A. framework with a MorphVM-hosted MCP server."""
    log(LogLevel.INFO, "Starting Pokemon example with E.V.A. framework")
    
    # In a real scenario, you would use an actual snapshot ID
    POKEMON_MCP_SNAPSHOT_ID = snapshot_id
    
    # First, we need to start a MorphVM instance with the Pokemon MCP server
    log(LogLevel.INFO, f"Starting MorphVM instance from snapshot: {POKEMON_MCP_SNAPSHOT_ID}")
    morph_instance = MorphInstance(
        snapshot_id=POKEMON_MCP_SNAPSHOT_ID,
        metadata={"purpose": "pokemon_game_server"},
        ttl_seconds=7200  # 2-hour TTL
    )
    
    try:
        # The MCP server is running inside the MorphVM instance
        # We need to expose it as an HTTP service
        log(LogLevel.INFO, "Exposing MCP server HTTP service")
        
        mcp_url = morph_instance.instance.expose_http_service(
            name="mcp",
            port=8000  # Assuming MCP server runs on port 8000 inside the VM
        )
        
        log(LogLevel.SUCCESS, f"MCP server exposed at: {mcp_url}")
        
        # Now connect to the MCP service running on the MorphVM
        mcp_handler = PokemonMCPHandler(f"{mcp_url}/sse")  # Assuming /sse is the SSE endpoint
        connected = await mcp_handler.connect()
        
        if not connected:
            log(LogLevel.ERROR, "Failed to connect to MCP server on MorphVM")
            return
        
        def verify_player_names(game_state: Dict[str, Any]) -> bool:
            """Verify that player name is CLAUDE and rival name is WACLAUD."""
            if isinstance(game_state, str):
                log(LogLevel.INFO, "Checking player and rival names in string format")
                player_name = None
                rival_name = None
                
                # Parse the formatted game state string
                for line in game_state.split('\n'):
                    if line.startswith("Player:"):
                        player_name = line.replace("Player:", "").strip()
                        log(LogLevel.INFO, f"Found player name: {player_name}")
                    elif line.startswith("Rival:"):
                        rival_name = line.replace("Rival:", "").strip()
                        log(LogLevel.INFO, f"Found rival name: {rival_name}")
                        
                    # Once we have both names, we can check them
                    if player_name and rival_name:
                        # Check that names match the expected values
                        # Note: Handle "Not yet set" case
                        has_correct_names = (player_name == "CLAUDE" and rival_name == "WACLAUD")
                        log(LogLevel.INFO, f"Names correct: {has_correct_names}")
                        return has_correct_names
                
                # If we didn't find both names or they didn't match
                log(LogLevel.WARNING, f"Could not verify both names or names did not match requirements")
                return False
            else:
                log(LogLevel.ERROR, f"Unexpected game state type: {type(game_state)}")
                return False

        def verify_left_mount_moon(game_state: Dict[str, Any]) -> bool:
            """Verify that player has successfully left Mount Moon."""
            if isinstance(game_state, str):
                log(LogLevel.INFO, "Checking if player has left Mount Moon")
                
                # Parse the formatted game state string
                for line in game_state.split('\n'):
                    if line.startswith("Location:"):
                        location = line.replace("Location:", "").strip()
                        log(LogLevel.INFO, f"Current location: {location}")
                        
                        # Check if location indicates player has left Mount Moon
                        # Mount Moon locations are typically named "Mt. Moon" or variations
                        # Routes after Mount Moon are typically "Route 4" 
                        if "Route 4" in location:
                            log(LogLevel.SUCCESS, f"Player has left Mount Moon, now at {location}")
                            return True
                        elif "Cerulean" in location:
                            log(LogLevel.SUCCESS, f"Player has reached Cerulean City beyond Mount Moon")
                            return True
                        elif "Mt. Moon" in location or "Mount Moon" in location:
                            log(LogLevel.INFO, f"Player is still in Mount Moon")
                            return False
                
                log(LogLevel.WARNING, "Could not determine player location from game state")
                return False
            else:
                log(LogLevel.ERROR, f"Unexpected game state type: {type(game_state)}")
                return False

        # Create a verification function for beating the first gym
        def verify_beat_first_gym(game_state: Dict[str, Any]) -> bool:
            # Handle case where game_state is a string (which is the actual case based on get_state_from_memory)
            if isinstance(game_state, str):
                log(LogLevel.INFO, f"Game state is a string, parsing manually")
                # Look for the badges line in the formatted string
                for line in game_state.split('\n'):
                    if line.startswith("Badges:"):
                        badges_str = line.replace("Badges:", "").strip()
                        badges = [b.strip() for b in badges_str.split(',') if b.strip()]
                        log(LogLevel.INFO, f"Found badges: {badges}")
                        return "Boulder Badge" in badges
                
                log(LogLevel.WARNING, "Could not find badges information in game state")
                return False
            elif isinstance(game_state, dict):
                # If it's somehow a dictionary, use the original approach
                badges = game_state.get("badges", [])
                log(LogLevel.INFO, f"Current badges: {badges}")
                return "Boulder Badge" in badges
            else:
                log(LogLevel.ERROR, f"Unexpected game state type: {type(game_state)}")
                return False
        
        # Create a Pokemon task - note we're using the same snapshot ID
        # since our verification happens through the MCP API, not by starting a new VM
        
        # Task for naming characters
        
        task = PokemonVerifiedTask.create(
            instruction="Name your character CLAUDE and your rival WACLAUD",
            snapshot_id=POKEMON_MCP_SNAPSHOT_ID,
            verification_function=verify_player_names,
            verification_message="You need to set your character's name to CLAUDE and your rival's name to WACLAUD.",
            metadata={"game": "Pokemon Red", "objective": "naming"}
        )

        # Task for leaving Mount Moon
        mount_moon_task = PokemonVerifiedTask.create(
            instruction="Navigate through Mount Moon and exit to Route 4",
            snapshot_id=POKEMON_MCP_SNAPSHOT_ID,
            verification_function=verify_left_mount_moon,
            verification_message="You need to navigate through the Mount Moon cave system and exit to Route 4.",
            metadata={"game": "Pokemon Red", "objective": "mount_moon"}
        )

        brock_task = PokemonVerifiedTask.create(
            instruction="Defeat Brock and earn the Boulder Badge",
            snapshot_id=POKEMON_MCP_SNAPSHOT_ID,  # Using same snapshot since we're verifying through MCP
            verification_function=verify_beat_first_gym,
            verification_message="You need to defeat Brock at the Pewter City Gym to earn the Boulder Badge.",
            metadata={"game": "Pokemon Red"}
        )
        
        # Create a Pokemon agent
        agent = PokemonAgent(mcp_handler)
        
        # Run the agent
        log(LogLevel.INFO, "Running Pokemon agent")
        result, trajectory = await run(
            task=task,
            agent=agent,
            max_steps=200,  # Allow up to 50 steps to beat the gym
            verify_every_step=True
        )
        
        # Print the result
        log(LogLevel.INFO, "Pokemon example completed")
        log(LogLevel.INFO, f"Task success: {result.success}")
        log(LogLevel.INFO, f"Message: {result.message}")
        
        # Print a summary of key trajectory steps
        log(LogLevel.INFO, "\nKey gameplay moments:")
        for i, step in enumerate(trajectory.steps):
            if step.action and i % 5 == 0:  # Show every 5th action
                log(LogLevel.INFO, f"Step {i}: {step.action}")
        
        # Additional log for full trajectory
        log(LogLevel.INFO, "FULL GAMEPLAY TRAJECTORY:")
        for i, step in enumerate(trajectory.steps):
            if step.action:
                log(LogLevel.INFO, f"Step {i}: {step.action}")
    
    finally:
        # Clean up both the MCP handler and the MorphVM instance
        await mcp_handler.cleanup()
        morph_instance.stop()
        log(LogLevel.INFO, "Cleaned up resources")


# Entry point for running the example
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Run Pokemon agent with custom snapshot ID')
    parser.add_argument('--snapshot-id', type=str, help='Snapshot ID to use for the MorphVM instance')
    args = parser.parse_args()
    
    asyncio.run(run_pokemon_example(args.snapshot_id))

