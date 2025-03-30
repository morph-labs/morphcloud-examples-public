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

# Import from the main E.V.A. framework with JSONL logging
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
        log(LogLevel.INFO, f"Creating Pokemon task: {instruction}", 
            extra={"snapshot_id": snapshot_id, "verification_message": verification_message})
        
        def pokemon_verifier(state: Instance[Dict[str, Any], Dict[str, Any]], 
                          actions: Sequence[str]) -> VerificationResult[bool]:
            log(LogLevel.INFO, f"Verifying Pokemon task", 
                extra={"task": instruction, "action_count": len(actions)})
            
            # Extract game state from the Instance
            game_state = state.state.get("game_state", {})
            log(LogLevel.INFO, f"Game state summary", 
                extra={"game_state": game_state, "action_count": len(actions)})
            
            # Check if the goal is achieved using the verification function
            try:
                success = verification_function(game_state)
                
                if success:
                    log(LogLevel.SUCCESS, f"Goal achieved", 
                        extra={"task": instruction, "actions_taken": len(actions)})
                    return VerificationResult(
                        value=True,
                        success=True,
                        message=f"Goal achieved: {instruction}",
                        details={
                            "actions_taken": len(actions)
                        }
                    )
                else:
                    log(LogLevel.INFO, f"Goal not yet achieved", 
                        extra={"task": instruction, "verification_message": verification_message})
                    return VerificationResult(
                        value=False,
                        success=False,
                        message=f"Goal not yet achieved: {instruction}",
                        details={
                            "verification_message": verification_message
                        }
                    )
            except Exception as e:
                log(LogLevel.ERROR, f"Error in verification", 
                    extra={"error": str(e), "task": instruction})
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
        log(LogLevel.INFO, f"Created MCP handler", extra={"server_url": server_url})
        
    async def connect(self):
        """Connect to the MCP server."""
        from mcp import ClientSession
        from mcp.client.sse import sse_client
        
        log(LogLevel.INFO, f"Connecting to MCP server", extra={"url": self.server_url})
        
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
            tool_names = [tool.name for tool in self.tools]
            log(LogLevel.INFO, f"Connected to server", 
                extra={"tool_count": len(tool_names), "tools": tool_names})
            return True
        except Exception as e:
            log(LogLevel.ERROR, f"Failed to connect to MCP server", extra={"error": str(e)})
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
            
            claude_tools.append(claude_tool)
        
        log(LogLevel.DEBUG, f"Prepared Claude tools: {claude_tools}", 
            extra={"tool_count": len(claude_tools), "claude_tools": claude_tools})
        return claude_tools

    async def call_tool_with_extras(self, tool_name, tool_input, include_state=True, include_screenshot=True):
        """Call a tool and get state and screenshot in a more efficient way."""
        log(LogLevel.INFO, f"Calling tool with extras", 
            extra={"tool_name": tool_name, "include_state": include_state, "include_screenshot": include_screenshot})
        
        # Call the primary tool
        if not self.session:
            raise ValueError("Not connected to MCP server")
        
        primary_result = await self.session.call_tool(tool_name, tool_input)
        
        log(LogLevel.DEBUG, f"Received primary tool result", 
            extra={"content_items": len(primary_result.content)})
        
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
        
        log(LogLevel.DEBUG, f"Primary result analysis", 
            extra={"has_state": has_state, "has_screenshot": has_screenshot})
        
        result_content = self._parse_result(primary_result)
        
        # Get game state if needed and not already included
        if include_state and not has_state:
            log(LogLevel.DEBUG, "Getting game state")
            state_result = await self.session.call_tool("get_game_state", {})
            state_content = self._parse_result(state_result)
            result_content.update(state_content)
            
            log(LogLevel.DEBUG, "Added game state to result")
        
        # Get screenshot if needed and not already included
        if include_screenshot and not has_screenshot:
            log(LogLevel.DEBUG, "Getting screenshot")
            screenshot_result = await self.session.call_tool("get_screenshot", {})
            
            log(LogLevel.DEBUG, f"Received screenshot result", 
                extra={"content_items": len(screenshot_result.content)})
            
            screenshot_content = self._parse_result(screenshot_result)
            result_content.update(screenshot_content)
            
            log(LogLevel.DEBUG, "Added screenshot to result")
        
        log(LogLevel.DEBUG, f"Tool with extras result completed", 
            extra={"result_keys": list(result_content.keys())})
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
            log(LogLevel.DEBUG, "Requesting screenshot from MCP server")
            response = await self.session.call_tool("get_screenshot", {})
            log(LogLevel.DEBUG, "Received screenshot response")
            
            result = self._parse_result(response)
            
            # Process the screenshot
            if "screenshot" in result:
                log(LogLevel.DEBUG, f"Processing screenshot", 
                    extra={"screenshot_type": type(result['screenshot']).__name__})
                if isinstance(result['screenshot'], str):
                    log(LogLevel.DEBUG, f"Screenshot data summary", 
                        extra={"length": len(result['screenshot'])})
                    
                result["screenshot"] = self.process_screenshot_data(result["screenshot"])
                log(LogLevel.DEBUG, f"Screenshot processed", 
                    extra={"result_type": type(result['screenshot']).__name__})
            else:
                log(LogLevel.WARNING, "No screenshot field in response")
                
            return result
        except Exception as e:
            log(LogLevel.ERROR, f"Error getting screenshot", extra={"error": str(e)})
            import traceback
            log(LogLevel.ERROR, f"Error traceback", extra={"traceback": traceback.format_exc()})
            return {"error": str(e)}

    def process_screenshot_data(self, data):
        """Process screenshot data from MCP server."""
        log(LogLevel.DEBUG, f"Processing screenshot data", 
            extra={"data_type": type(data).__name__})
        
        # For string data (expected to be base64)
        if isinstance(data, str):
            log(LogLevel.DEBUG, f"Processing string data", extra={"length": len(data)})
            
            if len(data) > 100:  # Make sure it's substantial
                log(LogLevel.DEBUG, f"Valid base64 string found", extra={"length": len(data)})
                return data
            else:
                log(LogLevel.WARNING, f"String too short for valid base64", extra={"length": len(data)})
                # Log the actual content if it's very short
                if len(data) < 50:
                    log(LogLevel.DEBUG, f"Short string content", extra={"content": data})
        else:
            log(LogLevel.WARNING, f"Unexpected data type", extra={"type": type(data).__name__})
        
        # If we got here, just return empty
        log(LogLevel.WARNING, "Screenshot data isn't usable, returning empty")
        return ""

    async def execute_action(self, action: str) -> Dict[str, Any]:
        """Execute a game action."""
        if not self.session:
            raise ValueError("Not connected to MCP server")
        else:
            log(LogLevel.INFO, f"Executing action", 
                extra={"mcp_url": self.server_url, "action": action})

        parts = action.split(":", 1)
    
        if len(parts) != 2:
            raise ValueError("Invalid action string format. Expected 'tool_name:json_data'")
        
        tool_name = parts[0]
        tool_input_json = parts[1]
        
        log(LogLevel.INFO, f"Calling MCP tool", 
            extra={"tool": tool_name, "input_json": tool_input_json})
        
        try:
            tool_input = json.loads(tool_input_json)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON in the action string")

        response = await self.session.call_tool(tool_name, tool_input)
            
        result = self._parse_result(response)
        return result
    
    def _parse_result(self, response) -> Dict[str, Any]:
        """Parse the response from MCP into a usable dictionary."""
        result = {}
        
        log(LogLevel.DEBUG, f"Parsing MCP response", 
            extra={"content_items": len(response.content)})
        
        for i, content_item in enumerate(response.content):
            log(LogLevel.DEBUG, f"Processing content item", 
                extra={"index": i, "type": content_item.type})
            
            if content_item.type == 'text':
                try:
                    parsed_json = json.loads(content_item.text)
                    # Make sure parsed_json is actually a dict before trying to access keys
                    if isinstance(parsed_json, dict):
                        log(LogLevel.DEBUG, f"Parsed JSON content", 
                            extra={"keys": list(parsed_json.keys())})
                        
                        # Check for screenshot in the parsed JSON
                        if "screenshot" in parsed_json:
                            s_data = parsed_json["screenshot"]
                            s_type = type(s_data).__name__
                            s_len = len(s_data) if isinstance(s_data, (str, bytes, bytearray)) else "N/A"
                            log(LogLevel.DEBUG, f"Found screenshot in JSON", 
                                extra={"type": s_type, "length": s_len})
                        
                        result.update(parsed_json)
                    else:
                        log(LogLevel.WARNING, f"Parsed JSON is not a dictionary", 
                            extra={"type": type(parsed_json).__name__})
                        result["parsed_content"] = parsed_json
                except json.JSONDecodeError:
                    log(LogLevel.DEBUG, "Content is not valid JSON, checking if it's a game state string")
                    
                    # Check if this looks like the formatted game state string
                    if "Player:" in content_item.text and "Badges:" in content_item.text:
                        log(LogLevel.DEBUG, "Detected formatted game state string")
                        result["game_state"] = content_item.text
                    else:
                        log(LogLevel.WARNING, "Content is not valid JSON or game state, using as raw text")
                        result["text"] = content_item.text
        
        log(LogLevel.DEBUG, f"Parsed result summary", 
            extra={"keys": list(result.keys())})
        return result

    async def cleanup(self):
        """Clean up resources."""
        if self.exit_stack:
            await self.exit_stack.aclose()
            log(LogLevel.INFO, "MCP handler resources cleaned up")


