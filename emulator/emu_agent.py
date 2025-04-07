# /// script
# dependencies = [
# "morphcloud",
# "anthropic",
# "python-dotenv"
# ]
# ///

import base64
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import anthropic
from dotenv import load_dotenv
# Import MorphComputer from local file
from morph_computer import MorphComputer

# Load environment variables from .env file if it exists
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("EmuAgent")


class EmuAgent:
    """
    A fully autonomous agent that uses Claude 3.7 Sonnet to play games through
    the MorphComputer interface, automatically taking screenshots after each action.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-3-7-sonnet-latest",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        computer: Optional[MorphComputer] = None,
        snapshot_id: Optional[str] = None,
        instance_id: Optional[str] = None,
        setup_computer: bool = True,
        verbose: bool = True,
    ):
        """Initialize the EmuAgent."""
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("Anthropic API key is required")

        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.verbose = verbose

        # Initialize Anthropic client
        self.client = anthropic.Anthropic(api_key=self.api_key)

        # Initialize computer if needed
        self.computer = computer
        if self.computer is None and setup_computer:
            if instance_id:
                self.log(f"Connecting to existing instance: {instance_id}")
                self.computer = MorphComputer(instance_id=instance_id)
            elif snapshot_id:
                self.log(f"Creating new computer from snapshot: {snapshot_id}")
                self.computer = MorphComputer(snapshot_id=snapshot_id)
            else:
                self.log("Creating new computer from default snapshot")
                self.computer = MorphComputer()

        # Conversation history
        self.messages = []
        self.system_prompt = """
You are an AI game-playing assistant that can see and interact with a game through screenshots.
You'll receive screenshots of the game state and can take actions by pressing keys.

CAPABILITIES:
- Observe the game through screenshots
- Press specific keys to control the game

AVAILABLE KEYS (based on what you see in the interface):
- "UP" (arrow up)
- "DOWN" (arrow down)
- "LEFT" (arrow left)
- "RIGHT" (arrow right)
- "ENTER" (start)
- "SPACE" (select)
- "Z" (A)
- "X" (B)

HOW THE SYSTEM WORKS:
1. You'll receive a screenshot of the game
2. Analyze the game state and decide on the best action
3. Specify the key to press using the action format below
4. The system will press the key and automatically take a new screenshot
5. The new screenshot will be sent to you to decide on your next action
6. This loop continues until the game session ends

To specify a key press, use this format:
```action
{
  "action_type": "keypress",
  "keys": ["Z"]
}
```

You can also wait if needed:
```action
{
  "action_type": "wait",
  "ms": 1000
}
```

