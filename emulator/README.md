# Morph Cloud Pokémon Emulator Agent

This project demonstrates how to use Morph Cloud to create a fully autonomous agent that can play Pokémon games in a Game Boy emulator. Using Claude 3.7 Sonnet, the agent can see the game through screenshots, interpret the game state, and take actions by controlling the emulator.

**IMPORTANT: This project does not include or distribute any ROM files. You need to provide your own legally obtained ROM files.**

## Getting Started

### Requirements

- Python 3.10 or higher is required

### Setup Environment

#### Option 1: Using `uv` (recommended)

The scripts in this project have dependencies embedded in comments, so `uv run` will automatically download them for you.

1. Install `uv` by following the [official installation guide](https://docs.astral.sh/uv/getting-started/installation/)

2. Run the scripts directly with `uv`:
   ```bash
   uv run emulator_setup_rom.py --rom path/to/your/rom.gb
   uv run emu_agent.py --snapshot your_snapshot_id
   ```

#### Option 2: Using your preferred virtual environment

1. Create a Python virtual environment:
   ```bash
   # Using venv
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   
   # OR using conda
   conda create -n emulator python=3.10
   conda activate emulator
   ```

2. Install dependencies:
   ```bash
   # Using the requirements.txt file
   pip install -r requirements.txt
   
   # OR manually
   pip install anthropic morphcloud python-dotenv
   ```

### Configuration

1. Set up your API keys by either:

   **Option A: Using environment variables**
   ```bash
   export ANTHROPIC_API_KEY="your_api_key"
   export MORPH_API_KEY="your_morph_api_key"
   ```

   **Option B: Using a .env file (recommended)**
   ```bash
   # Copy the example file
   cp .env.example .env
   
   # Edit the .env file with your actual API keys
   nano .env  # or use any text editor
   ```

2. **Getting API Keys:**
   - **Morph API Key**: Generate your API key at [cloud.morph.so/web/keys](https://cloud.morph.so/web/keys)
   - **Anthropic API Key**: Get your API key from [Anthropic Console](https://console.anthropic.com/)

3. **Learn More:**
   - [Morph Cloud Documentation](https://cloud.morph.so/docs/documentation/overview) - Learn how to use Morph Cloud
   - [Morph Python SDK](https://github.com/morph-labs/morph-python-sdk) - Documentation for the Python SDK

### Running the Emulator

1. Run the emulator setup with your ROM file:
   ```bash
   # If using uv:
   uv run emulator_setup_rom.py --rom path/to/your/rom.gb
   
   # If using a virtual environment:
   python emulator_setup_rom.py --rom path/to/your/rom.gb
   ```
   The script will output a snapshot ID when complete. Make note of this ID.

2. Run the agent using the snapshot ID from the setup:
   ```bash
   # If using uv:
   uv run emu_agent.py --snapshot your_snapshot_id --turns 100
   
   # If using a virtual environment:
   python emu_agent.py --snapshot your_snapshot_id --turns 100
   ```

## Components

### EmuAgent (`emu_agent.py`)

A Python class that creates an autonomous agent to play games through the MorphComputer interface:

- Uses Claude 3.7 Sonnet to interpret game state from screenshots
- Extracts actions (key presses) from Claude's responses
- Executes game actions in the emulator
- Maintains conversation context with screenshots and responses
- Features a configurable gameplay loop

```python
# Example: Initialize and run the agent with a specific snapshot
with EmuAgent(snapshot_id="your_snapshot_id", verbose=True) as agent:
    agent.play(max_turns=100)
```

### MorphComputer (`morph_computer.py`)

A foundation class for interacting with cloud-based VM environments:

- Creates and manages VM instances (from scratch or snapshots)
- Provides desktop interaction methods (mouse, keyboard, screenshots)
- Handles service configuration and exposure
- Implements retry mechanisms and error handling
- Supports VM lifecycle management and snapshots

### Emulator Setup (`emulator/emulator_setup_rom.py`)

A setup script that:

- Sets up the emulator environment in a Morph Cloud VM
- Allows uploading ROM files via SFTP
- Configures BizHawk to automatically load a specified ROM
- Creates a dedicated service for running the emulator
- Creates snapshots for easy reuse
- Provides detailed progress feedback

## Morph VM Snapshotting

This project leverages Morph Cloud's powerful VM snapshot capabilities:

- **State Preservation**: Snapshots preserve the entire VM state, including installed software, configurations, and in this case, the loaded ROM and emulator state. This makes them perfect for saving game progress or different gameplay states.

- **Snapshot Metadata**: Snapshots are tagged with metadata (like `type: "emulator-complete"` and ROM information) for easy identification and management.

- **Instant Resume**: You can create a VM instance from any snapshot using its ID, allowing you to pick up exactly where you left off. The `EmuAgent` can connect to an existing instance or create one from a snapshot.

```python
# Example: Creating a snapshot of your current game state
computer = MorphComputer(instance_id="your_instance_id")
snapshot = computer.create_snapshot(metadata={
    "type": "game-progress",
    "description": "Pokémon Red - After defeating Brock"
})
print(f"Snapshot created: {snapshot.id}")

# Later, continue from this exact state
with EmuAgent(snapshot_id=snapshot.id) as agent:
    agent.play(max_turns=100)
```

## Resources

- **Morph Cloud**: [cloud.morph.so/web](https://cloud.morph.so/web) - Sign up for Morph Cloud
- **API Keys**: [cloud.morph.so/web/keys](https://cloud.morph.so/web/keys) - Manage your Morph Cloud API keys
- **Documentation**: [cloud.morph.so/docs](https://cloud.morph.so/docs/documentation/overview) - Comprehensive Morph Cloud documentation
- **SDK**: [GitHub: morph-python-sdk](https://github.com/morph-labs/morph-python-sdk) - Learn more about the Python SDK used in this project

## Legal Notice

This project is provided for educational purposes only. All ROM files must be legally obtained by the user. This project does not distribute, share, or provide any ROM files. Users are responsible for ensuring they have the legal right to use any ROM files with this project.
