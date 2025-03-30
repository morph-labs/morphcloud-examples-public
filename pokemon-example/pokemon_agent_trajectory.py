import asyncio
import copy
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable, Sequence, Union, TypeVar, Generic, Tuple
from tasks import create_pokemon_verified_task, get_task_by_id, REGISTERED_TASKS


from anthropic import Anthropic

# Import from the main E.V.A. framework
from eva import (
    Instance, VerificationResult, VerifiedTask, Agent, Trajectory, TrajectoryStep,
    MorphInstance, log, LogLevel
)

# Type variables for generic components
S = TypeVar('S')  # State type
A = TypeVar('A')  # Action type
R = TypeVar('R')  # Verification result type
T = TypeVar('T')  # Snapshot type

# Define standard event types
EVENT_SNAPSHOT_CREATED = "snapshot_created"
EVENT_ACTION_STARTED = "action_started"
EVENT_ACTION_COMPLETED = "action_completed"
EVENT_TOOL_CALL = "tool_call"
EVENT_TOOL_RESULT = "tool_result"
EVENT_CLAUDE_TEXT = "claude_text"
EVENT_TRAJECTORY_UPDATED = "trajectory_updated"

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
            log(LogLevel.INFO, f"Game state summary: {game_state}", 
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

@dataclass
class PokemonTrajectoryStep(TrajectoryStep[Dict[str, Any], str, bool, str]):
    """A specialized trajectory step for Pokemon gameplay with extended data."""
    
    # Add Pokemon-specific fields
    game_state: Optional[str] = None  # Formatted game state string
    location: Optional[str] = None  # Current location in the game
    screenshot_data: Optional[str] = None  # Base64 screenshot data
    tool_name: Optional[str] = None  # Name of the tool used (e.g., "button", "navigate_to")
    tool_input: Optional[dict] = None  # Input parameters for the tool
    claude_text: Optional[str] = None  # Claude's reasoning before the action
    
    def __post_init__(self):
        """Process after initialization."""
        # Extract location from game state if not provided
        if not self.location and isinstance(self.game_state, str):
            for line in self.game_state.split('\n'):
                if line.startswith("Location:"):
                    self.location = line.replace("Location:", "").strip()
                    break
        
        # Log step creation with all metadata
        action_str = f" -> {self.action}" if self.action else " (initial)"
        log(LogLevel.DEBUG, f"Pokemon trajectory step{action_str}", 
            extra={
                "event_type": "pokemon_step_created",
                "step_type": "initial" if self.action is None else "action",
                "location": self.location,
                "has_screenshot": bool(self.screenshot_data),
                "tool_name": self.tool_name
            })


class PokemonTrajectory(Trajectory[Dict[str, Any], str, bool, str]):
    """A specialized trajectory for Pokemon gameplay with additional metadata."""
    
    def __init__(self):
        """Initialize a Pokemon trajectory."""
        super().__init__()
        # Override steps with Pokemon-specific step type
        self.steps: List[PokemonTrajectoryStep] = []
    
    def add_step(self, state: Instance[Dict[str, Any], str], 
                 action: Optional[str] = None,
                 result: Optional[VerificationResult[bool]] = None,
                 tool_name: Optional[str] = None,
                 tool_input: Optional[dict] = None,
                 claude_text: Optional[str] = None) -> None:
        """Add a Pokemon-specific step to the trajectory."""
        # Extract game state and screenshot from state
        game_state = state.state.get("game_state", "")
        screenshot_data = state.state.get("screenshot", "")
        
        # Extract location from game state
        location = None
        if isinstance(game_state, str):
            for line in game_state.split('\n'):
                if line.startswith("Location:"):
                    location = line.replace("Location:", "").strip()
                    break
        
        # Create snapshot (gets snapshot ID)
        snapshot_id = state.snapshot()
        
        # Create specialized step
        step = PokemonTrajectoryStep(
            state=state,
            snapshot=snapshot_id,  # Snapshot ID
            action=action,
            result=result,
            timestamp=datetime.now(),
            game_state=game_state,
            location=location,
            screenshot_data=screenshot_data,
            tool_name=tool_name,
            tool_input=tool_input,
            claude_text=claude_text
        )
        
        # Add step to trajectory
        self.steps.append(step)
        
        # Log with standardized event
        if len(self.steps) == 1:
            log(LogLevel.INFO, "Started new Pokemon trajectory", 
                extra={
                    "event_type": "trajectory_started", 
                    "step_index": 0
                })
        else:
            action_str = f"{action}" if action else "None"
            log(LogLevel.INFO, f"Step {len(self.steps)-1}: Action={action_str}", 
                extra={
                    "event_type": "step_added", 
                    "step_index": len(self.steps)-1, 
                    "action": action_str,
                    "location": location,
                    "snapshot_id": snapshot_id
                })
        
        # Emit trajectory updated event
        log(LogLevel.INFO, "Trajectory updated", 
            extra={
                "event_type": EVENT_TRAJECTORY_UPDATED,
                "step_count": len(self.steps),
                "latest_step_index": len(self.steps) - 1
            })
    
    def serialize(self) -> Dict[str, Any]:
        """Serialize the trajectory to a dictionary."""
        serialized = {
            "steps": [],
            "snapshots": []
        }
        
        for i, step in enumerate(self.steps):
            # Basic step data
            step_data = {
                "index": i,
                "timestamp": step.timestamp.isoformat(),
                "action": step.action if step.action else None,
                "location": step.location,
                "snapshot_id": step.snapshot,  # The snapshot is the ID
            }
            
            # Add tool information if available
            if step.tool_name:
                step_data["tool"] = {
                    "name": step.tool_name,
                    "input": step.tool_input
                }
            
            # Add Claude's reasoning if available
            if step.claude_text:
                step_data["claude_text"] = step.claude_text
            
            # Add result information if available
            if step.result:
                step_data["result"] = {
                    "success": step.result.success,
                    "message": step.result.message
                }
            
            serialized["steps"].append(step_data)
            
            # Collect snapshots
            if step.snapshot:
                serialized["snapshots"].append({
                    "id": step.snapshot,
                    "step": i,
                    "timestamp": step.timestamp.isoformat(),
                    "location": step.location
                })
        
        return serialized


class PokemonInstance(Instance[Dict[str, Any], str]):
    """Instance implementation for Pokemon game state that returns snapshot IDs."""
    
    def __init__(self, state: Dict[str, Any], morph_instance: Optional[MorphInstance] = None):
        """Initialize a Pokemon instance."""
        super().__init__(state)
        self._morph_instance = morph_instance
    
    def snapshot(self) -> str:
        """Create a snapshot and return the ID for visualization and rollback."""
        morph_instance = getattr(self.state, '_morph_instance', None) or self._morph_instance
        
        if morph_instance:
            try:
                # Create a snapshot
                snapshot_id = morph_instance.create_snapshot()
                
                # Add metadata useful for the driver
                metadata = {
                    "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
                    "action": self.state.get("last_action", ""),
                    "step_index": str(len(getattr(morph_instance, '_trajectory', []))),
                }
                
                # Add game state summary to metadata
                game_state = self.state.get("game_state", "")
                if isinstance(game_state, str):
                    for line in game_state.split('\n'):
                        if line.startswith("Location:"):
                            metadata["location"] = line.replace("Location:", "").strip()
                
                # Set metadata on snapshot
                morph_instance.set_snapshot_metadata(snapshot_id, metadata)
                
                # Log with standardized event
                log(LogLevel.INFO, "Created snapshot", 
                    extra={
                        "event_type": EVENT_SNAPSHOT_CREATED, 
                        "snapshot_id": snapshot_id, 
                        "step_count": str(len(getattr(morph_instance, '_trajectory', [])))
                    })
                
                return snapshot_id
            except Exception as e:
                log(LogLevel.ERROR, f"Failed to create snapshot", extra={"error": str(e)})
                import traceback
                log(LogLevel.ERROR, f"Snapshot error traceback", 
                    extra={"traceback": traceback.format_exc()})
                return ""
        
        return ""  # Empty string if no morph_instance


class PokemonMCPHandler:
    """Handler for Pokemon MCP communication."""
    
    def __init__(self, server_url: str):
        """Initialize the MCP handler."""
        self.server_url = server_url
        self.exit_stack = None
        self.session = None
        self.streams = None
        self.tools = []
        log(LogLevel.INFO, f"Created MCP handler", extra={"server_url": server_url})
    
    async def connect(self):
        """Connect to the MCP server."""
        from contextlib import AsyncExitStack
        
        self.exit_stack = AsyncExitStack()
        
        try:
            # Import here to avoid issues if MCP isn't available
            from mcp import ClientSession
            from mcp.client.sse import sse_client
            
            log(LogLevel.INFO, f"Connecting to MCP server", extra={"url": self.server_url})
            
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
            import traceback
            log(LogLevel.ERROR, f"Connection error traceback", 
                extra={"traceback": traceback.format_exc()})
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
        
        log(LogLevel.DEBUG, f"Prepared Claude tools", 
            extra={"tool_count": len(claude_tools)})
        return claude_tools
    
    async def call_tool_with_extras(self, tool_name, tool_input, include_state=True, include_screenshot=True):
        """Call a tool and get state and screenshot in a more efficient way."""
        log(LogLevel.INFO, f"Calling tool with extras", 
            extra={"tool_name": tool_name, "include_state": include_state, "include_screenshot": include_screenshot})
        
        # Call the primary tool
        if not self.session:
            raise ValueError("Not connected to MCP server")
        
        primary_result = await self.session.call_tool(tool_name, tool_input)
        
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
        
        result_content = self._parse_result(primary_result)
        
        # Get game state if needed and not already included
        if include_state and not has_state:
            state_result = await self.session.call_tool("get_game_state", {})
            state_content = self._parse_result(state_result)
            result_content.update(state_content)
            
        # Get screenshot if needed and not already included
        if include_screenshot and not has_screenshot:
            screenshot_result = await self.session.call_tool("get_screenshot", {})
            screenshot_content = self._parse_result(screenshot_result)
            result_content.update(screenshot_content)
            
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
            response = await self.session.call_tool("get_screenshot", {})
            result = self._parse_result(response)
            
            # Process the screenshot
            if "screenshot" in result:
                result["screenshot"] = self.process_screenshot_data(result["screenshot"])
                
            return result
        except Exception as e:
            log(LogLevel.ERROR, f"Error getting screenshot", extra={"error": str(e)})
            return {"error": str(e)}
    
    def process_screenshot_data(self, data):
        """Process screenshot data from MCP server."""
        # For string data (expected to be base64)
        if isinstance(data, str):
            if len(data) > 100:  # Make sure it's substantial
                return data
        
        # If we got here, just return empty
        return ""
    
    async def execute_action(self, action: str) -> Dict[str, Any]:
        """Execute a game action."""
        if not self.session:
            raise ValueError("Not connected to MCP server")
        
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
        
        for content_item in response.content:
            if content_item.type == 'text':
                try:
                    parsed_json = json.loads(content_item.text)
                    # Make sure parsed_json is actually a dict before trying to access keys
                    if isinstance(parsed_json, dict):
                        result.update(parsed_json)
                    else:
                        result["parsed_content"] = parsed_json
                except json.JSONDecodeError:
                    # Check if this looks like the formatted game state string
                    if "Player:" in content_item.text and "Badges:" in content_item.text:
                        result["game_state"] = content_item.text
                    else:
                        result["text"] = content_item.text
        
        return result
    
    async def cleanup(self):
        """Clean up resources."""
        if self.exit_stack:
            try:
                await self.exit_stack.aclose()
                log(LogLevel.INFO, "MCP handler resources cleaned up")
            except Exception as e:
                log(LogLevel.ERROR, f"Error during MCP resource cleanup: {e}")
                import traceback
                log(LogLevel.ERROR, f"Cleanup error traceback", 
                    extra={"traceback": traceback.format_exc()})



class PokemonAgent(Agent[Dict[str, Any], str, bool, str]):
    """An agent that plays Pokemon using the Claude API and tracks its trajectory."""
    
    def __init__(self, mcp_handler: PokemonMCPHandler, model_name="claude-3-7-sonnet-latest", max_tokens=1000, max_history=30):
        """Initialize the Pokemon agent."""
        super().__init__()
        self.mcp_handler = mcp_handler
        self.anthropic = Anthropic()
        self.model_name = model_name
        self.max_tokens = max_tokens
        self.temperature = 0.7
        self.message_history = []
        self.max_history = max_history
        
        # Specialized trajectory
        self.trajectory = PokemonTrajectory()
        
        # Fields to store current step data
        self.current_tool_name = None
        self.current_tool_input = None
        self.current_claude_text = None
        
        # For pause and resume functionality
        self.paused = False
        self.pause_event = asyncio.Event()
        self.pause_event.set()  # Start unpaused

        self.system_prompt = """You are playing Pokemon Red. You can see the game screen and control the game by executing emulator commands: check your tools! for example, 'navigate_to' can help you move in the overworld. Before each action, explain your reasoning briefly, then use the available actions to control the game"""
        
        log(LogLevel.INFO, f"Initialized PokemonAgent", 
            extra={"model": model_name, "max_tokens": max_tokens})
    
    def set_objective(self, objective: str):
        """Set the agent's current objective."""
        self.objective = objective
        log(LogLevel.INFO, f"Setting agent objective", extra={"objective": objective})
    
    async def initialize_state(self, morph_instance: 'MorphInstance') -> PokemonInstance:
        """Initialize the state from a MorphCloud instance."""
        log(LogLevel.INFO, "Initializing Pokemon agent state")
        
        # Store reference to morph_instance
        self.morph_instance = morph_instance
        
        # Initialize with empty state
        initial_state = {
            "game_state": {},
            "screenshot": "",
            "valid_moves": [],
            "last_action": ""
        }
        
        # Set MorphInstance reference (this will be used by snapshot())
        initial_state['_morph_instance'] = morph_instance
        
        # Create the initial instance
        instance = PokemonInstance(initial_state, morph_instance)
        
        # Add a starting message to the history
        initial_message = f"Your current objective is: {self.objective}\n\nYou may now begin playing Pokemon."
        self.message_history = [{"role": "user", "content": initial_message}]
        
        # Initialize the trajectory with the first step
        self.trajectory.add_step(instance)
        
        log(LogLevel.INFO, "Initial state and trajectory created")
        return instance
    
    async def _update_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Update the state with the latest game information."""
        # Get game state
        game_state = await self.mcp_handler.get_game_state()
        
        # Get screenshot
        screenshot_result = await self.mcp_handler.get_screenshot()
        
        # Update the state
        new_state = {
            "game_state": game_state.get("game_state", {}),
            "screenshot": screenshot_result.get("screenshot", ""),
            "valid_moves": game_state.get("valid_moves", []),
            "last_action": state.get("last_action", "")
        }
        
        
        # Make sure morph_instance reference is preserved
        if "_morph_instance" in state:
            new_state["_morph_instance"] = state["_morph_instance"]
        
        return new_state
    
    async def wait_if_paused(self):
        """Wait if the agent is paused."""
        await self.pause_event.wait()
    
    def pause(self):
        """Pause the agent's execution."""
        self.paused = True
        self.pause_event.clear()
        log(LogLevel.INFO, "Agent paused", extra={"event_type": "agent_paused"})
    
    def resume(self):
        """Resume the agent's execution."""
        self.paused = False
        self.pause_event.set()
        log(LogLevel.INFO, "Agent resumed", extra={"event_type": "agent_resumed"})
    
    async def run_step(self, state: Instance[Dict[str, Any], str]) -> str:
        """Determine the next action using Claude."""
        log(LogLevel.INFO, "Determining next action with Claude")
        
        # Wait if paused
        await self.wait_if_paused()
        
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
        
        # Get action with retries if needed
        action, success = await self._retry_with_nudge(max_retries=3)
        
        if not success:
            log(LogLevel.ERROR, "Failed to get valid tool call after retries, using fallback action")
        
        return action
    
    async def _retry_with_nudge(self, max_retries=3):
        """Retry getting a tool call from Claude with nudges."""
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
            
            # Wait if paused before making Claude API call
            await self.wait_if_paused()
            
            # Get Claude's response
            response = self.anthropic.messages.create(
                model=self.model_name,
                max_tokens=self.max_tokens,
                system=self.system_prompt,
                messages=messages,
                tools=self.mcp_handler.get_claude_tools(),
                temperature=self.temperature
            )
            
            # Extract Claude's text reasoning
            claude_text = " ".join([block.text for block in response.content if block.type == "text"])
            
            # Log Claude's text with standardized event
            if claude_text:
                log(LogLevel.INFO, f"Claude response text: {claude_text}", 
                    extra={"event_type": EVENT_CLAUDE_TEXT, "text_content": claude_text})
                
                # Store for trajectory
                self.current_claude_text = claude_text
            
            # Extract tool calls
            tool_calls = [
                block for block in response.content if block.type == "tool_use"
            ]
            
            # Add Claude's response to history
            assistant_content = []
            for block in response.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
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
            
            # Log tool call with standardized event
            log(LogLevel.INFO, f"Claude tool use", 
                extra={"event_type": EVENT_TOOL_CALL, "tool_name": tool_name, "tool_input_data": tool_input})
            
            # Store for trajectory
            self.current_tool_name = tool_name
            self.current_tool_input = tool_input
            
            # Convert to action string format
            action = f"{tool_name}:{json.dumps(tool_input)}"
            
            return action, True
        else:
            # If we still don't have tool calls after max retries
            log(LogLevel.ERROR, f"No tool calls after {max_retries} attempts")
            return "button:a", False  # Return fallback and False for success
    
    async def apply_action(self, state: Dict[str, Any], action: str) -> Dict[str, Any]:
        """Apply an action and return the new state."""
        log(LogLevel.INFO, f"Applying action", 
            extra={"event_type": EVENT_ACTION_STARTED, "action": action})
        
        # Wait if paused
        await self.wait_if_paused()
        
        # Execute the action
        action_result = await self.mcp_handler.execute_action(action)
        
        # Create a new state with the result
        new_state = {
            "last_action": action,
            "game_state": state.get("game_state", ""),
            "screenshot": state.get("screenshot", ""),
            "valid_moves": state.get("valid_moves", [])
        }

        
        # Make sure morph_instance reference is preserved
        if "_morph_instance" in state:
            new_state["_morph_instance"] = state["_morph_instance"]
        
        # Update the state with fresh game information
        new_state = await self._update_state(new_state)
        
        # Log tool result with standardized event
        log(LogLevel.INFO, f"Tool result", 
            extra={
                "event_type": EVENT_TOOL_RESULT, 
                "action": action,
                "game_state": new_state["game_state"]
            })
        
        # Create tool results from the action for Claude history
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
        
        # Create PokemonInstance from the new state
        instance = PokemonInstance(new_state)
        
        if isinstance(self.trajectory, PokemonTrajectory):
            # Use the enhanced method with Pokemon-specific fields
            self.trajectory.add_step(
                state=instance,
                action=action,
                tool_name=self.current_tool_name,
                tool_input=self.current_tool_input,
                claude_text=self.current_claude_text
            )
        else:
            # Fall back to the base Trajectory method
            log(LogLevel.WARNING, "Using base Trajectory.add_step instead of PokemonTrajectory", 
                extra={"trajectory_class": self.trajectory.__class__.__name__})
            self.trajectory.add_step(state=instance, action=action)

        
        # Reset current step data
        self.current_tool_name = None
        self.current_tool_input = None
        self.current_claude_text = None
        
        # Log action completion
        log(LogLevel.INFO, f"Action completed", 
            extra={"event_type": EVENT_ACTION_COMPLETED, "action": action})
        
        return new_state
    
    async def summarize_history(self):
        """Summarize the conversation history to save context space."""
        log(LogLevel.INFO, "Summarizing conversation history")
        
        # Get a new screenshot
        screenshot_result = await self.mcp_handler.get_screenshot()
        screenshot_b64 = screenshot_result.get("screenshot", "")
        
        # Create summary prompt
        summary_prompt = """I need you to create a detailed summary of our conversation history up to this point. This summary will replace the full conversation history to manage the context window.

        Please include:
        1. Key game events and milestones you've reached
        2. Important decisions you've made
        3. Current objectives or goals you're working toward
        4. Your current location and Pokémon team status
        5. Any strategies or plans you've mentioned

        The summary should be comprehensive enough that you can continue gameplay without losing important context about what has happened so far."""
        
        # Add the summary prompt to message history
        messages = copy.deepcopy(self.message_history)
        messages.append({
            "role": "user",
            "content": summary_prompt,
        })
        
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
        
        if not summary_text:
            log(LogLevel.WARNING, "Failed to generate summary, keeping message history")
            return
            
        log(LogLevel.INFO, f"Game Progress Summary Generated", 
            extra={"summary_length": len(summary_text)})
        
        # Create summary content
        summary_content = []
        summary_content.append({
            "type": "text",
            "text": f"CONVERSATION HISTORY SUMMARY (representing {self.max_history} previous messages): {summary_text}"
        })
        
        # Add screenshot if available
        if screenshot_b64:
            summary_content.append({
                "type": "text",
                "text": "\n\nCurrent game screenshot for reference:"
            })
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
            "text": "You may now continue playing by selecting your next action."
        })
        
        # Replace message history with just the summary
        self.message_history = [
            {
                "role": "user",
                "content": summary_content
            }
        ]
        log(LogLevel.INFO, "Message history condensed into summary")


