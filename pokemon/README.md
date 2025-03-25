# Morph Cloud Pokémon Emulator Agent

This project demonstrates how to use Morph Cloud to create a fully autonomous agent that can play Pokémon games in a Game Boy emulator. Using Claude 3.7 Sonnet, the agent can see the game through screenshots, interpret the game state, and take actions by controlling the emulator.

**IMPORTANT: This project does not include or distribute any ROM files. You need to provide your own legally obtained ROM files.**

## Getting Started


1. Set your API keys:
   ```
   export ANTHROPIC_API_KEY="your_api_key"
   export MORPH_API_KEY="your_morph_api_key"
   ```
   
2. Install dependencies:
   ```
   pip install anthropic morphcloud
   ```
   
   You can also use `uv run` to automatically download dependencies:
   ```
   uv run emulator/emulator_setup_rom.py --rom path/to/your/rom.gb
   uv run emu_agent.py --snapshot your_snapshot_id --turns 100
   ```

3. Run the emulator setup with your ROM file:
   ```
   python emulator/emulator_setup_rom.py --rom path/to/your/rom.gb
   ```

4. Run the agent using the snapshot ID from the setup:
   ```
   python emu_agent.py --snapshot your_snapshot_id --turns 100
   ```

## Components

### EmuAgent (`emu_agent.py`)

A Python class that creates an autonomous agent to play games through the MorphComputer interface:

- Uses Claude 3.7 Sonnet to interpret game state from screenshots
- Extracts actions (key presses) from Claude's responses
- Executes game actions in the emulator
- Maintains conversation context with screenshots and responses

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

- **State Preservation**: Snapshots preserve the entire memory and filesystem state of a Morph VM. This makes them perfect for easily replicating a game state to attach a new agent seamlessly, without having to manually mess with the RAM state of the emulator. 

- **Snapshot Metadata**: Snapshots are tagged with metadata (like `type: "emulator-complete"` and ROM information) for easy identification and management.

- **Instant Resume**: You can spin up an instance from any snapshot using its ID, allowing you to pick up exactly where you left off. The `EmuAgent` can connect to an existing instance or create one from a snapshot.

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

## Try Morph Cloud

Visit [cloud.morph.so/web](https://cloud.morph.so/web) to get started.

## Legal Notice

This project is provided for educational purposes only. All ROM files must be legally obtained by the user. This project does not distribute, share, or provide any ROM files. Users are responsible for ensuring they have the legal right to use any ROM files with this project.
