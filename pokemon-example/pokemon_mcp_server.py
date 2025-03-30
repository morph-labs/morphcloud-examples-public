import anyio
import sys
import logging
import base64
import io
from typing import Dict, Any, List
import time

import mcp.types as types
from mcp.server.lowlevel import Server
from starlette.applications import Starlette
from starlette.routing import Mount, Route

# Import the emulator client
from agent.client import EmulatorClient

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global client instance
client = None
emulator_ready = False

def check_emulator_status():
    """Check if the emulator is running through the existing server"""
    global client, emulator_ready
    
    try:
        # Create a client to the existing server if not already created
        if client is None:
            client = EmulatorClient(host='127.0.0.1', port=9876)
        
        # Try to get a status check
        status = client.get_game_state()
        
        # If we got a response, the emulator is running
        if status:
            emulator_ready = True
            logger.info("Connected to running emulator successfully")
            return True
        else:
            logger.warning("Emulator is not ready or no ROM loaded")
            return False
    except Exception as e:
        logger.error(f"Error connecting to emulator: {str(e)}")
        return False

async def press_buttons(buttons, wait=True):
    """Press a sequence of buttons on the Game Boy"""
    global client, emulator_ready
    
    if not emulator_ready:
        # Try to connect
        if not check_emulator_status():
            return {"error": "Emulator not ready. Please ensure a ROM is loaded."}
    
    try:
        # Use the client to call the existing server
        response = client.press_buttons(buttons, wait=wait, include_state=True, include_screenshot=True)
        
        # Return the response from the existing server
        return {
            "result": f"Pressed buttons: {', '.join(buttons)}",
            "screenshot": response.get('screenshot', ''),
            "game_state": response.get('game_state', {}).get('game_state', '')
        }
    except Exception as e:
        logger.error(f"Error pressing buttons: {str(e)}")
        return {"error": f"Error: {str(e)}"}

async def navigate_to(row, col):
    """Navigate to a specific position on the map grid"""
    global client, emulator_ready
    
    if not emulator_ready:
        # Try to connect
        if not check_emulator_status():
            return {"error": "Emulator not ready. Please ensure a ROM is loaded."}
    
    try:
        # Use the client to call the existing server
        response = client.navigate(row, col, include_state=True, include_screenshot=True)
        
        status = response.get('status', 'Unknown status')
        path = response.get('path', [])
        
        if path:
            result = f"Navigation successful: followed path with {len(path)} steps"
        else:
            result = f"Navigation failed: {status}"
        
        # Return the response from the existing server
        return {
            "result": result,
            "screenshot": response.get('screenshot', ''),
            "game_state": response.get('game_state', {}).get('game_state', '')
        }
    except Exception as e:
        logger.error(f"Error navigating: {str(e)}")
        return {"error": f"Error: {str(e)}"}

async def get_screenshot():
    """Get the current game screenshot"""
    global client, emulator_ready
    
    if not emulator_ready:
        # Try to connect
        if not check_emulator_status():
            return {"error": "Emulator not ready. Please ensure a ROM is loaded."}
    
    try:
        # Get screenshot as base64
        screenshot_b64 = client.get_screenshot_base64()
        
        return {
            "screenshot": screenshot_b64
        }
    except Exception as e:
        logger.error(f"Error getting screenshot: {str(e)}")
        return {"error": f"Error: {str(e)}"}

async def get_game_state():
    """Get the current game state information"""
    global client, emulator_ready
    
    if not emulator_ready:
        # Try to connect
        if not check_emulator_status():
            return {"error": "Emulator not ready. Please ensure a ROM is loaded."}
    
    try:
        # Get game state directly from client
        state_data = client.get_game_state()
        return state_data
    except Exception as e:
        logger.error(f"Error getting game state: {str(e)}")
        return {"error": f"Error: {str(e)}"}

def main():
    """Main function to initialize and run the server"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Pokemon Emulator MCP Server")
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind the server to')
    parser.add_argument('--port', type=int, default=8000, help='Port to run the server on')
    
    args = parser.parse_args()
    
    # Create Server instance
    app = Server("pokemon-emulator")
    
    # Register tool calls
    @app.call_tool()
    async def call_tool(
        name: str, arguments: dict
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Implementation of tool calling"""
        try:
            if name == "press_buttons":
                buttons = arguments.get("buttons", [])
                wait = arguments.get("wait", True)
                result = await press_buttons(buttons, wait)
            elif name == "navigate_to":
                row = arguments.get("row", 0)
                col = arguments.get("col", 0)
                result = await navigate_to(row, col)
            elif name == "get_screenshot":
                result = await get_screenshot()
            elif name == "get_game_state":
                result = await get_game_state()
            else:
                result = {"error": f"Unknown tool: {name}"}
            
            # Convert dict to JSON string to ensure proper handling
            import json
            return [types.TextContent(type="text", text=json.dumps(result))]
        except Exception as e:
            logger.error(f"Error in call_tool: {str(e)}")
            return [types.TextContent(type="text", text=json.dumps({"error": str(e)}))]
    
    # Register tool listing
    @app.list_tools()
    async def list_tools() -> list[types.Tool]:
        """List available tools"""
        return [
            types.Tool(
                name="press_buttons",
                description="Press a sequence of buttons on the Game Boy",
                inputSchema={
                    "type": "object",
                    "required": ["buttons"],
                    "properties": {
                        "buttons": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["a", "b", "start", "select", "up", "down", "left", "right"]
                            },
                            "description": "List of buttons to press in sequence"
                        },
                        "wait": {
                            "type": "boolean",
                            "description": "Whether to wait for a brief period after pressing each button",
                            "default": True
                        }
                    }
                }
            ),
            types.Tool(
                name="navigate_to",
                description="Automatically navigate to a position on the map grid",
                inputSchema={
                    "type": "object",
                    "required": ["row", "col"],
                    "properties": {
                        "row": {
                            "type": "integer",
                            "description": "The row coordinate to navigate to (0-8)"
                        },
                        "col": {
                            "type": "integer",
                            "description": "The column coordinate to navigate to (0-9)"
                        }
                    }
                }
            ),
            types.Tool(
                name="get_screenshot",
                description="Get the current game screenshot",
                inputSchema={
                    "type": "object",
                    "properties": {}
                }
            ),
            types.Tool(
                name="get_game_state",
                description="Get the current game state information",
                inputSchema={
                    "type": "object",
                    "properties": {}
                }
            )
        ]
    
    # Set up SSE transport
    from mcp.server.sse import SseServerTransport
    sse = SseServerTransport("/messages/")
    
    async def handle_sse(request):
        """Handle SSE connection setup"""
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await app.run(
                streams[0], streams[1], app.create_initialization_options()
            )
    
    # Create Starlette app
    starlette_app = Starlette(
        debug=True,
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )
    
    # Try to connect to the existing server
    logger.info("Attempting to connect to the Pokemon emulator server...")
    
    # Allow some time for the emulator server to start up if needed
    max_attempts = 5
    for attempt in range(max_attempts):
        if check_emulator_status():
            break
        logger.info(f"Attempt {attempt+1}/{max_attempts}: Waiting for emulator to be ready...")
        time.sleep(3)
    
    # Start Uvicorn server
    import uvicorn
    logger.info(f"Starting Pokemon Emulator MCP Server on {args.host}:{args.port}")
    logger.info(f"SSE endpoint available at http://{args.host}:{args.port}/sse")
    uvicorn.run(starlette_app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()