# HTTP API for the driver to communicate with the agent
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

import uvicorn
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

class RollbackRequest(BaseModel):
    """Request to roll back to a specific step."""
    step_index: int

class AgentRequest(BaseModel):
    """Request to start the agent with a task."""
    snapshot_id: str
    steps: int = 100
    objective: str = "Explore the Pokemon world"
    task_id: str = ""

class PokemonAPI:
    """API for the driver to communicate with the Pokemon agent."""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 8000):
        """Initialize the API."""
        self.host = host
        self.port = port
        self.app = FastAPI(title="Pokemon Agent API")

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],        # or ["*"] to allow all
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],)

        
        self.agent = None
        self.task = None
        self.morph_instance = None
        self.running_task = None
        self.novnc_url = None  # Store NoVNC URL for the frontend
        
        # Register routes
        self.register_routes()
    
    def register_routes(self):
        """Register API routes."""
        
        @self.app.get("/")
        async def root():
            """Root endpoint."""
            return {"message": "Pokemon Agent API"}
        
        @self.app.get("/tasks")
        async def list_tasks():
            """
            Return a list of all registered tasks that the user can choose from.
            Each task is converted to a dictionary for easy JSON serialization.
            """
            return [
                {
                    "id": task.id,
                    "instruction": task.instruction,
                    "verification_fn_name": task.verification_fn_name,
                    "verification_message": task.verification_message,
                    "metadata": task.metadata,
                }
                for task in REGISTERED_TASKS
            ]


        @self.app.get("/status")
        async def get_status():
            """Get agent status."""
            if not self.agent:
                return {"status": "not_initialized"}
            
            return {
                "status": "paused" if self.agent.paused else "running",
                "step_count": len(self.agent.trajectory.steps) if self.agent.trajectory else 0,
                "objective": getattr(self.agent, 'objective', None)
            }
        
        @self.app.get("/trajectory")
        async def get_trajectory():
            """Get the current trajectory."""
            if not self.agent or not self.agent.trajectory:
                return {"steps": [], "snapshots": []}
            
            return self.agent.trajectory.serialize()
            
        @self.app.get("/novnc_url")
        async def get_novnc_url():
            """Get the NoVNC URL for the game display."""
            if self.novnc_url:
                return {"url": f"{self.novnc_url}/vnc_lite.html"}
            else:
                return {"url": None}
        
        @self.app.post("/start")
        async def start_agent(request: AgentRequest, background_tasks: BackgroundTasks):
            """Start the agent with a task."""
            if self.running_task:
                return {"success": False, "error": "Agent is already running"}
            
            try:
                background_tasks.add_task(
                    self.run_agent_task, 
                    request.snapshot_id,
                    request.steps,
                    request.task_id,
                    request.objective
                )

                return {"success": True, "message": "Agent started"}
            except Exception as e:
                log(LogLevel.ERROR, f"Failed to start agent", extra={"error": str(e)})
                return {"success": False, "error": str(e)}
        
        @self.app.post("/pause")
        async def pause_agent():
            """Pause the agent."""
            if not self.agent:
                return {"success": False, "error": "Agent not initialized"}
            
            if self.agent.paused:
                return {"success": True, "message": "Agent already paused"}
            
            self.agent.pause()
            return {"success": True, "message": "Agent paused"}
        
        @self.app.post("/resume")
        async def resume_agent():
            """Resume the agent."""
            if not self.agent:
                return {"success": False, "error": "Agent not initialized"}
            
            if not self.agent.paused:
                return {"success": True, "message": "Agent already running"}
            
            self.agent.resume()
            return {"success": True, "message": "Agent resumed"}
        
        @self.app.post("/rollback")
        async def rollback(request: RollbackRequest, background_tasks: BackgroundTasks):
            """Roll back to a specific step."""
            if not self.agent or not self.agent.trajectory:
                return {"success": False, "error": "Agent not initialized"}
            
            if request.step_index < 0 or request.step_index >= len(self.agent.trajectory.steps):
                return {"success": False, "error": "Invalid step index"}
            
            # Pause the agent first
            self.agent.pause()
            
            try:
                background_tasks.add_task(
                    self.rollback_to_step,
                    step_index=request.step_index
                )
                return {"success": True, "message": f"Rolling back to step {request.step_index}"}
            except Exception as e:
                log(LogLevel.ERROR, f"Failed to rollback", extra={"error": str(e)})
                return {"success": False, "error": str(e)}
        
        @self.app.post("/stop")
        async def stop_agent():
            """Stop the agent."""
            if not self.agent:
                return {"success": False, "error": "Agent not initialized"}
            
            try:
                # Pause first
                self.agent.pause()
                
                # Clean up resources
                if self.morph_instance:
                    self.morph_instance.stop()
                    self.morph_instance = None
                
                if self.agent and hasattr(self.agent, 'mcp_handler'):
                    await self.agent.mcp_handler.cleanup()
                
                self.agent = None
                self.task = None
                self.running_task = None
                
                return {"success": True, "message": "Agent stopped"}
            except Exception as e:
                log(LogLevel.ERROR, f"Failed to stop agent", extra={"error": str(e)})
                return {"success": False, "error": str(e)}
    
    async def run_agent_task(self, snapshot_id: str, steps: int, task_id: Optional[str], objective: str):
        """
        The background task that actually:
        1. Creates the MorphInstance from the snapshot.
        2. Connects to MCP.
        3. Creates the PokemonAgent.
        4. Builds the PokemonVerifiedTask (if task_id is provided), or fallback task if not.
        5. Calls eva.run(...) and blocks until done or steps exhausted.
        """

        # logger.info(f"run_agent_task started with snapshot_id={snapshot_id}, steps={steps}, task_id={task_id}")

        try:
            # 1. Launch MorphInstance
            self.morph_instance = MorphInstance(
                snapshot_id=snapshot_id,
                metadata={"purpose": "pokemon_game_server"},
                ttl_seconds=3600
            )

            # 2. Expose MCP on port 8000 inside the VM
            mcp_url = self.morph_instance.instance.expose_http_service(name="mcp", port=8000)
            # logger.info(f"MCP server exposed at: {mcp_url}")

            # 3. Connect NoVNC and store the URL for frontend access
            novnc_url = self.morph_instance.instance.expose_http_service(name="novnc", port=6080)
            self.novnc_url = novnc_url
            log(LogLevel.INFO, f"NoVNC (VNC) accessible at: {novnc_url}/vnc_lite.html", 
                extra={"event_type": "novnc_url", "url": f"{novnc_url}/vnc_lite.html"})

            # 4. Create MCP handler
            mcp_handler = PokemonMCPHandler(f"{mcp_url}/sse")
            connected = await mcp_handler.connect()
            if not connected:
                # logger.error("Failed to connect to MCP server")
                return

            # 5. Create the agent
            self.agent = PokemonAgent(mcp_handler=mcp_handler)
            
            # Decide which VerifiedTask to run
            if task_id:
                # Use a real task from tasks.py
                self.running_task = create_pokemon_verified_task(task_id, snapshot_id)
                # The agent's "objective" might be the instruction from the actual task:
                self.agent.set_objective(self.running_task.instruction)
            else:
                # Fallback: create a trivial verification or use the 'objective' string
                # logger.warning("No task_id provided. Using trivial verification function.")
                def dummy_verify_func(gs: Dict[str, Any]) -> bool:
                    return False  # Always returns false => never completes
                self.running_task = PokemonVerifiedTask.create(
                    instruction=objective,
                    snapshot_id=snapshot_id,
                    verification_function=dummy_verify_func,
                    verification_message="No real verification in place",
                    metadata={"game": "Pokemon Red", "objective": objective}
                )
                self.agent.set_objective(objective)

            # 6. Run the agent with E.V.A.
            # logger.info(f"Starting E.V.A. run() for task: {self.running_task.instruction}")
            from eva import run
            result, trajectory = await run(
                task=self.running_task,
                agent=self.agent,
                max_steps=steps,
                verify_every_step=True,
                ttl_seconds=3600
            )

            # logger.info(f"Agent run complete. success={result.success}, message={result.message}")
            
        except Exception as e:
            print(e)
            # logger.exception("Error in run_agent_task")
        finally:
            self.background_task_active = False

    
    async def rollback_to_step(self, step_index: int):
        """Roll back to a specific step."""
        try:
            log(LogLevel.INFO, f"Rolling back to step {step_index}")
            
            if not self.agent or not self.task:
                log(LogLevel.ERROR, "Cannot rollback - agent or task not initialized")
                return
            
            # Get snapshot ID from the step
            target_step = self.agent.trajectory.steps[step_index]
            snapshot_id = target_step.snapshot
            
            if not snapshot_id:
                log(LogLevel.ERROR, f"No snapshot ID available for step {step_index}")
                return
            
            # Clean up existing MorphInstance if any
            if self.morph_instance:
                self.morph_instance.stop()
            
            # Start new MorphVM instance from the snapshot
            log(LogLevel.INFO, f"Starting MorphVM instance from rollback snapshot", 
                extra={"snapshot_id": snapshot_id})
            self.morph_instance = MorphInstance(
                snapshot_id=snapshot_id,
                metadata={"purpose": "pokemon_game_server_rollback"},
                ttl_seconds=7200  # 2-hour TTL
            )
            
            # Get MCP URL
            mcp_url = self.morph_instance.instance.expose_http_service(
                name="mcp",
                port=8000
            )
            
            log(LogLevel.SUCCESS, f"MCP server exposed for rollback", 
                extra={"mcp_url": mcp_url})
            
            # Expose NoVNC for the UI and store the URL
            novnc_url = self.morph_instance.instance.expose_http_service(
                name="novnc",
                port=6080
            )
            self.novnc_url = novnc_url
            
            log(LogLevel.INFO, f"NoVNC service available after rollback", 
                extra={"event_type": "novnc_url", "url": f"{novnc_url}/vnc_lite.html"})
            
            # Create new MCP handler
            mcp_handler = PokemonMCPHandler(f"{mcp_url}/sse")
            connected = await mcp_handler.connect()
            
            if not connected:
                log(LogLevel.ERROR, "Failed to connect to MCP server after rollback")
                return
            
            # Create new agent with the same objective
            self.agent = PokemonAgent(mcp_handler=mcp_handler)

            self.agent.set_objective(getattr(self.task, 'instruction', "Continue playing Pokemon"))
            
            # Create new trajectory with steps up to the rollback point
            new_trajectory = PokemonTrajectory()
            for i in range(step_index + 1):
                new_trajectory.steps.append(self.agent.trajectory.steps[i])
            
            self.agent.trajectory = new_trajectory
            
            # Resume the agent
            self.agent.resume()
            
            log(LogLevel.SUCCESS, f"Rollback to step {step_index} completed")
            
        except Exception as e:
            log(LogLevel.ERROR, f"Error during rollback", extra={"error": str(e)})
            import traceback
            log(LogLevel.ERROR, f"Rollback error traceback", extra={"traceback": traceback.format_exc()})
    
    def start(self):
        """Start the API server."""
        uvicorn.run(self.app, host=self.host, port=self.port)


