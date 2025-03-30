# Pokemon Minimal Agent

This is a minimal implementation of a Pokemon Red AI agent that runs on MorphCloud. The agent uses Claude to control a Pokemon Red emulator running on a MorphCloud instance.

## Prerequisites

- A MorphCloud account and API key
- An Anthropic API key
- Python 3.10+

## Setup

1. Set your API keys as environment variables:

```bash
export MORPH_API_KEY=your_morph_api_key
export ANTHROPIC_API_KEY=your_anthropic_api_key
```

## Running the Agent

The agent is designed to run with a MorphCloud snapshot that has the Pokemon Red emulator pre-configured.

```bash
uv run minimal_agent.py --snapshot-id <snapshot_id>
```

This command will:
1. Start a MorphCloud instance from the provided snapshot ID
2. Connect the agent to the emulator running on that instance
3. Run the AI agent which will play Pokemon Red automatically
4. Stop the instance when the agent finishes

### Using the Dashboard UI:
```bash
uv run dashboard.py
```
This will:
1. Start a web interface on http://127.0.0.1:5001/
2. Open the UI automatically in your default browser
3. Allow you to input your snapshot ID and configure steps
4. Show agent logs and display the game in a single interface
5. Let you start and stop the agent at any time
6. Support rolling back to previous snapshots within a run via the "Snapshots" tab

To roll back to a previous snapshot:
1. Click on the "Snapshots" tab
2. Click "Load Snapshot" on the snapshot you want to restore
3. Stop and then restart the agent to continue from that point

The dashboard runs the agent with the `--no-browser` flag automatically to prevent opening duplicate browser windows.
## Command Line Options for minimal_agent.py

### Required Arguments:
- `--snapshot-id`: The MorphCloud snapshot ID to run

### Basic Configuration:
- `--api-key`: Your MorphCloud API key (defaults to MORPH_API_KEY environment variable)
- `--steps`: Number of agent steps to run (default: 10)
- `--max-history`: Maximum history size before summarizing conversation (default: 30)

### Logging and Display Options:
- `--verbose`, `-v`: Increase output verbosity (can be stacked, e.g., `-vv` for maximum detail)
- `--quiet`, `-q`: Only show Claude's thoughts and actions, minimal logging
- `--show-game-state`: Show full game state information in the logs
- `--show-collision-map`: Show collision map in the logs
- `--log-file PATH`: Write logs to a file at the specified path
- `--no-browser`: Suppress automatically opening the game in a browser window

The agent will automatically open a browser window with the NoVNC interface so you can watch the gameplay in real-time. You can suppress this behavior with the `--no-browser` flag.

## Examples

### Basic Run:
```bash
uv run minimal_agent.py --snapshot-id snap_abc123 --steps 20
```
This will run the agent for 20 steps using the specified snapshot with default logging.

### Quiet Mode (Only Claude's Thoughts and Actions):
```bash
uv run minimal_agent.py --snapshot-id snap_abc123 --steps 20 --quiet
```
This will run the agent showing only Claude's thoughts and actions, with minimal technical logging.

### Detailed Logging with Game State:
```bash
uv run minimal_agent.py --snapshot-id snap_abc123 --steps 20 --verbose --show-game-state
```
This will run the agent with detailed logging including the game state information.

### Maximum Verbosity with Log File:
```bash
uv run minimal_agent.py --snapshot-id snap_abc123 --steps 20 -vv --show-game-state --show-collision-map --log-file pokemon_run.log
```
This will run the agent with maximum verbosity, showing all game state information, collision maps, and writing logs to a file.

### Running Without Browser Auto-open:
```bash
uv run minimal_agent.py --snapshot-id snap_abc123 --steps 20 --no-browser
```
This will run the agent without automatically opening a browser window. The URL for accessing the game will still be printed in the console.
## How to Extend

This minimal agent is designed to be easily extended and customized. Here are several ways you can modify the agent to improve its capabilities:

### Modifying the Agent's Behavior

The agent's behavior is primarily controlled by the `SYSTEM_PROMPT` in the `ServerAgent` class (around line 251). You can modify this prompt to:
- Change the agent's goals and objectives
- Add specific gameplay strategies
- Include Pokemon knowledge or tips
- Adjust the tone or personality

```python
# In minimal_agent.py, modify the SYSTEM_PROMPT (line 251):
SYSTEM_PROMPT = """You are playing Pokemon Red. You can see the game screen and control the game by executing emulator commands.

Your goal is to play through Pokemon Red and eventually defeat the Elite Four. Make decisions based on what you see on the screen.

# Add specialized knowledge or strategies here:
When selecting Pokemon, prioritize having a balanced team with different types.
During battles, consider type advantages and status effects.

Before each action, explain your reasoning briefly, then use the emulator tool to execute your chosen commands."""
```

### Extending Tools and Actions

The agent currently supports two main tools defined in `AVAILABLE_TOOLS` (around line 270):
1. `press_buttons`: For basic Game Boy button control
2. `navigate_to`: For automatic navigation (when `USE_NAVIGATOR` is enabled)

You can extend the agent's capabilities by:
- Adding new tools to the `AVAILABLE_TOOLS` list
- Enhancing existing tools with additional functionality 
- Implementing tool handlers in the `process_tool_call` method (around line 316)

Example of adding a new tool:

```python
# Add a new tool to AVAILABLE_TOOLS (after line 314):
AVAILABLE_TOOLS.append({
    "name": "check_pokemon_team",
    "description": "Get information about your current Pokemon team.",
    "input_schema": {
        "type": "object",
        "properties": {
            "detail_level": {
                "type": "string",
                "enum": ["basic", "detailed"],
                "description": "Level of detail for team information."
            }
        },
        "required": [],
    },
})

# Then implement the handler in process_tool_call (around line 450):
elif tool_name == "check_pokemon_team":
    detail_level = tool_input.get("detail_level", "basic")
    # Implement the logic to get team information
    team_info = "Your team: Charizard Lv.36, Pikachu Lv.28..."
    
    return {
        "type": "tool_result",
        "tool_use_id": tool_call.id,
        "content": [
            {"type": "text", "text": f"Pokemon Team ({detail_level}):\n{team_info}"}
        ],
    }
```

### Configuration Parameters

Key parameters you can adjust (found at the top of the file around line 37):
- `MAX_TOKENS`: Maximum response length
- `MODEL_NAME`: Claude model to use
- `TEMPERATURE`: Controls creativity (higher is more creative)
- `USE_NAVIGATOR`: Enables/disables navigation tool
- `max_history`: Controls conversation summarization threshold

### Example Extensions

Some ideas for extending the agent:
- Add a tool to display Pokemon team status
- Implement battle strategy analysis tools
- Create checkpoints to save game progress
- Add performance metrics or gameplay logging
- Extend the emulator client with advanced ROM manipulation

To implement these extensions, modify the `minimal_agent.py` file and add any necessary helper functions or classes.


