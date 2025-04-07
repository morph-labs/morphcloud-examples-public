#!/usr/bin/env python3
# /// script
# dependencies = [
#   "morphcloud",
#   "requests",
# ]
# ///

import json
import os
import random
import re
import string
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError

import requests
from morphcloud.api import MorphCloudClient


def run_ssh_command(instance, command, sudo=False, print_output=True, timeout=None):
    """
    Run a command on the instance via SSH and return the result

    Args:
        instance: The MorphCloud instance
        command: The command to run
        sudo: Whether to run with sudo
        print_output: Whether to print command output to console
        timeout: Maximum time in seconds to wait for command to complete (None = wait indefinitely)

    Returns:
        An InstanceExecResponse object or a timeout result object
    """
    import time
    from types import SimpleNamespace

    if sudo and not command.startswith("sudo "):
        command = f"sudo {command}"

    print(f"Running on VM: {command}" + (f" (timeout: {timeout}s)" if timeout else ""))

    # If timeout is specified, modify the command to include timeout control
    if timeout is not None:
        # Use the 'timeout' command on Linux to enforce a time limit
        # Add 5 seconds to the SSH timeout compared to the command timeout
        timeout_command = f"timeout {timeout} {command}"
        ssh_timeout = timeout + 5  # Give SSH slightly longer to return
    else:
        timeout_command = command
        ssh_timeout = None

    # Use a separate function for the actual execution to make timeout handling cleaner
    def execute_command():
        try:
            return instance.exec(timeout_command)
        except Exception as e:
            # Handle any exceptions that might occur during execution
            return SimpleNamespace(
                stdout="", stderr=f"Error executing command: {str(e)}", exit_code=1
            )

    # If no timeout, just run the command directly
    if ssh_timeout is None:
        result = execute_command()
    else:
        # Use a timer-based approach instead of ThreadPoolExecutor
        result = None
        has_result = False

        # Create a thread to run the command
        execution_thread = threading.Thread(
            target=lambda: globals().update(
                {"result": execute_command(), "has_result": True}
            )
        )
        execution_thread.daemon = (
            True  # Allow Python to exit even if this thread is running
        )

        # Start the thread and wait for it
        execution_thread.start()
        execution_thread.join(timeout=ssh_timeout)

        # Check if we got a result in time
        if not has_result:
            # Create a timeout result
            result = SimpleNamespace(
                stdout="",
                stderr=f"Command timed out after {timeout} seconds",
                exit_code=124,  # Standard timeout exit code
            )

            # We won't try to cancel the command, as we can't effectively do this remotely
            # The command will continue running on the server, but we'll stop waiting for it
            print(f"Command timed out after {timeout} seconds. Continuing...")

    # Print output if requested
    if print_output and result:
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(f"ERR: {result.stderr}", file=sys.stderr)

    if (
        result and result.exit_code != 0 and result.exit_code != 124
    ):  # Don't show error for timeouts
        print(f"Command failed with exit code {result.exit_code}")

    return result


def get_or_create_snapshot(client, vcpus, memory, disk_size, node_required=True):
    """Get an existing snapshot with matching metadata or create a new one"""
    # Define the snapshot configuration metadata
    snapshot_metadata = {
        "type": "mcp-server-base",
        "vcpus": str(vcpus),
        "memory": str(memory),
        "disk_size": str(disk_size),
    }

    if node_required:
        snapshot_metadata["has_node"] = "true"

    # Try to find an existing snapshot with matching metadata
    print("Looking for existing snapshot with matching configuration...")
    existing_snapshots = client.snapshots.list(metadata={"type": "mcp-server-base"})

    for snapshot in existing_snapshots:
        if (
            snapshot.status == "ready"
            and snapshot.metadata.get("vcpus") == snapshot_metadata["vcpus"]
            and snapshot.metadata.get("memory") == snapshot_metadata["memory"]
            and snapshot.metadata.get("disk_size") == snapshot_metadata["disk_size"]
        ):

            # Check for Node.js if required
            if node_required and snapshot.metadata.get("has_node") != "true":
                print(
                    f"Snapshot {snapshot.id} matches but doesn't have Node.js installed. Continuing search..."
                )
                continue

            print(f"Found existing snapshot {snapshot.id} with matching configuration")
            return snapshot

    # No matching snapshot found, create a new one
    print("No matching snapshot found. Creating new snapshot...")
    snapshot = client.snapshots.create(
        vcpus=vcpus,
        memory=memory,
        disk_size=disk_size,
    )

    # Add metadata to the snapshot
    print("Adding metadata to snapshot...")
    snapshot.set_metadata(snapshot_metadata)

    return snapshot