# Example usage
async def run_pokemon_example(snapshot_id: str, steps: int = 100):
    """Run a Pokemon example."""
    # Create the API
    api = PokemonAPI(host="127.0.0.1", port=8000)
    
    # Start the API in a separate thread
    import threading
    api_thread = threading.Thread(target=api.start)
    api_thread.daemon = True
    api_thread.start()
    
    # Start the agent using the API
    import requests
    response = requests.post(
        "http://127.0.0.1:8000/start",
        json={
            "snapshot_id": snapshot_id,
            "steps": steps,
            "objective": "Explore Pokemon Red and defeat the second gym leader"
        }
    ).json()
    
    if response.get("success"):
        print("Agent started successfully")
    else:
        print(f"Failed to start agent: {response.get('error')}")


def verify_player_names(game_state: Dict[str, Any]) -> bool:
    """
    Verify that the player name is 'CLAUDE' and the rival name is 'WACLAUD'.
    This expects game_state to be the formatted string containing 'Player:' and 'Rival:' lines.
    """
    if isinstance(game_state, str):
        player_name = None
        rival_name = None
        for line in game_state.split('\n'):
            if line.startswith("Player:"):
                player_name = line.replace("Player:", "").strip()
            elif line.startswith("Rival:"):
                rival_name = line.replace("Rival:", "").strip()
            
            # Once both names are found, verify them
            if player_name and rival_name:
                return (player_name == "CLAUDE" and rival_name == "WACLAUD")
        return False
    return False

