# Claude Plays Pokémon Hackathon Quickstart Guide

## Prerequisites

-   Python 3.11 or higher
-   UV package manager ([Installation Guide](https://docs.astral.sh/uv/getting-started/installation/))

## Setup Instructions

### 1. Join the Event

-   Navigate to [https://cloud.morph.so/web/event?event=pokemon](https://cloud.morph.so/web/event?event=pokemon)
-   Sign up with your email or Google account

### 2. Clone the Repository

```bash
git clone https://github.com/morph-labs/morphcloud-examples-public.git
cd morphcloud-examples-public/pokemon-example

```

### 3. Set Up Python Environment

```bash
# Create a virtual environment
uv venv

# Activate the virtual environment
source .venv/bin/activate  # On Unix/MacOS
# OR
.\.venv\Scripts\activate   # On Windows

# Install dependencies
uv pip install -r requirements.txt

```

### 4. Find Your Snapshot ID

-   Open your Morph Cloud Console
-   Navigate to the Snapshots tab
-   Copy the newest snapshot ID

### 5. Run the Agent

```bash
export MORPH_API_KEY="YOUR API KEY"
export ANTHROPIC_API_KEY="YOUR API KEY"
uv run pokemon_agent_trajectory.py --snapshot-id YOUR_SNAPSHOT_ID --port 9999
uv run trajectory_driver.py --api-port 9999 --ui-port 8080
```

### 6. Watch The Agent Play

-   Go to your [Morph Cloud Console](https://cloud.morph.so/web/instances)
-   Find the newly created instance
-   Click the Details icon (eye)
-   Navigate to the VNC service link to watch the agent play Pokémon