As you play, explain your reasoning and strategy. Describe what you observe in the game and why you're making specific moves.
"""
        self.init_conversation()

    def init_conversation(self):
        """Initialize or reset the conversation history."""
        self.messages = []  # Empty list, system prompt is passed separately

    def log(self, message: str):
        """Log a message if verbose mode is enabled."""
        if self.verbose:
            logger.info(message)

    def __enter__(self):
        """Context manager entry."""
        if self.computer:
            self.computer.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self.computer:
            self.computer.__exit__(exc_type, exc_val, exc_tb)

    def take_screenshot(self) -> str:
        """Take a screenshot and return the encoded image data."""
        self.log("Taking screenshot...")
        try:
            return self.computer.screenshot()
        except Exception as e:
            self.log(f"Error taking screenshot: {e}")
            return None

    def take_save_state(self) -> str:
        """Take a save state and return the encoded Core.bin data."""
        self.log("Taking save state...")
        try:
            return self.computer.take_save_state()
        except Exception as e:
            self.log(f"Error taking save state: {e}")
            return None

    def add_screenshot_to_conversation(self) -> None:
        """Take a screenshot and add it to the conversation as a tool result."""
        try:
            screenshot_data = self.take_screenshot()
            if screenshot_data:
                # Add screenshot as a tool result instead of a user message
                if len(self.messages) > 0 and self.messages[-1]["role"] == "assistant":
                    # If the last message was from the assistant, add the screenshot as a user message
                    self.messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Screenshot result from your last action:",
                                },
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": screenshot_data,
                                    },
                                },
                            ],
                        }
                    )
                else:
                    # For the initial screenshot or if conversation flow needs correction
                    self.messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Here's the current game state. What action will you take next?",
                                },
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": screenshot_data,
                                    },
                                },
                            ],
                        }
                    )
                self.log("Added screenshot as tool result")
            else:
                self.log("Failed to add screenshot - no data")
        except Exception as e:
            self.log(f"Error adding screenshot: {e}")

    def add_save_state_to_conversation(self) -> None:
        """Take a save state and add the Core.bin data to the conversation."""
        try:
            save_state_data = self.take_save_state()
            if save_state_data:
                message = {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Here's the emulator save state data (Core.bin in base64 format):",
                        },
                        {"type": "text", "text": save_state_data},
                    ],
                }
                self.messages.append(message)
                self.log("Added save state data to conversation")
            else:
                self.log("Failed to add save state - no data")
        except Exception as e:
            self.log(f"Error adding save state: {e}")

    def execute_action(self, action_type: str, **params) -> bool:
        """Execute an action on the desktop."""
        self.log(f"Executing action: {action_type} with params: {params}")
        try:
            if action_type == "keypress":
                self.computer.keypress(params["keys"], params.get("press_ms", 500))
            elif action_type == "wait":
                self.computer.wait(params.get("ms", 1000))
            else:
                self.log(f"Unsupported action type: {action_type}")
                return False
            return True
        except Exception as e:
            self.log(f"Error executing action {action_type}: {e}")
            return False

    def play(
        self,
        initial_prompt: str = "Analyze this game and start playing",
        max_turns: int = 100,
        max_no_action_turns: int = 3,
        include_save_states: bool = False,
    ) -> str:
        """
        Start a fully autonomous gameplay session.

        Args:
            initial_prompt: Initial instruction to Claude
            max_turns: Maximum number of turns to play
            max_no_action_turns: Maximum consecutive turns without actions before stopping
            include_save_states: Whether to include save state data with each turn

        Returns:
            Final response from Claude
        """
        self.log(f"Starting autonomous gameplay with prompt: {initial_prompt}")

        # Initialize conversation with just the initial prompt
        self.messages = [{"role": "user", "content": initial_prompt}]

        # Add initial screenshot as tool result
        self.add_screenshot_to_conversation()

        # Optionally add initial save state
        if include_save_states:
            self.add_save_state_to_conversation()

        # Get Claude's first response
        response = self.get_next_action()
        last_response = response

        # Process action loop
        no_action_count = 0
        for turn in range(max_turns):
            self.log(f"Turn {turn+1}/{max_turns}")

            # Check if Claude wants to take an action
            action = self.extract_action(response)

            if not action:
                # No action requested, count it and potentially break
                no_action_count += 1
                self.log(
                    f"No action requested ({no_action_count}/{max_no_action_turns})"
                )

                if no_action_count >= max_no_action_turns:
                    self.log("Maximum no-action turns reached, ending gameplay")
                    break

                # Prompt Claude again for an action
                self.messages.append(
                    {
                        "role": "user",
                        "content": "Please specify an action to take in the game using the ```action{...}``` format.",
                    }
                )
                response = self.get_next_action()
                last_response = response
                continue

            # Reset no-action counter when an action is found
            no_action_count = 0

            # Execute the action
            self.execute_action(**action)

            # IMPORTANT: Always take a new screenshot after action
            self.add_screenshot_to_conversation()

            # Optionally add save state after each action
            if include_save_states:
                self.add_save_state_to_conversation()

            # Get Claude's next step
            response = self.get_next_action()
            last_response = response

        return last_response

    def get_next_action(self) -> str:
        """Get Claude's next action based on the conversation so far."""
        try:
            self.log("Getting next action from Claude...")

            # For newer Anthropic SDK versions (>=0.5.0)
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=self.system_prompt,
                messages=self.messages,
            )

            response_text = response.content[0].text
            self.log(f"Claude response: {response_text[:100]}...")

            # Add to conversation history
            self.messages.append({"role": "assistant", "content": response_text})

            return response_text

        except Exception as e:
            self.log(f"Error getting response from Claude: {e}")
            return f"Error: {str(e)}"

    def extract_action(self, response: str) -> Optional[Dict[str, Any]]:
        """Extract an action from Claude's response."""
        # Look for action blocks
        action_match = re.search(r"```action\n(.*?)\n```", response, re.DOTALL)

        if not action_match:
            return None

        try:
            action_json = action_match.group(1).strip()
            action = json.loads(action_json)
            return action
        except json.JSONDecodeError:
            self.log(f"Failed to parse action JSON: {action_match.group(1)}")
            return None

    def close(self):
        """Clean up resources used by the agent."""
        if hasattr(self, "computer") and self.computer:
            try:
                self.computer.cleanup()
                self.log("Cleaned up computer resources")
            except Exception as e:
                self.log(f"Error cleaning up computer: {e}")


# Simple command-line interface
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the EmuAgent")
    parser.add_argument("--snapshot", "-s", help="Snapshot ID to use")
    parser.add_argument("--instance", "-i", help="Instance ID to use")
    parser.add_argument(
        "--turns", "-t", type=int, default=100, help="Max turns to play"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )
    parser.add_argument(
        "--save-states",
        action="store_true",
        help="Include save state data with each turn",
    )

    args = parser.parse_args()

    with EmuAgent(
        snapshot_id=args.snapshot, instance_id=args.instance, verbose=args.verbose
    ) as agent:
        agent.play(max_turns=args.turns, include_save_states=args.save_states)