def verify_left_mount_moon(game_state: Dict[str, Any]) -> bool:
    """
    Verify that the player has successfully left Mount Moon.
    Checking for 'Location:' line indicating 'Route 4' 
    """
    if isinstance(game_state, str):
        for line in game_state.split('\n'):
            if line.startswith("Location:"):
                location = line.replace("Location:", "").strip()
                return ("ROUTE 4" in location) 
    return False

def verify_beat_first_gym(game_state: Dict[str, Any]) -> bool:
    """
    Verify that the player has earned the 'Boulder Badge' from Brock.
    Look for 'Badges:' line that includes 'Boulder Badge'.
    """
    if isinstance(game_state, str):
        for line in game_state.split('\n'):
            if line.startswith("Badges:"):
                badges_str = line.replace("Badges:", "").strip()
                # Split by commas, check if 'Boulder Badge' is one of them
                badges = [b.strip() for b in badges_str.split(',')]
                return "BOULDER" in badges
    return False


async def run_pokemon_without_api(snapshot_id: str, steps: int = 100):
    """Run Pokemon agent directly without using the API."""
    log(LogLevel.INFO, f"Starting Pokemon agent directly", 
        extra={"snapshot_id": snapshot_id, "steps": steps})
    
    
    # Create the task
    task_def = get_task_by_id("escape-mt-moon")
    print(f"Running task: {task_def.instruction}")
    
    # Create the task with a snapshot ID
    moon_task = create_pokemon_verified_task("escape-mt-moon", snapshot_id)

    # Start MorphVM instance
    log(LogLevel.INFO, f"Starting MorphVM instance", 
        extra={"snapshot_id": snapshot_id})
    
    morph_instance = MorphInstance(
        snapshot_id=snapshot_id,
        metadata={"purpose": "pokemon_game_server"},
        ttl_seconds=7200  # 2-hour TTL
    )
    
    mcp_handler = None
    
    try:
        # Get MCP URL
        mcp_url = morph_instance.instance.expose_http_service(
            name="mcp",
            port=8000  # Assuming MCP server runs on port 8000 inside the VM
        )
        
        log(LogLevel.SUCCESS, f"MCP server exposed", 
            extra={"mcp_url": mcp_url})
        
        # Expose NoVNC for the UI
        novnc_url = morph_instance.instance.expose_http_service(
            name="novnc",
            port=6080
        )
        
        log(LogLevel.INFO, f"NoVNC service available", 
            extra={"event_type": "novnc_url", "url": f"{novnc_url}/vnc_lite.html"})
        
        # Create MCP handler
        mcp_handler = PokemonMCPHandler(f"{mcp_url}/sse")
        connected = await mcp_handler.connect()
        
        if not connected:
            log(LogLevel.ERROR, "Failed to connect to MCP server")
            return
        
        # Create the agent
        agent = PokemonAgent(mcp_handler=mcp_handler)


        # agent.trajectory = PokemonTrajectory()
        
        # Set the objective
        agent.set_objective("Explore Pokemon Red and defeat the second gym leader")
        
        # Run the agent
        from eva import run
        result, _ = await run(
            task=moon_task,
            agent=agent,
            max_steps=steps,
            verify_every_step=True,
            ttl_seconds=7200  # 2-hour TTL
        )
        
        log(LogLevel.INFO, "Agent task completed", 
            extra={"success": result.success, "message": result.message})
    
    except Exception as e:
        log(LogLevel.ERROR, f"Error running agent: {e}")
        import traceback
        log(LogLevel.ERROR, f"Error traceback", 
            extra={"traceback": traceback.format_exc()})
    
    finally:
        # Clean up resources in reverse order
        if mcp_handler:
            try:
                await mcp_handler.cleanup()
            except Exception as e:
                log(LogLevel.ERROR, f"Error cleaning up MCP handler: {e}")
        
        try:
            morph_instance.stop()
            log(LogLevel.INFO, "MorphInstance stopped")
        except Exception as e:
            log(LogLevel.ERROR, f"Error stopping MorphInstance: {e}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Run Pokemon agent with trajectory system')
    parser.add_argument('--snapshot-id', type=str, required=True, help='Snapshot ID to use')
    parser.add_argument('--steps', type=int, default=100, help='Number of steps to run')
    parser.add_argument('--no-api', action='store_true', help='Run without the HTTP API')
    parser.add_argument('--port', type=int, default=8000, help='API server port')
    
    args = parser.parse_args()
    
    if args.no_api:
        # Run directly without API server
        asyncio.run(run_pokemon_without_api(args.snapshot_id, args.steps))
    else:
        # Create and start the API
        api = PokemonAPI(host="127.0.0.1", port=args.port)
        print(f"Starting Pokemon Agent API on port {args.port}...")
        api.start()

