import base64
import copy
import io
import logging
import os
import asyncio
from typing import Optional, List, Dict, Any
from contextlib import AsyncExitStack
from PIL import Image

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from anthropic import Anthropic

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are playing Pokemon Red. You can see the game screen and control the game by executing emulator commands.

Your goal is to play through Pokemon Red and eventually defeat the Elite Four. Make decisions based on what you see on the screen.

Before each action, explain your reasoning briefly, then use the available tools to execute your chosen commands.

The conversation history may occasionally be summarized to save context space. If you see a message labeled "CONVERSATION HISTORY SUMMARY", this contains the key information about your progress so far. Use this information to maintain continuity in your gameplay."""

SUMMARY_PROMPT = """I need you to create a detailed summary of our conversation history up to this point. This summary will replace the full conversation history to manage the context window.

Please include:
1. Key game events and milestones you've reached
2. Important decisions you've made
3. Current objectives or goals you're working toward
4. Your current location and Pokémon team status
5. Any strategies or plans you've mentioned

The summary should be comprehensive enough that you can continue gameplay without losing important context about what has happened so far."""

class MCPServerAgent:
    def __init__(self, server_script_path: str, max_history=60, model_name="claude-3-5-sonnet-20241022", temperature=0.7, max_tokens=1000):
        """Initialize the MCP server agent.

        Args:
            server_script_path: Path to the MCP server script
            max_history: Maximum number of messages in history before summarization
            model_name: The Claude model to use
            temperature: Temperature for generation
            max_tokens: Maximum tokens for generation
        """
        # Initialize session and client objects
        self.exit_stack = AsyncExitStack()
        self.session: Optional[ClientSession] = None
        self.anthropic = Anthropic()
        self.server_script_path = server_script_path
        
        self.running = True
        self.message_history = [{"role": "user", "content": "You may now begin playing."}]
        self.max_history = max_history
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def connect_to_server(self):
        """Connect to the MCP server"""
        is_python = self.server_script_path.endswith('.py')
        is_js = self.server_script_path.endswith('.js')
        if not (is_python or is_js):
            raise ValueError("Server script must be a .py or .js file")
            
        command = "python" if is_python else "node"
        server_params = StdioServerParameters(
            command=command,
            args=[self.server_script_path],
            env=None
        )
        
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))
        
        await self.session.initialize()
        
        # List available tools
        response = await self.session.list_tools()
        tools = response.tools
        logger.info(f"Connected to server with tools: {[tool.name for tool in tools]}")
        return True

    async def process_message(self):
        """Process a single message with the agent."""
        messages = copy.deepcopy(self.message_history)

        # Get available tools from MCP server
        response = await self.session.list_tools()
        available_tools = [{ 
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.inputSchema
        } for tool in response.tools]

        # Initial Claude API call
        response = self.anthropic.messages.create(
            model=self.model_name,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=available_tools,
            temperature=self.temperature
        )

        logger.info(f"Response usage: {response.usage}")

        # Extract tool calls
        tool_calls = [
            block for block in response.content if block.type == "tool_use"
        ]

        # Display the model's reasoning
        for block in response.content:
            if block.type == "text":
                logger.info(f"[Text] {block.text}")
            elif block.type == "tool_use":
                logger.info(f"[Tool] Using tool: {block.name}")

        # Process tool calls
        if tool_calls:
            # Add assistant message to history
            assistant_content = []
            for block in response.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append({"type": "tool_use", **dict(block)})
            
            self.message_history.append(
                {"role": "assistant", "content": assistant_content}
            )
            
            # Process tool calls with MCP
            for tool_call in tool_calls:
                tool_name = tool_call.name
                tool_input = tool_call.input
                
                logger.info(f"Calling tool: {tool_name} with input: {tool_input}")
                
                # Execute tool call through MCP
                result = await self.session.call_tool(tool_name, tool_input)
                
                # Format the tool result for the message history
                tool_result_content = []
                
                # Add text result
                tool_result_content.append({
                    "type": "text", 
                    "text": result.content.get("result", f"Used tool: {tool_name}")
                })
                
                # Add screenshot if available
                if "screenshot" in result.content and result.content["screenshot"]:
                    tool_result_content.append({
                        "type": "text",
                        "text": "\nHere is a screenshot of the screen after your action:"
                    })
                    tool_result_content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": result.content["screenshot"],
                        },
                    })
                
                # Add game state if available
                if "game_state" in result.content and result.content["game_state"]:
                    tool_result_content.append({
                        "type": "text",
                        "text": f"\nGame state information from memory after your action:\n{result.content['game_state']}"
                    })
                
                # Add formatted tool result to message history
                self.message_history.append({
                    "role": "user",
                    "content": tool_result_content
                })

            # Check if we need to summarize the history
            if len(self.message_history) >= self.max_history:
                await self.summarize_history()
                
            return True
        
        return False

    async def summarize_history(self):
        """Generate a summary of the conversation history and replace the history with the summary."""
        logger.info(f"[Agent] Generating conversation summary...")
        
        # Get a new screenshot using the MCP tool
        screenshot_result = await self.session.call_tool("get_screenshot", {})
        screenshot_b64 = screenshot_result.content.get("screenshot", "")
        
        # Create messages for the summarization request
        messages = copy.deepcopy(self.message_history)
        
        messages.append({
            "role": "user",
            "content": SUMMARY_PROMPT
        })
        
        # Get summary from Claude
        response = self.anthropic.messages.create(
            model=self.model_name,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT,
            messages=messages,
            temperature=self.temperature
        )
        
        # Extract the summary text
        summary_text = " ".join([block.text for block in response.content if block.type == "text"])
        
        logger.info(f"[Agent] Game Progress Summary:")
        logger.info(f"{summary_text}")
        
        # Replace message history with just the summary
        self.message_history = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"CONVERSATION HISTORY SUMMARY (representing {self.max_history} previous messages): {summary_text}"
                    },
                    {
                        "type": "text",
                        "text": "\n\nCurrent game screenshot for reference:"
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
                        "text": "You were just asked to summarize your playthrough so far, which is the summary you see above. You may now continue playing by selecting your next action."
                    },
                ]
            }
        ]
        
        logger.info(f"[Agent] Message history condensed into summary.")

    async def run(self, num_steps=1):
        """Main agent loop.

        Args:
            num_steps: Number of steps to run for
        """
        logger.info(f"Starting agent loop for {num_steps} steps")

        steps_completed = 0
        while self.running and steps_completed < num_steps:
            try:
                result = await self.process_message()
                if result:
                    steps_completed += 1
                    logger.info(f"Completed step {steps_completed}/{num_steps}")
                else:
                    logger.warning("No tool calls were made in this step")
            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt, stopping")
                self.running = False
            except Exception as e:
                logger.error(f"Error in agent loop: {e}")
                raise e

        if not self.running:
            await self.cleanup()

        return steps_completed

    async def cleanup(self):
        """Clean up resources."""
        await self.exit_stack.aclose()

async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="MCP Server Agent for Pokemon Red")
    parser.add_argument('--server', required=True, help='Path to MCP server script')
    parser.add_argument('--steps', type=int, default=10, help='Number of steps to run')
    parser.add_argument('--max-history', type=int, default=30, help='Maximum history size before summarizing')
    parser.add_argument('--model', default="claude-3-5-sonnet-20241022", help='Claude model to use')
    
    args = parser.parse_args()

    # Create and run agent
    try:
        agent = MCPServerAgent(
            server_script_path=args.server,
            max_history=args.max_history,
            model_name=args.model
        )
        
        # Connect to server
        await agent.connect_to_server()
        
        # Run agent
        steps_completed = await agent.run(num_steps=args.steps)
        logger.info(f"Agent completed {steps_completed} steps")
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, stopping")
    except Exception as e:
        logger.error(f"Error: {e}")
        raise
    finally:
        if 'agent' in locals():
            await agent.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
