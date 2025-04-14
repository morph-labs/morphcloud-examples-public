# NextJS Devbox Example

This guide shows you how to quickly spin up a Next.js devbox using [Morph Cloud](https://cloud.morph.so/developers).

You'll need to use this [magic link](https://cloud.morph.so/web/nextjs) to get the snapshot that this example requires - you'll also get 1000 free credits!

## Quick Start

```bash
git clone https://github.com/morph-labs/morphcloud-examples-public

cd morphcloud-examples-public/nextjs-devbox

# Install uv (fast Python package installer)
# On macOS and Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install required packages
uv add --script nextjs_devbox.py morphcloud rich

# https://cloud.morph.so/web/keys
export MORPH_API_KEY=...

uv run nextjs_devbox.py
```

The example script (`nextjs_devbox.py`) is included in this repository. It creates a Computer instance, provides desktop access, navigates to a NextJS site, and starts an MCP server.

## Connect with MCP Clients

The Computer can easily connect to any MCP-compatible client:

```python
# Get a Computer instance
from morphcloud.computer import Computer
computer = Computer.new()

# Start the MCP server (returns the connection URL)
mcp_url = computer.start_mcp_server(port=8888)
print(f"MCP URL: {mcp_url}")
```

Use this URL to connect with:
- **[Cursor](https://cursor.com)**
- **[Windsurf](https://windsurf.com/editor)**
- **[Claude Desktop](https://claude.ai/download/)**
- Any other MCP-compatible client

## Overview

Morph Computer provides a programmatically controlled virtual environment with browser automation, code execution, and desktop interaction. Access everything through a clean Python API or connect AI assistants via the built-in Model Context Protocol (MCP) server.

The Computer combines VM functionality with high-level APIs for browser control, system operations, and sandboxed Python execution. Designed for simplicity, it enables automated testing, development workflows, and AI-assisted programming.

## Example Walkthrough

The demo script shows a complete Computer workflow:

1. **Start Computer**: Creates a new cloud-based Computer instance with a visual progress indicator
2. **Access Desktop**: Displays the URL for direct GUI access to the Computer
3. **Browser Control**: Navigates to a NextJS hackathon site, demonstrating browser automation
4. **MCP Server**: Starts an MCP server on port 8888 for AI assistant connections
5. **Interaction**: Keeps the Computer running until manual shutdown
6. **Cleanup**: Automatically shuts down the Computer when exiting

## API Basics

```python
from morphcloud.computer import Computer

with Computer.new() as computer:
    # Browser automation
    computer.browser.goto("https://example.com")
    
    # Start MCP server for AI connections
    server_url = computer.start_mcp_server()
```

MCP Tools available:
- `desktop` - Mouse, keyboard, screenshots
- `browser` - Navigation, interaction, HTML inspection
- `sandbox` - Python execution, Jupyter notebooks
