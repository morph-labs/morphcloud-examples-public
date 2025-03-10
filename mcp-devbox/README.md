# Instructions

## python
```bash
# env setup
uv pip install morphcloud mcp anthropic requests```

```bash
# server setup
uv run setup_mcp.py
```

```bash
# With config file
python setup_mcp.py 
```

```bash
# Connect to servers
python client_sse.py <sse_endpoint>
```

## info
- sets up one or more Model Context Protocol (MCP) servers on Morph Cloud VMs
- supports multiple servers on a single VM with unique service names and ports
- intelligent port management and service naming to prevent conflicts
- uses a 2 vcpu 2GB ram and 4GB disk instance by default
- accessible through SSE endpoints with client tools included

## notes
- make sure to export your MORPH_API_KEY into your environment
    - [get early access](https://docs.google.com/forms/d/1F8JeJEJWwP5ywfmGN_N-r3MBNHVzry7k1Dg_2YEex28/viewform?edit_requested=true)
- supports existing VM integration with `--instance-id <vm-id>`
- customize VM specs with `--vcpus`, `--memory`, and `--disk-size` options
- includes unified client that supports both SSE and stdio transport methods
- see client_sse.py for a complete client example using the SSE endpoint

## Usage Examples

### Create a VM with multiple servers
```bash
python setup_mcp.py --multi --count 3
```

### Add servers to existing VM
```bash
python setup_mcp.py --instance-id abc123 --base-port 4000
```

### Connect with unified client
```bash
# Connect to servers
python client_sse.py https://remote-server-brave-search-1-morphvm-jdf4963i.http.cloud.morph.so/sse
```


### Connect with Claude Desktop 

- add to `claude_desktop_config.json`
- note that we use supergateway to turn the sse transport back into stdio for interop w/ Claude Desktop

```json
{
  "mcpServers": {
    "supermachineExampleNpx": {
      "command": "npx",
      "args": [
        "-y",
        "supergateway",
        "--sse",
        "https://remote-server-brave-search-1-morphvm-jdf4963i.http.cloud.morph.so/sse"
      ]
    }
  }
}
```

### Connect with Cursor

- Cursor Settings > MCP > Add New MCP Server

#### sse
- select the 'sse' option

```
https://remote-server-tool-morphvm-abc123.http.cloud.morph.so/sse
```

#### stdio
- select the 'command' option

```bash
npx -y supergateway --sse https://remote-server-tool-morphvm-abc123.http.cloud.morph.so/sse
```
