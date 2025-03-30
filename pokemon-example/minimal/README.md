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

## Command Line Options

- `--snapshot-id`: (Required) The MorphCloud snapshot ID to run
- `--api-key`: Your MorphCloud API key (defaults to MORPH_API_KEY environment variable)
- `--steps`: Number of agent steps to run (default: 10)
- `--max-history`: Maximum history size before summarizing conversation (default: 30)

## Example

```bash
uv run minimal_agent.py --snapshot-id snap_abc123 --steps 20
```

This will run the agent for 20 steps using the specified snapshot.