def fetch_mcp_packages():
    """Fetch the list of available MCP packages"""
    try:
        response = requests.get(
            "https://raw.githubusercontent.com/michaellatman/mcp-get/refs/heads/main/packages/package-list.json"
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching MCP packages: {e}")
        return []


def select_mcp_package(packages):
    """Present MCP server options to user and let them select one"""
    # Display options to user
    print("\nAvailable MCP Servers:")
    for i, package in enumerate(packages, 1):
        print(f"{i}. {package['name']}")
        print(f"   Description: {package.get('description', 'No description')}")
        print(f"   Vendor: {package.get('vendor', 'Unknown')}")
        print(f"   Source: {package.get('sourceUrl', 'Unknown')}")
        print()

    # Get user selection
    while True:
        try:
            selection = input(
                "Select an MCP server by number (or press Enter for Brave Search): "
            )
            if not selection.strip():
                # Default to Brave Search if user just presses Enter
                for pkg in packages:
                    if "brave-search" in pkg["name"].lower():
                        return pkg
                # If Brave Search not found, use the first package
                return packages[0]

            selection = int(selection) - 1
            if 0 <= selection < len(packages):
                return packages[selection]
            else:
                print(f"Please enter a number between 1 and {len(packages)}")
        except ValueError:
            print("Please enter a valid number")


def parse_github_url(source_url):
    """Parse GitHub URL to extract username, repo, branch, and path"""
    if not source_url:
        return None

    # Parse GitHub URLs with subdirectories
    # Example: https://github.com/modelcontextprotocol/servers/blob/main/src/redis
    github_pattern = r"https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.*)"
    match = re.match(github_pattern, source_url)

    if match:
        username, repo, branch, path = match.groups()
        return {"username": username, "repo": repo, "branch": branch, "path": path}

    # Try simpler pattern for repo root
    # Example: https://github.com/username/repo
    simple_pattern = r"https://github\.com/([^/]+)/([^/]+)/?$"
    match = re.match(simple_pattern, source_url)

    if match:
        username, repo = match.groups()
        return {
            "username": username,
            "repo": repo,
            "branch": None,  # We'll try both main and master
            "path": "",
        }

    return None


def find_readme_urls(github_info):
    """Generate possible README URLs based on the GitHub path"""
    if not github_info:
        return []

    username = github_info["username"]
    repo = github_info["repo"]
    path = github_info["path"]

    # Try both main and master branches
    branches = []
    if github_info["branch"]:
        # If a branch is specified in the URL, try that one first
        branches.append(github_info["branch"])
        # Then try the alternative
        branches.append("master" if github_info["branch"] == "main" else "main")
    else:
        # If no branch is specified, try both common branch names
        branches = ["main", "master"]

    # Possible README filenames
    readme_names = ["README.md", "Readme.md", "readme.md", "README", "readme"]

    urls = []

    # Generate URLs for all combinations of branches, paths and README names
    for branch in branches:
        # First priority: Check exact directory path
        if path:
            # If path points to a file, get its directory
            if not path.endswith("/"):
                dir_path = "/".join(path.split("/")[:-1])
                if dir_path:
                    for name in readme_names:
                        urls.append(
                            f"https://raw.githubusercontent.com/{username}/{repo}/{branch}/{dir_path}/{name}"
                        )

            # Check in the path directly (if it's a directory)
            for name in readme_names:
                urls.append(
                    f"https://raw.githubusercontent.com/{username}/{repo}/{branch}/{path}/{name}"
                )

        # Last resort: try repo root
        for name in readme_names:
            urls.append(
                f"https://raw.githubusercontent.com/{username}/{repo}/{branch}/{name}"
            )

    return urls


def extract_json_blocks(text):
    """Extract all JSON objects from text, handling URLs correctly"""
    json_blocks = []
    json_texts = []  # Store the raw text of each JSON block

    # Find all markdown code blocks
    code_block_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    code_blocks = re.finditer(code_block_pattern, text, re.DOTALL)

    # Process each code block
    for block in code_blocks:
        block_content = block.group(1).strip()

        if block_content.startswith("{") and block_content.endswith("}"):
            if block_content not in json_texts:
                json_texts.append(block_content)
                try:
                    # Try to parse as JSON
                    json_obj = json.loads(block_content)
                    json_blocks.append({"json": json_obj, "text": block_content})
                except json.JSONDecodeError:
                    # Include it even if it has errors
                    json_blocks.append(
                        {
                            "json": None,
                            "text": block_content,
                            "error": "Invalid JSON syntax",
                        }
                    )

    # Find inline code blocks that look like JSON objects
    inline_pattern = r"`(\{[^`]*\})`"
    inline_blocks = re.finditer(inline_pattern, text)

    for block in inline_blocks:
        block_content = block.group(1).strip()

        if block_content not in json_texts:
            json_texts.append(block_content)
            try:
                # Try to parse as JSON
                json_obj = json.loads(block_content)
                json_blocks.append({"json": json_obj, "text": block_content})
            except json.JSONDecodeError:
                # Only include if it looks reasonably like JSON
                if (
                    block_content.count("{") == block_content.count("}")
                    and '"' in block_content
                ):
                    json_blocks.append(
                        {
                            "json": None,
                            "text": block_content,
                            "error": "Invalid JSON syntax",
                        }
                    )

    # Now let's look for indented code blocks
    lines = text.split("\n")
    in_indented_block = False
    current_block = []

    for line in lines:
        if not in_indented_block and line.startswith("    ") and "{" in line:
            in_indented_block = True
            current_block = [line.strip()]
        elif in_indented_block:
            if line.startswith("    "):
                current_block.append(line.strip())
            else:
                in_indented_block = False
                block_content = "\n".join(current_block)

                if block_content.startswith("{") and block_content.endswith("}"):
                    if block_content not in json_texts:
                        json_texts.append(block_content)
                        try:
                            json_obj = json.loads(block_content)
                            json_blocks.append(
                                {"json": json_obj, "text": block_content}
                            )
                        except json.JSONDecodeError:
                            json_blocks.append(
                                {
                                    "json": None,
                                    "text": block_content,
                                    "error": "Invalid JSON syntax",
                                }
                            )

                current_block = []

    # One more special case: Look for line-by-line HTML tables containing JSON configs
    html_json_pattern = r"<tr>.*?<td>.*?</td>.*?<td>.*?(\{.*?\}).*?</td>.*?</tr>"
    html_matches = re.finditer(html_json_pattern, text, re.DOTALL)

    for match in html_matches:
        potential_json = match.group(1).strip()

        if potential_json not in json_texts:
            json_texts.append(potential_json)
            try:
                json_obj = json.loads(potential_json)
                json_blocks.append({"json": json_obj, "text": potential_json})
            except json.JSONDecodeError:
                pass

    return json_blocks


def fetch_github_content(url):
    """Fetch content from GitHub raw URL"""
    if not url:
        return None

    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.text
        return None
    except requests.RequestException:
        return None


def find_mcp_config_from_readme(package):
    """Find MCP server configuration from the package's README"""
    source_url = package.get("sourceUrl")
    if not source_url:
        print("No source URL available for this package.")
        return None

    print(f"Source URL: {source_url}")

    github_info = parse_github_url(source_url)
    if not github_info:
        print(
            "Could not parse GitHub URL. Make sure it's a valid GitHub repository URL."
        )
        return None

    readme_urls = find_readme_urls(github_info)
    print(f"Checking {len(readme_urls)} possible README locations...")

    readme_content = None
    found_url = None

    for url in readme_urls:
        content = fetch_github_content(url)
        if content:
            readme_content = content
            found_url = url
            print(f"Found README at: {url}")
            break

    if not readme_content:
        print("Could not find README in the repository.")
        return None

    print("\n==== README PREVIEW ====\n")
    # Print just the first 300 characters as a preview
    preview = readme_content[:300] + ("..." if len(readme_content) > 300 else "")
    print(preview)

    json_blocks = extract_json_blocks(readme_content)

    if not json_blocks:
        print("\nNo JSON blocks found in the README.")
        return None

    print(f"\n==== FOUND {len(json_blocks)} JSON BLOCKS ====\n")

    # Look for blocks that contain mcpServers
    mcp_config = None

    for i, block in enumerate(json_blocks, 1):
        print(f"JSON BLOCK #{i}:")

        if block.get("error"):
            print(f"WARNING: {block['error']}")
            print("RAW TEXT:")
            print(block["text"])
        else:
            try:
                print(json.dumps(block["json"], indent=2))
            except:
                print(block["text"])
        print()

        # If this block has mcpServers, save it
        if block.get("json") and "mcpServers" in block.get("json", {}):
            print("⭐ This block contains MCP server configuration! ⭐")
            print()
            mcp_config = block["json"]

    return mcp_config


def setup_supergateway_multi(
    instance, command_info, service_name, port=3000, enable_cors=False
):
    """
    Set up supergateway to convert MCP output to SSE with unique service names

    Args:
        instance: The MorphCloud instance
        command_info: Dictionary with command configuration
        service_name: Unique name for this MCP server service
        port: Port number to use for this service
        enable_cors: Whether to enable CORS for this service

    Returns:
        bool: True if setup was successful, False otherwise
    """
    print(f"\nSetting up supergateway for {service_name} on port {port}...")

    # Install supergateway if not already installed
    # Use -g to install globally, which is required for the service to work
    run_ssh_command(instance, "npm list -g supergateway || npm install -g supergateway")

    # Build the command that will be passed to supergateway
    if command_info["runtime"] == "node":
        if command_info["command"] == "npx":
            cmd_str = f"npx {' '.join(command_info['args'])}"
        else:
            cmd_str = f"{command_info['command']} {' '.join(command_info['args'])}"
    elif command_info["runtime"] == "python":
        cmd_str = f"{command_info['command']} {' '.join(command_info['args'])}"
    else:
        cmd_str = f"{command_info['command']} {' '.join(command_info['args'])}"

    print(f"MCP server command: {cmd_str}")

    # Create environment variable exports if they exist
    env_exports = ""
    if "env" in command_info and command_info["env"]:
        env_vars = command_info["env"]
        for key, value in env_vars.items():
            env_exports += f'export {key}="{value}"\n'
        print(f"Adding environment variables: {', '.join(env_vars.keys())}")

    # Add supergateway options
    supergateway_options = f'--stdio "{cmd_str}" --port {port}'
    if enable_cors:
        supergateway_options += " --cors"
        print("CORS enabled for supergateway")

    # Create a startup script with environment variables - use unique names
    start_script_path = f"~/start-{service_name}.sh"
    start_script = f"""
cat > {start_script_path} << 'EOF'
#!/bin/bash
cd ~
{env_exports}
npx -y supergateway {supergateway_options}
EOF
chmod +x {start_script_path}
"""
    run_ssh_command(instance, start_script)

    # Set up as a unique system service
    service_config = f"""
cat > /tmp/{service_name}.service << 'EOF'
[Unit]
Description=MCP SSE Server - {service_name}
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root
ExecStart=/root/start-{service_name}.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
sudo mv /tmp/{service_name}.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable {service_name}
sudo systemctl start {service_name}
"""
    result = run_ssh_command(instance, service_config)

    if result.exit_code != 0:
        print(f"Failed to set up service {service_name}")
        return False

    # Wait for service to start
    print(f"Waiting for {service_name} service to start...")
    time.sleep(5)
    status_result = run_ssh_command(instance, f"systemctl status {service_name}")

    # Check if service started successfully
    return status_result.exit_code == 0


def setup_supergateway(instance, command_info, port=3000, enable_cors=False):
    """
    Legacy function for backward compatibility
    Sets up a supergateway with the default service name
    """
    return setup_supergateway_multi(
        instance, command_info, "mcp-sse", port, enable_cors
    )


def extract_server_config(mcp_config, package_name):
    """Extract server configuration from MCP config for a specific package"""
    if not mcp_config or "mcpServers" not in mcp_config:
        return None

    # Look for an exact match first
    for key, server in mcp_config["mcpServers"].items():
        if key == package_name:
            return {
                "name": package_name,
                "runtime": server.get("runtime", "node"),
                "command": server.get("command", "npx"),
                "args": server.get("args", []),
                "env": server.get("env", {}),
            }

    # If no exact match, try partial match
    for key, server in mcp_config["mcpServers"].items():
        # Try different ways of matching the package name to the config key
        if package_name in key or key in package_name:
            return {
                "name": package_name,
                "runtime": server.get("runtime", "node"),
                "command": server.get("command", "npx"),
                "args": server.get("args", []),
                "env": server.get("env", {}),
            }

    # Use the first server config as fallback
    if mcp_config.get("mcpServers"):
        key = next(iter(mcp_config["mcpServers"]))
        server = mcp_config["mcpServers"][key]
        return {
            "name": package_name,
            "runtime": server.get("runtime", "node"),
            "command": server.get("command", "npx"),
            "args": server.get("args", []),
            "env": server.get("env", {}),
        }

    return None


def apply_server_config(instance, server_config):
    """Apply server configuration on the instance by creating config file"""
    if not server_config:
        return False

    # Create a server_config.json file on the VM
    config_json = {
        "mcpServers": {
            server_config["name"]: {
                "runtime": server_config["runtime"],
                "command": server_config["command"],
                "args": server_config["args"],
            }
        }
    }

    # Add environment variables if they exist
    if server_config.get("env"):
        config_json["mcpServers"][server_config["name"]]["env"] = server_config["env"]

    # Convert to JSON string
    config_str = json.dumps(config_json, indent=2)

    # Escape any special characters for shell script
    config_str = config_str.replace('"', '\\"')

    # Write the config to a file on the VM
    config_cmd = f"""
cat > ~/.config/Claude/server_config.json << 'EOF'
{json.dumps(config_json, indent=2)}
EOF
"""
    result = run_ssh_command(instance, config_cmd)
    return result.exit_code == 0


def fallback_to_default_config(instance, package):
    """Create a default configuration based on package information"""
    package_name = package["name"]

    # Extract the package name without the scope/namespace
    simple_name = package_name.split("/")[-1]

    # Create a simple configuration
    config = {
        "name": package_name,
        "runtime": "node",
        "command": "npx",
        "args": ["-y", package_name],
        "env": {},
    }

    print("Using default configuration for MCP server.")
    apply_server_config(instance, config)
    return config


def detect_existing_services(instance):
    """
    Detect existing MCP-SSE services on the VM by querying systemd services
    and finding used ports.

    Returns:
        dict: A dictionary containing information about existing services
              with service names as keys and port numbers as values
    """
    print("\nDetecting existing MCP-SSE services...")

    # Check systemd services
    result = run_ssh_command(
        instance,
        "systemctl list-units --type=service --state=running | grep mcp-sse",
        print_output=False,
    )

    service_info = {}

    if result.exit_code == 0 and result.stdout.strip():
        # Parse the service list output
        service_lines = result.stdout.strip().split("\n")
        for line in service_lines:
            service_name = line.split()[0]
            if service_name.endswith(".service"):
                service_name = service_name[:-8]  # Remove .service suffix

                # Get service port by checking the service file
                port_cmd = f"grep -o 'port [0-9]\\+' /etc/systemd/system/{service_name}.service || cat /etc/systemd/system/{service_name}.service"
                port_result = run_ssh_command(instance, port_cmd, print_output=False)

                if port_result.exit_code == 0 and port_result.stdout:
                    port_match = re.search(r"port (\d+)", port_result.stdout)
                    if port_match:
                        port = int(port_match.group(1))
                        service_info[service_name] = {
                            "port": port,
                            "running": True,
                            "service_name": service_name,
                        }

    # Also check for listening ports using netstat
    port_cmd = "netstat -tulpn | grep LISTEN"
    port_result = run_ssh_command(instance, port_cmd, print_output=False)

    if port_result.exit_code == 0 and port_result.stdout.strip():
        port_lines = port_result.stdout.strip().split("\n")
        for line in port_lines:
            if "node" in line or "supergateway" in line:
                port_match = re.search(r":(\d+)\s+", line)
                pid_match = re.search(r"(\d+)/\w+", line)
                if port_match and pid_match:
                    port = int(port_match.group(1))
                    pid = pid_match.group(1)

                    # If we already have this port in our service_info, continue
                    if any(info.get("port") == port for info in service_info.values()):
                        continue

                    # Try to find service name from process
                    cmd_result = run_ssh_command(
                        instance, f"ps -p {pid} -o command=", print_output=False
                    )
                    if cmd_result.exit_code == 0 and cmd_result.stdout.strip():
                        cmd = cmd_result.stdout.strip()
                        # Generate a generic name for services found this way
                        service_name = f"unknown-mcp-sse-{port}"
                        service_info[service_name] = {
                            "port": port,
                            "running": True,
                            "service_name": service_name,
                            "command": cmd,
                        }

    if service_info:
        print(f"Found {len(service_info)} existing MCP-SSE services:")
        for name, info in service_info.items():
            print(f"  - {name} (port {info['port']})")
    else:
        print("No existing MCP-SSE services detected.")

    return service_info


def find_available_port(instance, base_port=3000, existing_services=None):
    """
    Find an available port starting from base_port and incrementing

    Args:
        instance: The MorphCloud instance
        base_port: The starting port number to check
        existing_services: Dictionary of existing services with their ports

    Returns:
        int: An available port number
    """
    if existing_services is None:
        existing_services = {}

    # Extract all used ports from existing services
    used_ports = set()
    for service_info in existing_services.values():
        if "port" in service_info:
            used_ports.add(service_info["port"])

    # Check ports starting from base_port
    port = base_port
    while port in used_ports or not is_port_available(instance, port):
        port += 1
        if port > 65535:  # Maximum valid port
            raise ValueError("Could not find an available port")

    print(f"Found available port: {port}")
    return port


def is_port_available(instance, port):
    """
    Check if a port is available on the VM

    Args:
        instance: The MorphCloud instance
        port: The port number to check

    Returns:
        bool: True if port is available, False otherwise
    """
    # Check if the port is already in use
    result = run_ssh_command(
        instance, f"netstat -tuln | grep ':{port} '", print_output=False
    )

    # If command succeeds and returns output, port is in use
    return result.exit_code != 0 or not result.stdout.strip()


def generate_unique_service_name(base_name, existing_services=None):
    """
    Generate a unique service name by appending an index or random suffix

    Args:
        base_name: The base service name
        existing_services: Dictionary of existing services

    Returns:
        str: A unique service name
    """
    if existing_services is None:
        existing_services = {}

    # Clean the base name to ensure it's suitable for a systemd service
    base_name = re.sub(r"[^a-zA-Z0-9_-]", "-", base_name)

    # Try with sequential numbers first
    for i in range(1, 100):
        service_name = f"{base_name}-{i}"
        if service_name not in existing_services:
            return service_name

    # If all sequential names are taken, add a random suffix
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{base_name}-{suffix}"


def display_connection_info(instance, server_configs, custom_urls=None):
    """Display connection information for multiple MCP servers"""
    # Get the HTTP service URL
    instance._refresh()  # Refresh to get latest HTTP services

    if not isinstance(server_configs, list):
        server_configs = [server_configs]

    if custom_urls is None or not isinstance(custom_urls, list):
        custom_urls = [None] * len(server_configs)

    services = instance.networking.http_services

    print("\n========== CONNECTION INFORMATION ==========")

    # Format for Claude config
    claude_configs_json = {"mcpServers": {}}

    # Format for our unified client
    unified_configs_json = {"mcpServers": {}}

    for i, (server_config, custom_url) in enumerate(zip(server_configs, custom_urls)):
        # Use the custom service name in the lookup
        service_name = (
            custom_url
            if custom_url
            else f"remote-server-{server_config['name'].split('/')[-1]}"
        )
        sse_service = next((svc for svc in services if svc.name == service_name), None)

        if sse_service:
            # Use the same service name for the config
            server_url_name = service_name

            print(f"\n--- SERVER {i+1} ---")
            print(f"MCP Package: {server_config['name']}")
            print(f"SSE Endpoint: {sse_service.url}/sse")

            # Make sure we have the /sse endpoint
            sse_url = f"{sse_service.url}/sse"

            # Add to the Claude config
            claude_configs_json["mcpServers"][server_url_name] = {
                "endpoint": sse_url,
                "type": "sse",
            }

            # Add to the unified client config with both SSE and stdio options
            package_name = server_config["name"].split("/")[-1]

            # SSE version
            unified_configs_json["mcpServers"][f"{package_name}-sse"] = {"url": sse_url}

            # stdio version using supergateway
            unified_configs_json["mcpServers"][f"{package_name}-stdio"] = {
                "command": "npx",
                "args": ["-y", "supergateway", "--sse", sse_url],
            }
        else:
            print(
                f"Could not find SSE service URL for {server_config['name']}. Please check the VM manually."
            )

    # Write unified config to file
    config_filename = f"mcp_config_{instance.id}.json"
    with open(config_filename, "w") as f:
        json.dump(unified_configs_json, f, indent=2)

    print("\nTo use with Claude:")
    print("Add the following MCP servers to your Claude config:")
    print(json.dumps(claude_configs_json, indent=2))
    print("\nConnect to the MCP servers in your next Claude conversation")

    print(f"\nA unified client configuration has been saved to: {config_filename}")
    print(f"To use it with the unified client, run:")
    print(f"  python unified_client.py {config_filename}")
    print("========================================")

    return claude_configs_json


def prompt_for_env_vars(env_vars):
    """Prompt user to update environment variables"""
    print("\nCurrent environment variables:")
    for key, value in env_vars.items():
        # Mask values that look like API keys
        if (
            "key" in key.lower() or "token" in key.lower() or "secret" in key.lower()
        ) and value != "":
            display_value = (
                f"{'*' * (len(value) - 4)}{value[-4:]}" if len(value) > 4 else "****"
            )
        else:
            display_value = value
        print(f"  {key}: {display_value}")

    print("\nWould you like to modify any environment variables? (y/n)")
    choice = input("Enter your choice: ").strip().lower()

    if choice == "y":
        updated_env = env_vars.copy()

        while True:
            print("\nOptions:")
            print("  1. Add or update an environment variable")
            print("  2. Remove an environment variable")
            print("  3. Done editing")

            try:
                option = int(input("Enter your choice (1-3): ").strip())

                if option == 1:
                    key = input("Enter environment variable name: ").strip()
                    value = input(f"Enter value for {key}: ").strip()
                    updated_env[key] = value
                    print(f"Updated {key}")

                elif option == 2:
                    if not updated_env:
                        print("No environment variables to remove.")
                        continue

                    print("\nAvailable environment variables:")
                    for i, key in enumerate(updated_env.keys(), 1):
                        print(f"  {i}. {key}")

                    key_idx = (
                        int(input("Enter number of variable to remove: ").strip()) - 1
                    )
                    if 0 <= key_idx < len(updated_env):
                        key_to_remove = list(updated_env.keys())[key_idx]
                        del updated_env[key_to_remove]
                        print(f"Removed {key_to_remove}")
                    else:
                        print("Invalid selection")

                elif option == 3:
                    break
                else:
                    print("Invalid option. Please enter 1, 2, or 3.")

            except ValueError:
                print("Invalid input. Please enter a number.")

        return updated_env
    else:
        return env_vars


def prompt_for_args_modification(args):
    """Prompt user to update command arguments"""
    print("\nCurrent command arguments:")
    for i, arg in enumerate(args):
        print(f"  {i+1}. {arg}")

    print("\nWould you like to modify the command arguments? (y/n)")
    choice = input("Enter your choice: ").strip().lower()

    if choice == "y":
        updated_args = args.copy()

        while True:
            print("\nOptions:")
            print("  1. Add an argument")
            print("  2. Update an argument")
            print("  3. Remove an argument")
            print("  4. Reorder arguments")
            print("  5. Done editing")

            try:
                option = int(input("Enter your choice (1-5): ").strip())

                if option == 1:
                    arg = input("Enter new argument: ").strip()
                    position = input("Enter position (press Enter to append): ").strip()

                    if position:
                        pos = int(position) - 1
                        updated_args.insert(min(pos, len(updated_args)), arg)
                    else:
                        updated_args.append(arg)

                elif option == 2:
                    if not updated_args:
                        print("No arguments to update.")
                        continue

                    print("\nCurrent arguments:")
                    for i, arg in enumerate(updated_args):
                        print(f"  {i+1}. {arg}")

                    arg_idx = (
                        int(input("Enter number of argument to update: ").strip()) - 1
                    )
                    if 0 <= arg_idx < len(updated_args):
                        new_value = input(
                            f"Enter new value for '{updated_args[arg_idx]}': "
                        ).strip()
                        updated_args[arg_idx] = new_value
                    else:
                        print("Invalid selection")

                elif option == 3:
                    if not updated_args:
                        print("No arguments to remove.")
                        continue

                    print("\nCurrent arguments:")
                    for i, arg in enumerate(updated_args):
                        print(f"  {i+1}. {arg}")

                    arg_idx = (
                        int(input("Enter number of argument to remove: ").strip()) - 1
                    )
                    if 0 <= arg_idx < len(updated_args):
                        removed = updated_args.pop(arg_idx)
                        print(f"Removed '{removed}'")
                    else:
                        print("Invalid selection")

                elif option == 4:
                    if len(updated_args) < 2:
                        print("Not enough arguments to reorder.")
                        continue

                    print("\nCurrent arguments:")
                    for i, arg in enumerate(updated_args):
                        print(f"  {i+1}. {arg}")

                    from_idx = (
                        int(input("Enter number of argument to move: ").strip()) - 1
                    )
                    to_idx = int(input("Enter target position: ").strip()) - 1

                    if 0 <= from_idx < len(updated_args) and 0 <= to_idx < len(
                        updated_args
                    ):
                        arg = updated_args.pop(from_idx)
                        updated_args.insert(to_idx, arg)
                        print("Arguments reordered")
                    else:
                        print("Invalid selection")

                elif option == 5:
                    break
                else:
                    print("Invalid option. Please enter a number between 1 and 5.")

            except ValueError:
                print("Invalid input. Please enter a number.")

        print("\nUpdated arguments:")
        for i, arg in enumerate(updated_args):
            print(f"  {i+1}. {arg}")

        return updated_args
    else:
        return args


def prompt_for_config_customization(server_config):
    """Allow user to customize server configuration"""
    if not server_config:
        return None

    print("\n========== Server Configuration Customization ==========")
    print(f"Server package: {server_config['name']}")
    print(f"Runtime: {server_config['runtime']}")
    print(f"Command: {server_config['command']}")

    # Allow user to customize arguments
    if "args" in server_config:
        server_config["args"] = prompt_for_args_modification(server_config["args"])

    # Allow user to customize environment variables
    if "env" in server_config:
        server_config["env"] = prompt_for_env_vars(server_config["env"])
    else:
        env_vars = {}
        print("\nWould you like to add environment variables? (y/n)")
        if input("Enter your choice: ").strip().lower() == "y":
            server_config["env"] = prompt_for_env_vars(env_vars)
        else:
            server_config["env"] = {}

    return server_config


def load_config_from_file(config_path):
    """Load server configuration from a JSON file"""
    try:
        with open(config_path, "r") as file:
            config = json.load(file)

        if "mcpServers" not in config:
            print("Error: Invalid config file format. Missing 'mcpServers' key.")
            return None

        # Get the first server config from the file
        server_name = next(iter(config["mcpServers"]))
        server_config = config["mcpServers"][server_name]

        # Format it to match our expected structure
        return {
            "name": server_name,
            "runtime": server_config.get("runtime", "node"),
            "command": server_config.get("command", "npx"),
            "args": server_config.get("args", []),
            "env": server_config.get("env", {}),
        }
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Error loading config file: {e}")
        return None


def check_nodejs_installation(instance, update_metadata=True):
    """
    Check if Node.js is installed on the VM and install if needed

    Args:
        instance: The MorphCloud instance
        update_metadata: Whether to update the snapshot metadata when Node.js is installed

    Returns:
        bool: True if Node.js is installed (or was installed successfully), False otherwise
    """
    # Check if Node.js is already installed
    result = run_ssh_command(instance, "node --version", print_output=False)

    if result.exit_code == 0:
        node_version = result.stdout.strip()
        print(f"Node.js {node_version} is already installed.")
        node_installed = True
    else:
        # Install Node.js if not installed
        print("Node.js not found, installing...")
        install_result = run_ssh_command(
            instance, "apt-get update -y && apt-get install -y nodejs npm", sudo=True
        )

        if install_result.exit_code == 0:
            # Verify installation
            verify_result = run_ssh_command(
                instance, "node --version && npm --version", print_output=False
            )
            if verify_result.exit_code == 0:
                node_version = verify_result.stdout.strip().split("\n")[0]
                print(f"Node.js {node_version} installed successfully.")
                node_installed = True
            else:
                print("Failed to install Node.js.")
                return False
        else:
            print("Failed to install Node.js.")
            return False

    # Update instance metadata to reflect Node.js installation
    if update_metadata and node_installed:
        try:
            # Get current metadata and update it
            current_metadata = instance.metadata or {}
            current_metadata["has_node"] = "true"
            current_metadata["node_version"] = node_version
            instance.set_metadata(current_metadata)
            print("Updated instance metadata with Node.js information.")
        except Exception as e:
            print(f"Warning: Failed to update metadata: {e}")

    return True


def setup_single_server(instance, args, existing_services=None, server_count=0):
    """
    Set up a single MCP server on the instance

    Args:
        instance: The MorphCloud instance
        args: Command-line arguments
        existing_services: Dictionary of existing services
        server_count: Current count of servers being set up

    Returns:
        tuple: (server_config, service_name, port) for the newly set up server
    """
    if existing_services is None:
        existing_services = {}

    # Determine server configuration
    server_config = None

    # If config file is provided, load from it
    if args.config:
        config_path = (
            args.config[0]
            if isinstance(args.config, list) and len(args.config) > 0
            else args.config
        )
        print(f"\nLoading configuration from file: {config_path}")
        server_config = load_config_from_file(config_path)
        if server_config:
            print("Configuration loaded successfully")
        else:
            print(
                "Failed to load configuration from file. Continuing with selection..."
            )

    # If no config file or loading failed, proceed with package selection
    if not server_config:
        # Fetch and select an MCP package
        packages = fetch_mcp_packages()
        if not packages:
            print("Failed to fetch MCP packages. Exiting.")
            return None, None, None

        selected_package = select_mcp_package(packages)
        print(f"\nSelected: {selected_package['name']}")

        # Find MCP configuration from README
        mcp_config = find_mcp_config_from_readme(selected_package)

        # Extract configuration for the selected package
        if mcp_config:
            server_config = extract_server_config(mcp_config, selected_package["name"])
            if server_config:
                print("\nFound MCP server configuration in README:")
                print(json.dumps(server_config, indent=2))
            else:
                print(
                    "\nCould not extract server configuration from README. Using fallback."
                )
                server_config = fallback_to_default_config(instance, selected_package)
        else:
            print("\nCould not find MCP configuration in README. Using fallback.")
            server_config = fallback_to_default_config(instance, selected_package)

    # Allow user to customize the configuration
    server_config = prompt_for_config_customization(server_config)

    # Apply the configuration on the VM
    if apply_server_config(instance, server_config):
        print("Applied MCP server configuration on VM.")
    else:
        print("Failed to apply server configuration.")
        return None, None, None

    # Determine base service name from package name
    package_name = server_config["name"].split("/")[-1]

    # Determine the actual service name (must be unique)
    base_service_name = "mcp-sse"
    if server_count > 0:
        base_service_name = f"mcp-sse-{package_name}"

    # Generate a unique service name
    service_name = generate_unique_service_name(base_service_name, existing_services)

    # Determine port to use (find an available one)
    base_port = args.base_port if hasattr(args, "base_port") else 3000
    port = find_available_port(instance, base_port, existing_services)

    # Setup supergateway for SSE conversion
    if not setup_supergateway_multi(
        instance, server_config, service_name, port=port, enable_cors=args.all_cors
    ):
        print(f"Failed to set up supergateway for {service_name}.")
        return None, None, None

    # Determine HTTP service name
    http_service_name = f"remote-{package_name}"
    if server_count > 0:
        http_service_name = f"remote-{package_name}-{server_count+1}"

    # Make sure HTTP service name is unique
    http_service_name = generate_unique_service_name(
        http_service_name, {svc.name: True for svc in instance.networking.http_services}
    )

    auth_mode = None
    if args.api_key_auth:
        auth_mode = "api_key"
    else:
        print("\nWould you like to secure this MCP server with API key authentication?")
        print("This will require clients to provide an API key to access the server.")
        choice = input("Enable API key authentication? [y/N]: ").strip().lower()
        if choice == "y":
            auth_mode = "api_key"

    # Expose HTTP service with the unique name
    print(f"\nExposing HTTP service as '{http_service_name}'...")
    if auth_mode is not None:
        instance.expose_http_service(http_service_name, port, auth_mode=auth_mode)
    else:
        instance.expose_http_service(http_service_name, port)

    # Return the configuration
    return server_config, http_service_name, port


def update_snapshot_metadata(snapshot, server_configs, service_names, instance=None):
    """
    Update snapshot metadata with information about all MCP servers and node/npm

    Args:
        snapshot: The snapshot to update
        server_configs: List of server configurations
        service_names: List of service names
        instance: The instance to get node information from (optional)
    """
    # Get existing metadata
    existing_metadata = snapshot.metadata or {}

    # Preserve existing metadata keys
    new_metadata = existing_metadata.copy()
    new_metadata["type"] = "mcp-server-multi"

    # Add server information to metadata
    server_info = []
    for i, (config, name) in enumerate(zip(server_configs, service_names)):
        server_info.append({"name": config["name"], "service": name, "index": i + 1})

    # Store server information as JSON string
    new_metadata["mcp_servers"] = json.dumps(server_info)
    new_metadata["description"] = (
        f"Multi-MCP Server with {len(server_configs)} services"
    )

    # If instance is provided, check and add Node.js information
    if instance:
        # Check if Node.js is installed
        result = run_ssh_command(
            instance, "node --version && npm --version", print_output=False
        )
        if result.exit_code == 0 and result.stdout.strip():
            versions = result.stdout.strip().split("\n")
            if len(versions) >= 2:
                node_version = versions[0]
                npm_version = versions[1]
                new_metadata["has_node"] = "true"
                new_metadata["node_version"] = node_version
                new_metadata["npm_version"] = npm_version
                print(
                    f"Added Node.js ({node_version}) and npm ({npm_version}) information to snapshot metadata"
                )
    else:
        # Copy Node.js information from instance metadata if it exists
        if "has_node" in existing_metadata:
            new_metadata["has_node"] = existing_metadata["has_node"]
        if "node_version" in existing_metadata:
            new_metadata["node_version"] = existing_metadata["node_version"]
        if "npm_version" in existing_metadata:
            new_metadata["npm_version"] = existing_metadata["npm_version"]

    # Update snapshot metadata
    snapshot.set_metadata(new_metadata)
    print(f"Updated snapshot metadata with {len(server_configs)} MCP servers")


def main():
    """Main function to setup multiple MCP servers on a MorphCloud VM"""
    try:
        # Parse command line arguments
        import argparse

        parser = argparse.ArgumentParser(
            description="Setup multiple MCP servers on MorphCloud"
        )

        # VM creation arguments
        parser.add_argument("--vcpus", type=int, default=2, help="Number of vCPUs")
        parser.add_argument("--memory", type=int, default=2048, help="Memory in MB")
        parser.add_argument(
            "--disk-size", type=int, default=4096, help="Disk size in MB"
        )
        parser.add_argument(
            "--node-required",
            action="store_true",
            default=True,
            help="Require Node.js to be installed",
        )

        # Connection arguments
        parser.add_argument(
            "--instance-id",
            help="Connect to an existing instance instead of creating a new one",
        )

        # Server configuration arguments
        parser.add_argument("--config", nargs="+", help="Path to JSON config file(s)")

        # Multi-server arguments
        parser.add_argument(
            "--multi", action="store_true", help="Set up multiple servers"
        )
        parser.add_argument(
            "--count", type=int, help="Number of servers to set up (when using --multi)"
        )
        parser.add_argument(
            "--base-port",
            type=int,
            default=3000,
            help="Starting port number for port allocation",
        )
        parser.add_argument(
            "--all-cors", action="store_true", help="Enable CORS for all servers"
        )

        args = parser.parse_args()

        # Initialize Morph Cloud client
        client = MorphCloudClient()

        # Track all server configurations and service names
        all_server_configs = []
        all_service_names = []

        # Either connect to an existing instance or create a new one
        if args.instance_id:
            # Connect to an existing instance
            print(f"\nConnecting to existing instance {args.instance_id}...")
            instance = client.instances.get(args.instance_id)

            if not instance:
                print(f"Instance {args.instance_id} not found.")
                sys.exit(1)

            print("Connected to instance.")
        else:
            # Create a new instance
            # VM configuration for MCP server
            VCPUS = args.vcpus
            MEMORY = args.memory
            DISK_SIZE = args.disk_size

            # Get or create a snapshot for our base VM
            snapshot = get_or_create_snapshot(
                client, VCPUS, MEMORY, DISK_SIZE, node_required=args.node_required
            )

            # Start instance from snapshot
            print("\nStarting VM instance...")
            instance = client.instances.start(snapshot.id)

            print("Waiting for instance to be ready...")
            instance.wait_until_ready()

            # Create directory for MCP server config
            run_ssh_command(instance, "mkdir -p ~/.config/Claude", sudo=False)

        # Always check for Node.js and install if needed
        if not check_nodejs_installation(instance):
            print("Node.js installation failed. Exiting.")
            sys.exit(1)

        # Detect existing services on the instance
        existing_services = detect_existing_services(instance)

        # Determine how many servers to set up
        if args.multi:
            server_count = args.count if args.count else 1
            print(f"\nSetting up {server_count} MCP servers...")
        else:
            server_count = 1
            print("\nSetting up a single MCP server...")

        # Set up each server
        for i in range(server_count):
            if i > 0:
                print(f"\n--- Setting up server {i+1} of {server_count} ---")
                # Ask if user wants to continue with next server
                choice = input("Continue with next server? [Y/n]: ").strip().lower()
                if choice == "n":
                    print("Stopping setup.")
                    break

            # Set up a single server
            server_config, service_name, port = setup_single_server(
                instance, args, existing_services, len(all_server_configs)
            )

            if server_config and service_name:
                # Add to our tracking lists
                all_server_configs.append(server_config)
                all_service_names.append(service_name)

                # Update the existing services to avoid port conflicts
                existing_services[service_name] = {
                    "port": port,
                    "running": True,
                    "service_name": service_name,
                }

                print(
                    f"Successfully set up server {len(all_server_configs)} of {server_count}"
                )

        # Create a final snapshot with all services
        if all_server_configs:
            print("\nCreating a snapshot of the configured server(s)...")
            final_snapshot = instance.snapshot()

            # Update snapshot metadata with instance information
            update_snapshot_metadata(
                final_snapshot, all_server_configs, all_service_names, instance
            )
            print(f"Final snapshot created: {final_snapshot.id}")

            # Display connection information for all servers
            display_connection_info(
                instance, all_server_configs, custom_urls=all_service_names
            )

            print(f"\nInstance ID: {instance.id}")
            print(
                f"Your MCP server{'s are' if len(all_server_configs) > 1 else ' is'} now running!"
            )
            print(f"To stop the VM later, run: morphcloud instance stop {instance.id}")
            print(
                f"To restart from snapshot, run: morphcloud instance start {final_snapshot.id}"
            )
        else:
            print("\nNo servers were successfully set up.")

    except Exception as e:
        print(f"\nSetup failed: {e}")
        print(
            "\nFor troubleshooting, try running with more detailed error information:"
        )
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