class PokemonAgent(Agent[Dict[str, Any], str, bool, Dict[str, Any]]):
    """An agent that plays Pokemon using the Claude API."""
    
    def __init__(self, mcp_handler: PokemonMCPHandler, model_name="claude-3-7-sonnet-latest", max_tokens=1000, max_history=30, morph_instance=None):
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
        self.max_history = max_history
        self.morph_instance = morph_instance
        self.objective = None  # Store the objective here
        self.summary_prompt = """I need you to create a detailed summary of our conversation history up to this point. This summary will replace the full conversation history to manage the context window.

    Please include:
    1. Key game events and milestones you've reached
    2. Important decisions you've made
    3. Current objectives or goals you're working toward
    4. Your current location and Pokémon team status
    5. Any strategies or plans you've mentioned

    The summary should be comprehensive enough that you can continue gameplay without losing important context about what has happened so far."""

        self.system_prompt = """You are playing Pokemon Red. You can see the game screen and control the game by executing emulator commands: check your tools! for example, 'navigate_to' can help you move in the overworld. Before each action, explain your reasoning briefly, then use the available actions to control the game"""
        
        log(LogLevel.INFO, f"Initialized PokemonAgent", 
            extra={"model": model_name, "max_tokens": max_tokens})

    def set_objective(self, objective: str):
        """Set the agent's current objective."""
        log(LogLevel.INFO, f"Setting agent objective", extra={"objective": objective})
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
        log(LogLevel.INFO, "Initial state and message history created")
        
        return PokemonInstance(initial_state)
    
    async def _update_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Update the state with the latest game information."""
        # Get game state
        log(LogLevel.DEBUG, "Updating state with fresh game information")
        game_state = await self.mcp_handler.get_game_state()
        
        # Get screenshot
        screenshot_result = await self.mcp_handler.get_screenshot()
        
        # Update the state
        new_state = copy.deepcopy(state)
        new_state["game_state"] = game_state.get("game_state", {})
        new_state["screenshot"] = screenshot_result.get("screenshot", "")
        new_state["valid_moves"] = game_state.get("valid_moves", [])
        
        log(LogLevel.DEBUG, "State updated", 
            extra={"has_game_state": bool(new_state["game_state"]), 
                   "has_screenshot": bool(new_state["screenshot"]),
                   "valid_moves_count": len(new_state["valid_moves"])})
        
        return new_state
    
    
    async def run_step(self, state: Instance[Dict[str, Any], Dict[str, Any]]) -> str:
        """Determine the next action using Claude."""
        log(LogLevel.INFO, "Determining next action with Claude")
        
        # Check if we need to summarize the history
        if len(self.message_history) >= self.max_history:
            log(LogLevel.INFO, f"Message history size ({len(self.message_history)}) exceeds max_history ({self.max_history})")
            await self.summarize_history()
            log(LogLevel.INFO, f"Summarized! History size: {len(self.message_history)}")
        
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
            log(LogLevel.DEBUG, "Added screenshot to user message")
        
        # Add game state info if available
        if updated_state["game_state"]:
            game_state_text = f"\nGame state information:\n{json.dumps(updated_state['game_state'], indent=2)}"
            user_content.append({"type": "text", "text": game_state_text})
            log(LogLevel.DEBUG, "Added game state to user message")
        
        # Add valid moves if available
        if updated_state["valid_moves"]:
            valid_moves_text = f"\nValid moves:\n{', '.join(updated_state['valid_moves'])}"
            user_content.append({"type": "text", "text": valid_moves_text})
            log(LogLevel.DEBUG, "Added valid moves to user message")
        
        # Add the message to history
        self.message_history.append({"role": "user", "content": user_content})
        
        # Get action with retries if needed
        action, success = await self._retry_with_nudge(max_retries=3)
        
        if not success:
            log(LogLevel.ERROR, "Failed to get valid tool call after retries, using fallback action")
        
        return action
    
    async def _retry_with_nudge(self, max_retries=3):
        """Retry getting a tool call from Claude with nudges.
        
        Args:
            max_retries: Maximum number of retry attempts
            
        Returns:
            A tuple of (action, success) where action is the tool action string
            and success is a boolean indicating if a tool call was obtained
        """
        attempts = 0
        tool_calls = []
        
        while attempts < max_retries and not tool_calls:
            attempts += 1
            
            # If this is a retry, add a nudge message
            if attempts > 1:
                nudge_message = {
                    "role": "user", 
                    "content": f"Please make a decision and use one of the available tools to control the game. This is attempt {attempts} of {max_retries}."
                }
                self.message_history.append(nudge_message)
                log(LogLevel.WARNING, f"No tool calls found, adding nudge (attempt {attempts}/{max_retries})")
            
            # Create a copy of message history for cache control
            messages = copy.deepcopy(self.message_history)
            
            # Add cache control for older messages
            if len(messages) >= 3:
                if messages[-1]["role"] == "user" and isinstance(messages[-1]["content"], list) and messages[-1]["content"]:
                    messages[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}
                
                if len(messages) >= 5 and messages[-3]["role"] == "user" and isinstance(messages[-3]["content"], list) and messages[-3]["content"]:
                    messages[-3]["content"][-1]["cache_control"] = {"type": "ephemeral"}
            
            # Get Claude's response
            log(LogLevel.DEBUG, f"Calling Claude API (attempt {attempts}/{max_retries})", 
                extra={"model": self.model_name, "temperature": self.temperature})
            
            response = self.anthropic.messages.create(
                model=self.model_name,
                max_tokens=self.max_tokens,
                system=self.system_prompt,
                messages=messages,
                tools=self.mcp_handler.get_claude_tools(),
                temperature=self.temperature
            )
            
            # Extract tool calls
            tool_calls = [
                block for block in response.content if block.type == "tool_use"
            ]

            claude_text = " ".join([block.text for block in response.content if block.type == "text"])
            if claude_text:
                log(LogLevel.INFO, f"Claude response text", 
                    extra={"event_type": "claude_text", "text_content": claude_text})

            
            log(LogLevel.DEBUG, f"Tool calls extracted", 
                extra={"tool_call_count": len(tool_calls), "attempt": attempts})
            
            # Add Claude's response to history with all properties preserved
            assistant_content = []
            for block in response.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    # Preserve ALL properties including ID
                    assistant_content.append({"type": "tool_use", **dict(block)})
                    log(LogLevel.DEBUG, f"Found tool call", 
                        extra={"tool": block.name, "input": json.dumps(block.input)})
            
            self.message_history.append({"role": "assistant", "content": assistant_content})

            # If we found tool calls, break out of the loop
            if tool_calls:
                break
        
        # After max retries or successful tool call
        if tool_calls:
            # Extract the first tool call for action
            tool_call = tool_calls[0]
            tool_name = tool_call.name
            tool_input = tool_call.input
            
            log(LogLevel.DEBUG, f"Selected action after {attempts} attempt(s)", 
                extra={"tool": tool_name, "input": json.dumps(tool_input)})
            
            log(LogLevel.INFO, f"Claude tool use", 
                extra={"event_type": "claude_tool_use", "tool_name": tool_name, "tool_input_data": tool_input})

            
            # Convert to action string format
            action = f"{tool_name}:{json.dumps(tool_input)}"
            
            return action, True
        else:
            # If we still don't have tool calls after max retries
            log(LogLevel.ERROR, f"No tool calls after {max_retries} attempts")
            return "button:a", False  # Return fallback and False for success

    async def apply_action(self, state: Dict[str, Any], action: str) -> Dict[str, Any]:
        """Apply an action and return the new state."""
        log(LogLevel.INFO, f"Applying action", extra={"action": action})
        
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
                    
                    # Add the tool results to message history
                    self.message_history.append({"role": "user", "content": tool_results})
                    
                    log(LogLevel.INFO, f"Tool result", 
                        extra={
                            "event_type": "tool_result", 
                            "content_items_count": len(result_content),
                            "game_state": new_state["game_state"]  # Include game state in logs
                        })

                    log(LogLevel.DEBUG, f"Added tool result to history", 
                        extra={"action": action, "tool_use_id": tool_use_id})
        
        # Create a snapshot of the game state after this action
        snapshot_id = await self.create_gameplay_snapshot(new_state, action)
        
        return new_state

    
    async def create_gameplay_snapshot(self, state: Dict[str, Any], action: str) -> str:
        """Create a snapshot of the current game state after an action.
        
        Args:
            state: Current game state
            action: The action that was just performed
            
        Returns:
            str: The ID of the created snapshot
        """
        if not hasattr(self, 'morph_instance') or not self.morph_instance:
            log(LogLevel.WARNING, "Cannot create snapshot - no morph_instance reference")
            return ""
        
        log(LogLevel.INFO, f"Creating snapshot after action", 
            extra={"action": action})
        
        try:
            # First, create a snapshot to capture the current state
            snapshot_id = self.morph_instance.create_snapshot()
            
            if not snapshot_id:
                log(LogLevel.ERROR, "Failed to create snapshot - no snapshot ID returned")
                return ""
                
            # Get the current timestamp for metadata
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Extract relevant game state info for the metadata
            game_state_summary = {}
            if isinstance(state.get("game_state"), str):
                # Parse the formatted game state string for key information
                lines = state["game_state"].split('\n')
                for line in lines:
                    if ':' in line:
                        parts = line.split(':', 1)
                        if len(parts) == 2:
                            key, value = parts
                            # Only include specific fields we're interested in
                            if key.strip() in ["Player", "Location", "Badges", "Pokemon", "Money"]:
                                game_state_summary[key.strip()] = value.strip()
            
            # Create metadata for the snapshot
            snapshot_metadata = {
                "name": f"pokemon_action_{timestamp}",
                "description": f"Game state after action: {action}",
                "game": "Pokemon Red",
                "action": action,
                "timestamp": timestamp,
                "last_action": state.get("last_action", "")
            }
            
            # Add game state summary to metadata
            for key, value in game_state_summary.items():
                # Keep metadata values reasonably short
                if len(value) > 200:
                    value = value[:197] + "..."
                snapshot_metadata[f"game_state_{key.lower()}"] = value
            
            # Set the metadata on the snapshot
            self.morph_instance.set_snapshot_metadata(snapshot_id, snapshot_metadata)
            
            log(LogLevel.SUCCESS, f"Created and annotated gameplay snapshot", 
                extra={"snapshot_id": snapshot_id, "snapshot_name": snapshot_metadata["name"]})
            log(LogLevel.INFO, f"Created snapshot", 
                extra={"event_type": "snapshot_created", "snapshot_id": snapshot_id, "step_count": self.step_count})
            
            
            return snapshot_id
        except Exception as e:
            log(LogLevel.ERROR, f"Failed to create snapshot", 
                extra={"error": str(e), "action": action})
            import traceback
            log(LogLevel.ERROR, f"Snapshot error traceback", 
                extra={"traceback": traceback.format_exc()})
            return ""



    async def summarize_history(self):
        """Summarize the conversation history to save context space."""
        log(LogLevel.INFO, "Summarizing conversation history")
        
        # Get a new screenshot using the MCP tool
        screenshot_result = await self.mcp_handler.get_screenshot()
        screenshot_b64 = screenshot_result.get("screenshot", "")
        
        # Create messages for the summarization request
        messages = copy.deepcopy(self.message_history)
        
        # Add cache control for older messages
        if len(messages) >= 3:
            if messages[-1]["role"] == "user" and isinstance(messages[-1]["content"], list) and messages[-1]["content"]:
                messages[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}
            
            if len(messages) >= 5 and messages[-3]["role"] == "user" and isinstance(messages[-3]["content"], list) and messages[-3]["content"]:
                messages[-3]["content"][-1]["cache_control"] = {"type": "ephemeral"}
        
        # Add the summary prompt
        messages.append({
            "role": "user",
            "content": self.summary_prompt,
        })
        
        # Validate messages to ensure none have empty content
        validated_messages = [msg for msg in messages if msg.get('content')]
        if len(validated_messages) != len(messages):
            log(LogLevel.WARNING, f"Filtered {len(messages) - len(validated_messages)} messages with empty content for summarization")
            messages = validated_messages
        
        # Get summary from Claude
        response = self.anthropic.messages.create(
            model=self.model_name,
            max_tokens=self.max_tokens,
            system=self.system_prompt,
            messages=messages,
            temperature=0.7
        )
        
        # Extract the summary text
        summary_text = " ".join([block.text for block in response.content if block.type == "text"])
        
        log(LogLevel.INFO, f"Game Progress Summary:\n{summary_text}")
        
        # Create summary content
        summary_content = []
        
        # Add summary text
        if summary_text:
            summary_content.append({
                "type": "text",
                "text": f"CONVERSATION HISTORY SUMMARY (representing {self.max_history} previous messages): {summary_text}"
            })
            summary_content.append({
                "type": "text",
                "text": "\n\nCurrent game screenshot for reference:"
            })
        else:
            summary_content.append({
                "type": "text",
                "text": f"CONVERSATION HISTORY SUMMARY: Unable to generate detailed summary. Continuing gameplay."
            })
        
        # Add screenshot if available
        if screenshot_b64:
            summary_content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": screenshot_b64,
                },
            })
        
        # Add continuation prompt
        summary_content.append({
            "type": "text",
            "text": "You were just asked to summarize your playthrough so far, which is the summary you see above. You may now continue playing by selecting your next action."
        })
        
        # Replace message history with just the summary
        if summary_content:
            self.message_history = [
                {
                    "role": "user",
                    "content": summary_content
                }
            ]
            log(LogLevel.DEBUG, f"Message history condensed into summary.")
        else:
            log(LogLevel.ERROR, f"Failed to create valid summary content - keeping message history")


async def run_pokemon_example(snapshot_id=None, steps=200):
    """Run a Pokemon Red game using the E.V.A. framework with a MorphVM-hosted MCP server."""
    log(LogLevel.INFO, "Starting Pokemon example", 
        extra={"framework": "E.V.A.", "snapshot_id": snapshot_id})
    
    # In a real scenario, you would use an actual snapshot ID
    POKEMON_MCP_SNAPSHOT_ID = snapshot_id
    
    # First, we need to start a MorphVM instance with the Pokemon MCP server
    log(LogLevel.INFO, f"Starting MorphVM instance", 
        extra={"snapshot_id": POKEMON_MCP_SNAPSHOT_ID})
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
        
        log(LogLevel.SUCCESS, f"MCP server exposed", 
            extra={"mcp_url": mcp_url})
        
        # Now connect to the MCP service running on the MorphVM
        mcp_handler = PokemonMCPHandler(f"{mcp_url}/sse")  # Assuming /sse is the SSE endpoint
        connected = await mcp_handler.connect()
        
        if not connected:
            log(LogLevel.ERROR, "Failed to connect to MCP server on MorphVM")
            return
        
        def verify_player_names(game_state: Dict[str, Any]) -> bool:
            """Verify that player name is CLAUDE and rival name is WACLAUD."""
            if isinstance(game_state, str):
                log(LogLevel.INFO, "Checking player and rival names", 
                    extra={"format": "string"})
                player_name = None
                rival_name = None
                
                # Parse the formatted game state string
                for line in game_state.split('\n'):
                    if line.startswith("Player:"):
                        player_name = line.replace("Player:", "").strip()
                        log(LogLevel.INFO, f"Found player name", 
                            extra={"player_name": player_name})
                    elif line.startswith("Rival:"):
                        rival_name = line.replace("Rival:", "").strip()
                        log(LogLevel.INFO, f"Found rival name", 
                            extra={"rival_name": rival_name})
                        
                    # Once we have both names, we can check them
                    if player_name and rival_name:
                        # Check that names match the expected values
                        has_correct_names = (player_name == "CLAUDE" and rival_name == "WACLAUD")
                        log(LogLevel.INFO, f"Names verification result", 
                            extra={"correct": has_correct_names, 
                                   "player": player_name, 
                                   "rival": rival_name})
                        return has_correct_names
                
                # If we didn't find both names or they didn't match
                log(LogLevel.WARNING, f"Name verification failed",
                    extra={"player_found": player_name is not None,
                           "rival_found": rival_name is not None})
                return False
            else:
                log(LogLevel.ERROR, f"Unexpected game state type", 
                    extra={"type": type(game_state).__name__})
                return False

        def verify_left_mount_moon(game_state: Dict[str, Any]) -> bool:
            """Verify that player has successfully left Mount Moon."""
            if isinstance(game_state, str):
                log(LogLevel.INFO, "Checking if player has left Mount Moon")
                
                # Parse the formatted game state string
                for line in game_state.split('\n'):
                    if line.startswith("Location:"):
                        location = line.replace("Location:", "").strip()
                        log(LogLevel.INFO, f"Current location", 
                            extra={"location": location})
                        
                        # Check if location indicates player has left Mount Moon
                        if "Route 4" in location:
                            log(LogLevel.SUCCESS, f"Player has left Mount Moon", 
                                extra={"location": location})
                            return True
                        elif "Cerulean" in location:
                            log(LogLevel.SUCCESS, f"Player has reached Cerulean City", 
                                extra={"location": location})
                            return True
                        elif "Mt. Moon" in location or "Mount Moon" in location:
                            log(LogLevel.INFO, f"Player is still in Mount Moon")
                            return False
                
                log(LogLevel.WARNING, "Could not determine player location")
                return False
            else:
                log(LogLevel.ERROR, f"Unexpected game state type", 
                    extra={"type": type(game_state).__name__})
                return False

        # Create a verification function for beating the first gym
        def verify_beat_first_gym(game_state: Dict[str, Any]) -> bool:
            # Handle case where game_state is a string (which is the actual case based on get_state_from_memory)
            if isinstance(game_state, str):
                log(LogLevel.INFO, f"Checking for Boulder Badge")
                # Look for the badges line in the formatted string
                for line in game_state.split('\n'):
                    if line.startswith("Badges:"):
                        badges_str = line.replace("Badges:", "").strip()
                        badges = [b.strip() for b in badges_str.split(',') if b.strip()]
                        log(LogLevel.INFO, f"Current badges", 
                            extra={"badges": badges})
                        has_badge = "Boulder Badge" in badges
                        log(LogLevel.INFO, f"Boulder Badge check result", 
                            extra={"has_boulder_badge": has_badge})
                        return has_badge
                
                log(LogLevel.WARNING, "Could not find badges information")
                return False
            elif isinstance(game_state, dict):
                # If it's somehow a dictionary, use the original approach
                badges = game_state.get("badges", [])
                log(LogLevel.INFO, f"Current badges (dict format)", 
                    extra={"badges": badges})
                has_badge = "Boulder Badge" in badges
                return has_badge
            else:
                log(LogLevel.ERROR, f"Unexpected game state type", 
                    extra={"type": type(game_state).__name__})
                return False
        
        # Create a Pokemon task - note we're using the same snapshot ID
        # since our verification happens through the MCP API, not by starting a new VM
        
        # Task for naming characters
        brock_task = PokemonVerifiedTask.create(
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

        task = PokemonVerifiedTask.create(
            instruction="Defeat Brock and earn the Boulder Badge",
            snapshot_id=POKEMON_MCP_SNAPSHOT_ID,  # Using same snapshot since we're verifying through MCP
            verification_function=verify_beat_first_gym,
            verification_message="You need to defeat Brock at the Pewter City Gym to earn the Boulder Badge.",
            metadata={"game": "Pokemon Red", "objective": "gym_battle"}
        )
        
        # Create a Pokemon agent
        agent = PokemonAgent(mcp_handler)

        agent.morph_instance = morph_instance

        novnc_url = morph_instance.instance.expose_http_service(
            name="novnc",
            port=6080# Assuming MCP server runs on port 8000 inside the VM
        )

        log(LogLevel.INFO, f"NoVNC service available", 
            extra={"event_type": "novnc_url", "url": f"{novnc_url}/vnc_lite.html"})
        
        # Run the agent
        log(LogLevel.INFO, "Running Pokemon agent")
        result, trajectory = await run(
            task=task,
            agent=agent,
            max_steps=steps,  # Allow up to 200 steps
            verify_every_step=True
        )
        
        # Print the result
        log(LogLevel.INFO, "Pokemon example completed", 
            extra={"success": result.success, "message": result.message})
        
        # Print a summary of key trajectory steps
        log(LogLevel.INFO, "Key gameplay moments summary",
            extra={"total_steps": len(trajectory.steps)})
        
        # Log full trajectory in JSONL format
        for i, step in enumerate(trajectory.steps):
            if step.action:
                log(LogLevel.INFO, f"Gameplay action", 
                    extra={"step": i, "action": step.action})
    
    finally:
        # Clean up both the MCP handler and the MorphVM instance
        await mcp_handler.cleanup()
        morph_instance.stop()
        log(LogLevel.INFO, "Resources cleaned up")


# Entry point for running the example
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Run Pokemon agent with custom snapshot ID')
    parser.add_argument('--snapshot-id', type=str, help='Snapshot ID to use for the MorphVM instance')
    parser.add_argument('--steps', type=int, default=200, help='Number of steps to run the agent for')
    
    args = parser.parse_args()
    
    asyncio.run(run_pokemon_example(args.snapshot_id, args.steps))
