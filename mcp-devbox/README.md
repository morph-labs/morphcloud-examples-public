# Remote MCP Server Setup with Morph Cloud 

This tool helps you set up one or more Model Context Protocol (MCP) servers on Morph Cloud VMs quickly and easily. It supports creating new VMs or adding servers to existing ones, with intelligent port management and service naming.

## Features

- **Multi-Server Support**: Run multiple MCP servers on a single VM with unique service names and ports
- **Existing VM Integration**: Add new servers to existing VMs without starting from scratch
- **Intelligent Port Management**: Automatically find available ports to avoid conflicts
- **Service Naming**: Generate unique service names to prevent collisions
- **Comprehensive Metadata**: Track all servers in VM snapshots for easy restoration
- **Interactive Configuration**: Customize each server's settings during setup
- **Dependency Checking**: Verify and install required dependencies only when needed
- **Error Handling**: Gracefully recover from failures during multi-server setup

## Requirements

- Python 3.11 or newer
- [Morph Cloud CLI](https://cloud.morph.so/developers) installed and configured
- A Morph Cloud account with API key configured
- [Get Early Access](https://docs.google.com/forms/d/1F8JeJEJWwP5ywfmGN_N-r3MBNHVzry7k1Dg_2YEex28/viewform?edit_requested=true)

## Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/morphcloud/mcp-devbox.git
   cd mcp-devbox
   ```

2. Install dependencies:
   ```bash
   pip install morphcloud requests
   ```

## Usage

### Basic Usage

To create a new VM with a single MCP server:

```bash
python setup_mcp.py
```

This will walk you through selecting an MCP server type from the available options and configuring it on a new VM.

### Multiple Servers

To set up multiple MCP servers on a single VM:

```bash
python setup_mcp.py --multi --count 3
```

This will guide you through setting up 3 MCP servers, each with its own unique service name and port.

### Connect to Existing VM

To add a new MCP server to an existing VM:

```bash
python setup_mcp.py --instance-id <vm-instance-id>
```

The script will detect any existing MCP services running on the VM and ensure new services use unique names and available ports.

### Using Configuration Files

To set up a server using a pre-defined configuration file:

```bash
python setup_mcp.py --config example_config.json
```

See [example_config.json](example_config.json) for an example configuration.

### Additional Options

- `--vcpus <count>`: Number of vCPUs for the VM (default: 2)
- `--memory <mb>`: Memory in MB for the VM (default: 2048)
- `--disk-size <mb>`: Disk size in MB for the VM (default: 4096)
- `--base-port <port>`: Starting port number for port allocation (default: 3000)
- `--all-cors`: Enable CORS for all servers

## Examples

### Create a Basic MCP Server VM

```bash
python setup_mcp.py --vcpus 2 --memory 2048 --disk-size 4096
```

### Set Up Multiple Servers with Specific Configurations

```bash
python setup_mcp.py --multi --count 2
```

### Add Server to Existing VM with Custom Port

```bash
python setup_mcp.py --instance-id abc123 --base-port 4000
```

### Set Up Multiple Servers with CORS Enabled

```bash
python setup_mcp.py --multi --count 3 --all-cors
```

## How It Works

1. **VM Initialization**: Either creates a new VM or connects to an existing one
2. **Dependency Check**: Verifies required dependencies (Node.js) are installed
3. **Service Detection**: If using an existing VM, detects running MCP services
4. **Server Setup**: For each server:
   - Selects MCP server package (interactively or from config)
   - Finds MCP configuration from repository README or fallback
   - Customizes configuration with user input
   - Generates unique service name
   - Finds available port
   - Sets up systemd service with supergateway for SSE conversion
   - Exposes HTTP service
5. **Snapshot Creation**: Creates a snapshot with metadata for all servers
6. **Connection Info**: Displays connection information for all servers

## Client Connection

After setting up the servers, you can connect to them using any MCP client that supports SSE transport, including:

```python
# Example using the official MCP Python SDK with SSE endpoint
from mcp.client.sse import sse_client
from mcp import ClientSession

async with sse_client("http://your-server-url/sse") as streams:
    async with ClientSession(streams[0], streams[1]) as session:
        # Use the session to call tools...
```

See [client_sse.py](client_sse.py) for a complete client example.

## Troubleshooting

### Server Not Starting

If a server fails to start, check:
- Verify the service status: `systemctl status <service-name>`
- Check logs: `journalctl -u <service-name>`
- Verify port availability: `netstat -tuln | grep <port>`

### Connection Issues

If you can't connect to your server:
- Verify the HTTP service is exposed correctly
- Check that the SSE endpoint URL is correct
- Ensure your MORPH_API_KEY is set in client requests

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Unified Client

This repository includes a unified client that supports both SSE and stdio transport methods and can load server configurations from a JSON file.

### Usage

```bash
# Start with a config file
python unified_client.py unified_config.json

# Or start without config and load later
python unified_client.py
```

### Interactive Commands

Once the client is running, you can use the following commands:

- `load <config_file>` - Load a configuration file containing server definitions
- `list` - List all available configured servers
- `connect <server>` - Connect to a server defined in the config file
- `connect_stdio <path>` - Connect to a stdio server script directly
- `connect_sse <url>` - Connect to an SSE server URL directly
- `query <text>` - Send a query to the connected server
- `disconnect` - Disconnect from the current server
- `quit` - Exit the client

### Configuration File Format

The configuration file should be in JSON format and follow this structure:

```json
{
  "mcpServers": {
    "server-name-1": {
      "url": "https://remote-server-name-morphvm-id.http.cloud.morph.so/sse"
    },
    "server-name-2": {
      "command": "npx",
      "args": [
        "-y",
        "supergateway",
        "--sse",
        "https://remote-server-name-morphvm-id.http.cloud.morph.so/sse"
      ]
    }
  }
}
```

Each server can be defined with either:
- An `url` field for direct SSE connections
- `command` and `args` fields for stdio connections

The unified client automatically detects which connection method to use based on the configuration.

### Example Workflow

1. Create a Morph Cloud VM with multiple MCP servers using `setup_mcp.py`
2. Save the server URLs in a configuration file
3. Use the unified client to connect to any of your servers and interact with them

## License

This project is licensed under the Apache 2.0 License - see the LICENSE file for details.

