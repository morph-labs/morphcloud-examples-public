import asyncio
import json
import sys
from typing import Optional, Dict, Any, List, Union
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()  # load environment variables from .env

class MCPUnifiedClient:
    def __init__(self, config_path: str = None):
        # Initialize session and client objects
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.anthropic = Anthropic()
        self.config: Dict[str, Any] = {}
        self.active_server: str = None
        self.available_servers: Dict[str, Dict[str, Any]] = {}
        
        if config_path:
            self.load_config(config_path)
    
    def load_config(self, config_path: str):
        """Load server configuration from a JSON file
        
        Args:
            config_path: Path to the config JSON file
        """
        try:
            with open(config_path, 'r') as f:
                self.config = json.load(f)
                self.available_servers = self.config.get("mcpServers", {})
                print(f"Loaded {len(self.available_servers)} server configurations")
        except Exception as e:
            print(f"Error loading config: {str(e)}")
            self.config = {}
            self.available_servers = {}

    async def connect_to_stdio_server(self, server_script_path: str):
        """Connect to an MCP server via stdio
        
        Args:
            server_script_path: Path to the server script (.py or .js)
        """
        is_python = server_script_path.endswith('.py')
        is_js = server_script_path.endswith('.js')
        if not (is_python or is_js):
            raise ValueError("Server script must be a .py or .js file")
            
        command = "python" if is_python else "node"
        server_params = StdioServerParameters(
            command=command,
            args=[server_script_path],
            env=None
        )
        
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))
        
        await self.session.initialize()
        
        # List available tools
        response = await self.session.list_tools()
        tools = response.tools
        return tools

    async def connect_to_sse_server(self, server_url: str):
        """Connect to an MCP server via SSE
        
        Args:
            server_url: URL of the server's SSE endpoint
        """
        # Connect to the SSE endpoint
        streams = await self.exit_stack.enter_async_context(sse_client(server_url))
        self.session = await self.exit_stack.enter_async_context(ClientSession(streams[0], streams[1]))
        
        await self.session.initialize()
        
        # List available tools
        response = await self.session.list_tools()
        tools = response.tools
        return tools

    async def connect_to_configured_server(self, server_name: str):
        """Connect to a server defined in the configuration
        
        Args:
            server_name: Name of the server in the config
        """
        if server_name not in self.available_servers:
            raise ValueError(f"Server '{server_name}' not found in configuration")
        
        server_config = self.available_servers[server_name]
        
        # Check if this is an SSE server (has url field)
        if "url" in server_config:
            print(f"Connecting to SSE server: {server_name}")
            tools = await self.connect_to_sse_server(server_config["url"])
        else:
            # Otherwise, it's a stdio server
            # For stdio, we need to construct the command
            print(f"Connecting to stdio server: {server_name}")
            
            command = server_config.get("command")
            args = server_config.get("args", [])
            env = server_config.get("env")
            
            # If it's a predefined runtime (node/python), set up appropriately
            if "runtime" in server_config:
                runtime = server_config["runtime"]
                if runtime == "node":
                    if command is None:
                        command = "node"
                elif runtime == "python":
                    if command is None:
                        command = "python"
            
            # Create and connect to the server
            server_params = StdioServerParameters(
                command=command,
                args=args,
                env=env
            )
            
            stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
            self.stdio, self.write = stdio_transport
            self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))
            
            await self.session.initialize()
            
            # List available tools
            response = await self.session.list_tools()
            tools = response.tools
        
        self.active_server = server_name
        return tools

    async def process_query(self, query: str) -> str:
        """Process a query using Claude and available tools"""
        if not self.session:
            return "Error: Not connected to any server. Please connect first."
            
        messages = [
            {
                "role": "user",
                "content": query
            }
        ]

        response = await self.session.list_tools()
        available_tools = [{ 
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.inputSchema
        } for tool in response.tools]

        # Initial Claude API call
        response = self.anthropic.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1000,
            messages=messages,
            tools=available_tools
        )

        # Process response and handle tool calls
        tool_results = []
        final_text = []

        for content in response.content:
            if content.type == 'text':
                final_text.append(content.text)
            elif content.type == 'tool_use':
                tool_name = content.name
                tool_args = content.input
                
                # Execute tool call
                result = await self.session.call_tool(tool_name, tool_args)
                tool_results.append({"call": tool_name, "result": result})
                final_text.append(f"[Calling tool {tool_name} with args {tool_args}]")

                # Continue conversation with tool results
                if hasattr(content, 'text') and content.text:
                    messages.append({
                      "role": "assistant",
                      "content": content.text
                    })
                messages.append({
                    "role": "user", 
                    "content": result.content
                })

                # Get next response from Claude
                response = self.anthropic.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=1000,
                    messages=messages,
                )

                final_text.append(response.content[0].text)

        return "\n".join(final_text)

    def list_available_servers(self):
        """List all available servers from the configuration"""
        if not self.available_servers:
            print("No servers configured. Please load a config file first.")
            return
            
        print("\nAvailable servers:")
        for name, config in self.available_servers.items():
            server_type = "SSE" if "url" in config else "stdio"
            print(f"  - {name} ({server_type})")
            
    async def interactive_loop(self):
        """Run an interactive loop for server selection and querying"""
        print("\nMCP Unified Client Started!")
        
        while True:
            if not self.active_server:
                print("\nCommands:")
                print("  load <config_file>   - Load a configuration file")
                print("  list                 - List available servers")
                print("  connect <server>     - Connect to a configured server")
                print("  connect_stdio <path> - Connect to a stdio server script")
                print("  connect_sse <url>    - Connect to an SSE server URL")
                print("  quit                 - Exit the client")
            else:
                print(f"\nConnected to: {self.active_server}")
                print("\nCommands:")
                print("  query <text>         - Send a query to the current server")
                print("  disconnect           - Disconnect from current server")
                print("  quit                 - Exit the client")
            
            try:
                command_line = input("\n> ").strip()
                parts = command_line.split(maxsplit=1)
                
                if not parts:
                    continue
                    
                command = parts[0].lower()
                args = parts[1] if len(parts) > 1 else ""
                
                if command == "quit":
                    break
                    
                elif command == "load":
                    if not args:
                        print("Error: Please specify a config file path")
                        continue
                    self.load_config(args)
                    
                elif command == "list":
                    self.list_available_servers()
                    
                elif command == "connect":
                    if not args:
                        print("Error: Please specify a server name")
                        continue
                    try:
                        tools = await self.connect_to_configured_server(args)
                        print(f"Connected to server with tools: {[tool.name for tool in tools]}")
                    except Exception as e:
                        print(f"Error connecting to server: {str(e)}")
                        
                elif command == "connect_stdio":
                    if not args:
                        print("Error: Please specify a server script path")
                        continue
                    try:
                        tools = await self.connect_to_stdio_server(args)
                        print(f"Connected to server with tools: {[tool.name for tool in tools]}")
                        self.active_server = f"stdio:{Path(args).name}"
                    except Exception as e:
                        print(f"Error connecting to server: {str(e)}")
                        
                elif command == "connect_sse":
                    if not args:
                        print("Error: Please specify a server URL")
                        continue
                    try:
                        tools = await self.connect_to_sse_server(args)
                        print(f"Connected to server with tools: {[tool.name for tool in tools]}")
                        self.active_server = f"sse:{args}"
                    except Exception as e:
                        print(f"Error connecting to server: {str(e)}")
                
                elif command == "disconnect":
                    if self.active_server:
                        await self.cleanup()
                        self.exit_stack = AsyncExitStack()
                        self.session = None
                        print(f"Disconnected from {self.active_server}")
                        self.active_server = None
                    else:
                        print("Not connected to any server")
                
                elif command == "query":
                    if not self.active_server:
                        print("Error: Not connected to any server")
                        continue
                    if not args:
                        print("Error: Please provide a query")
                        continue
                    response = await self.process_query(args)
                    print("\n" + response)
                
                else:
                    print(f"Unknown command: {command}")
                    
            except Exception as e:
                print(f"\nError: {str(e)}")
    
    async def cleanup(self):
        """Clean up resources"""
        await self.exit_stack.aclose()

async def main():
    # Check for a config file argument
    config_path = None
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
        
    client = MCPUnifiedClient(config_path)
    try:
        await client.interactive_loop()
    finally:
        await client.cleanup()

if __name__ == "__main__":
    asyncio.run(main())