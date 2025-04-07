# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "morphcloud",     # For instance management
#     "websockets",     # For Jupyter kernel communication
#     "jupyter_client", # For message protocol
#     "httpx",          # For HTTP requests
#     "pydantic",       # For type definitions
#     "rich"            # For nice terminal output
# ]
# ///

import asyncio
import json
import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx
import websockets
from jupyter_client.session import Session
# Import necessary libraries
from morphcloud.api import MorphCloudClient
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax

# Setup console for nice output
console = Console()


class InvalidSandboxSnapshotError(Exception):
    """Raised when a snapshot is not a valid sandbox environment."""

    pass


class JupyterMessageEncoder(json.JSONEncoder):
    """Custom JSON encoder for Jupyter messages"""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, bytes):
            return obj.decode("utf-8")
        return super().default(obj)


class JupyterKernelManager:
    """Manages connections to Jupyter kernels"""

    def __init__(self, jupyter_url: str, token: str = ""):
        self.jupyter_url = jupyter_url
        self.token = token
        self.active_kernels = {}  # kernel_id -> websocket
        self.default_kernel_id = None
        self.session = Session(key=b"", username="kernel")

    async def wait_for_service(self, timeout=30):
        """Wait for Jupyter service to be ready"""
        start_time = time.time()

        # Only include Authorization header if token is not empty
        headers = {}
        if self.token and self.token.strip():
            headers["Authorization"] = f"token {self.token}"

        console.print("[yellow]Waiting for Jupyter service to be ready...[/yellow]")
        async with httpx.AsyncClient() as client:
            while time.time() - start_time < timeout:
                try:
                    response = await client.get(
                        f"{self.jupyter_url}/api", headers=headers
                    )
                    if response.status_code == 200:
                        console.print("[green]Jupyter service is ready![/green]")
                        return True
                except Exception as e:
                    console.print(f"[dim]Still waiting... ({e})[/dim]")
                await asyncio.sleep(2)
            raise TimeoutError("Jupyter service failed to start")

    async def list_kernels(self) -> List[dict]:
        """Get list of all running kernels"""
        headers = {}
        if self.token and self.token.strip():
            headers["Authorization"] = f"token {self.token}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.jupyter_url}/api/kernels", headers=headers
            )
            response.raise_for_status()
            kernels = response.json()

            if kernels:
                console.print("[green]Found kernels:[/green]")
                for kernel in kernels:
                    console.print(f"- {kernel.get('id')} ({kernel.get('name')})")
            else:
                console.print("[yellow]No kernels found[/yellow]")

            return kernels

    async def connect_to_kernel(self, kernel_id: str):
        """Connect to an existing kernel"""
        if kernel_id in self.active_kernels:
            return self.active_kernels[kernel_id]

        # Connect to kernel websocket
        ws_url = self.jupyter_url.replace("https://", "wss://").replace(
            "http://", "ws://"
        )
        ws_endpoint = f"{ws_url}/api/kernels/{kernel_id}/channels"

        if self.token and self.token.strip():
            ws_endpoint += f"?token={self.token}"

        try:
            console.print(f"[yellow]Connecting to kernel {kernel_id}...[/yellow]")
            ws = await websockets.connect(ws_endpoint)
            self.active_kernels[kernel_id] = ws
            console.print(f"[green]Connected to kernel {kernel_id}[/green]")

            # Set as default if no default exists
            if not self.default_kernel_id:
                self.default_kernel_id = kernel_id
                console.print(f"[green]Set kernel {kernel_id} as default[/green]")

            return ws
        except Exception as e:
            console.print(f"[red]Failed to connect to kernel {kernel_id}: {e}[/red]")
            raise ConnectionError(f"Failed to connect to kernel {kernel_id}: {e}")

    async def start_new_kernel(self, kernel_name="python3") -> str:
        """Start a new kernel and return its ID"""
        headers = {}
        if self.token and self.token.strip():
            headers["Authorization"] = f"token {self.token}"

        console.print(f"[yellow]Starting new {kernel_name} kernel...[/yellow]")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.jupyter_url}/api/kernels",
                headers=headers,
                json={"name": kernel_name},
            )
            response.raise_for_status()
            kernel_info = response.json()
            kernel_id = kernel_info["id"]
            console.print(f"[green]Started new kernel with ID: {kernel_id}[/green]")

            # Connect to the new kernel
            await self.connect_to_kernel(kernel_id)
            return kernel_id

    def _prepare_message(self, msg_type: str, content: dict) -> tuple[dict, str]:
        """Prepare a Jupyter message in the correct format"""
        msg_id = str(uuid.uuid4())
        msg = {
            "header": {
                "msg_id": msg_id,
                "username": "kernel",
                "session": str(uuid.uuid4()),
                "msg_type": msg_type,
                "version": "5.0",
                "date": datetime.now().isoformat(),
            },
            "parent_header": {},
            "metadata": {},
            "content": content,
            "channel": "shell",
        }
        return msg, msg_id

    async def execute(self, code: str, kernel_id: str = None) -> dict:
        """Execute code on specified kernel or default kernel"""
        if not kernel_id:
            kernel_id = self.default_kernel_id
            if not kernel_id:
                # No default kernel, create one
                kernel_id = await self.start_new_kernel()
                self.default_kernel_id = kernel_id

        # Connect to kernel if not already connected
        if kernel_id not in self.active_kernels:
            await self.connect_to_kernel(kernel_id)

        ws = self.active_kernels[kernel_id]

        msg, msg_id = self._prepare_message(
            "execute_request",
            {
                "code": code,
                "silent": False,
                "store_history": True,
                "user_expressions": {},
                "allow_stdin": False,
                "stop_on_error": True,
            },
        )

        console.print(f"\n[bold blue]Executing code on kernel {kernel_id}:[/bold blue]")
        console.print(Syntax(code, "python", theme="monokai", line_numbers=True))
        await ws.send(json.dumps(msg, cls=JupyterMessageEncoder))

        outputs = []
        images = []  # New list to collect image data
        execution_count = None
        status = "ok"
        got_execute_input = False
        got_output = False
        got_idle = False

        # Timeout after 30 seconds
        start_time = time.time()
        timeout = 30

        while True:
            if time.time() - start_time > timeout:
                console.print("[red]Execution timed out[/red]")
                break

            try:
                # Set a timeout on receive to avoid hanging indefinitely
                response = await asyncio.wait_for(ws.recv(), timeout=5.0)
                response_data = json.loads(response)

                parent_msg_id = response_data.get("parent_header", {}).get("msg_id")
                msg_type = response_data.get("header", {}).get("msg_type")

                console.print(
                    f"[dim]Received message: {msg_type} (parent: {parent_msg_id})[/dim]"
                )

                # Only process messages related to our request
                if parent_msg_id != msg_id:
                    console.print(f"[dim]Skipping unrelated message[/dim]")
                    continue

                if msg_type == "execute_input":
                    got_execute_input = True
                    execution_count = response_data.get("content", {}).get(
                        "execution_count"
                    )

                elif msg_type == "stream":
                    got_output = True
                    text = response_data.get("content", {}).get("text", "")
                    outputs.append(text)

                elif msg_type == "execute_result":
                    got_output = True
                    data = response_data.get("content", {}).get("data", {})
                    text = data.get("text/plain", "")
                    outputs.append(text)

                    # Check for image data
                    if "image/png" in data:
                        image_data = data.get("image/png", "")
                        metadata = response_data.get("content", {}).get("metadata", {})
                        images.append(
                            {
                                "mime_type": "image/png",
                                "data": image_data,
                                "metadata": metadata,
                            }
                        )
                    elif "image/jpeg" in data:
                        image_data = data.get("image/jpeg", "")
                        metadata = response_data.get("content", {}).get("metadata", {})
                        images.append(
                            {
                                "mime_type": "image/jpeg",
                                "data": image_data,
                                "metadata": metadata,
                            }
                        )
                    elif "image/svg+xml" in data:
                        image_data = data.get("image/svg+xml", "")
                        metadata = response_data.get("content", {}).get("metadata", {})
                        images.append(
                            {
                                "mime_type": "image/svg+xml",
                                "data": image_data,
                                "metadata": metadata,
                            }
                        )

                elif msg_type == "display_data":
                    got_output = True
                    data = response_data.get("content", {}).get("data", {})
                    text = data.get("text/plain", "")
                    outputs.append(text)

                    # Check for image data
                    if "image/png" in data:
                        image_data = data.get("image/png", "")
                        metadata = response_data.get("content", {}).get("metadata", {})
                        images.append(
                            {
                                "mime_type": "image/png",
                                "data": image_data,
                                "metadata": metadata,
                            }
                        )
                    elif "image/jpeg" in data:
                        image_data = data.get("image/jpeg", "")
                        metadata = response_data.get("content", {}).get("metadata", {})
                        images.append(
                            {
                                "mime_type": "image/jpeg",
                                "data": image_data,
                                "metadata": metadata,
                            }
                        )
                    elif "image/svg+xml" in data:
                        image_data = data.get("image/svg+xml", "")
                        metadata = response_data.get("content", {}).get("metadata", {})
                        images.append(
                            {
                                "mime_type": "image/svg+xml",
                                "data": image_data,
                                "metadata": metadata,
                            }
                        )

                elif msg_type == "error":
                    got_output = True
                    status = "error"
                    traceback = response_data.get("content", {}).get("traceback", [])
                    outputs.extend(traceback)

                elif msg_type == "status":
                    if (
                        response_data.get("content", {}).get("execution_state")
                        == "idle"
                    ):
                        got_idle = True

                # Break when we've gotten all expected messages
                if got_idle and (got_output or got_execute_input):
                    # Add a small delay to ensure we've gotten all messages
                    await asyncio.sleep(0.1)
                    break

            except asyncio.TimeoutError:
                console.print("[yellow]Waiting for more output...[/yellow]")
                continue
            except Exception as e:
                console.print(f"[red]Error processing message: {e}[/red]")
                break

        # Create result dictionary with basic fields
        result = {
            "status": status,
            "execution_count": execution_count,
            "output": "\n".join(outputs).strip(),
            "kernel_id": kernel_id,
        }

        # Only add images field if we have images
        if images:
            result["images"] = images
            console.print(f"[green]Captured {len(images)} image(s)[/green]")

        if result["status"] == "ok":
            console.print("[green]Execution completed successfully[/green]")
        else:
            console.print("[red]Execution failed[/red]")

        if result["output"]:
            console.print("\n[bold]Output:[/bold]")
            console.print(result["output"])

        return result

    async def interrupt_kernel(self, kernel_id: str = None):
        """Send interrupt signal to the kernel"""
        if not kernel_id:
            kernel_id = self.default_kernel_id
        if not kernel_id:
            raise ValueError("No kernel specified and no default kernel")

        console.print(f"[yellow]Interrupting kernel {kernel_id}...[/yellow]")

        # Only include Authorization header if token is not empty
        headers = {}
        if self.token and self.token.strip():
            headers["Authorization"] = f"token {self.token}"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.jupyter_url}/api/kernels/{kernel_id}/interrupt", headers=headers
            )
            response.raise_for_status()
            console.print(f"[green]Kernel {kernel_id} interrupted[/green]")
            return response.json()

    async def restart_kernel(self, kernel_id: str = None):
        """Restart the kernel"""
        if not kernel_id:
            kernel_id = self.default_kernel_id
        if not kernel_id:
            raise ValueError("No kernel specified and no default kernel")

        console.print(f"[yellow]Restarting kernel {kernel_id}...[/yellow]")

        # Only include Authorization header if token is not empty
        headers = {}
        if self.token and self.token.strip():
            headers["Authorization"] = f"token {self.token}"

        # Close existing websocket if it exists
        if kernel_id in self.active_kernels:
            await self.active_kernels[kernel_id].close()
            del self.active_kernels[kernel_id]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.jupyter_url}/api/kernels/{kernel_id}/restart", headers=headers
            )
            response.raise_for_status()
            console.print(f"[green]Kernel {kernel_id} restarted[/green]")

            # Reconnect to the restarted kernel
            await self.connect_to_kernel(kernel_id)
            return response.json()

    async def close(self):
        """Close all kernel connections"""
        for kernel_id, ws in list(self.active_kernels.items()):
            console.print(f"[yellow]Closing connection to kernel {kernel_id}[/yellow]")
            await ws.close()
            del self.active_kernels[kernel_id]
        self.default_kernel_id = None
        console.print("[green]All kernel connections closed[/green]")


class JupyterNotebookClient:
    """Client for interacting with Jupyter notebooks via HTTP API"""

    def __init__(self, jupyter_url: str, token: str = ""):
        self.jupyter_url = jupyter_url
        self.token = token

        # Only include token in headers if it's not empty
        self.headers = {}
        if token and token.strip():
            self.headers["Authorization"] = f"token {token}"

        self.kernel_manager = JupyterKernelManager(jupyter_url, token)

    async def wait_for_service(self, timeout=30):
        """Wait for Jupyter service to be ready"""
        return await self.kernel_manager.wait_for_service(timeout)

    async def start(self):
        """Initialize the client and kernel connection"""
        await self.wait_for_service()
        return await self.kernel_manager.start_new_kernel()

    async def connect_to_existing(self):
        """Connect to existing kernels if available"""
        await self.wait_for_service()
        kernels = await self.kernel_manager.list_kernels()

        if not kernels:
            console.print(
                "[yellow]No existing kernels found, starting a new one[/yellow]"
            )
            await self.kernel_manager.start_new_kernel()
        else:
            for kernel in kernels:
                try:
                    await self.kernel_manager.connect_to_kernel(kernel["id"])
                except Exception as e:
                    console.print(
                        f"[yellow]Warning: Failed to connect to kernel {kernel['id']}: {e}[/yellow]"
                    )

        return self.kernel_manager.default_kernel_id

    async def close(self):
        """Close all connections"""
        await self.kernel_manager.close()

    async def list_notebooks(self, path: str = ""):
        """List all notebooks in a directory"""
        console.print(f"[yellow]Listing notebooks in path: '{path}'[/yellow]")
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.jupyter_url}/api/contents/{path}", headers=self.headers
            )
            response.raise_for_status()
            result = response.json()

            # Extract notebook information
            notebooks = [
                item
                for item in result.get("content", [])
                if item.get("type") == "notebook"
            ]

            if notebooks:
                console.print("[green]Found notebooks:[/green]")
                for nb in notebooks:
                    console.print(
                        f"- {nb['name']} (Last modified: {nb['last_modified']})"
                    )
            else:
                console.print("[yellow]No notebooks found[/yellow]")

            return result

    async def create_notebook(self, path: str, kernel_name: str = "python3"):
        """Create a new empty notebook"""
        # Minimal notebook format
        notebook = {
            "metadata": {
                "kernelspec": {
                    "name": kernel_name,
                    "display_name": "Python 3",
                    "language": "python",
                }
            },
            "nbformat": 4,
            "nbformat_minor": 5,
            "cells": [],
        }

        console.print(f"[yellow]Creating notebook: {path}[/yellow]")
        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{self.jupyter_url}/api/contents/{path}",
                headers=self.headers,
                json={"type": "notebook", "content": notebook},
            )
            response.raise_for_status()
            result = response.json()
            console.print(f"[green]Notebook created: {result['path']}[/green]")
            return result

    async def get_notebook(self, path: str):
        """Get a notebook by path"""
        console.print(f"[yellow]Getting notebook: {path}[/yellow]")
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.jupyter_url}/api/contents/{path}", headers=self.headers
            )
            response.raise_for_status()
            result = response.json()
            console.print(f"[green]Retrieved notebook: {result['path']}[/green]")
            return result

    async def save_notebook(self, path: str, notebook_content: dict):
        """Save notebook content"""
        console.print(f"[yellow]Saving notebook: {path}[/yellow]")
        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{self.jupyter_url}/api/contents/{path}",
                headers=self.headers,
                json={"type": "notebook", "content": notebook_content},
            )
            response.raise_for_status()
            result = response.json()
            console.print(f"[green]Notebook saved: {result['path']}[/green]")
            return result

    async def add_cell(
        self,
        notebook_path: str,
        cell_content: str,
        cell_type: str = "code",
        index: int = None,
    ):
        """Add a cell to a notebook"""
        console.print(
            f"[yellow]Adding {cell_type} cell to notebook: {notebook_path}[/yellow]"
        )

        # Get current notebook content
        notebook_data = await self.get_notebook(notebook_path)
        notebook = notebook_data["content"]

        # Create new cell
        new_cell = {"cell_type": cell_type, "metadata": {}, "source": cell_content}

        # Add outputs array for code cells
        if cell_type == "code":
            new_cell["execution_count"] = None
            new_cell["outputs"] = []

        # Insert at specified index or append
        if index is not None:
            notebook["cells"].insert(index, new_cell)
            console.print(f"[green]Cell inserted at index {index}[/green]")
        else:
            notebook["cells"].append(new_cell)
            console.print(
                f"[green]Cell appended at index {len(notebook['cells'])-1}[/green]"
            )

        # Save updated notebook
        result = await self.save_notebook(notebook_path, notebook)

        # Return cell index
        cell_index = index if index is not None else len(notebook["cells"]) - 1
        return {"index": cell_index, "cell": new_cell}

    async def execute_cell(
        self, notebook_path: str, cell_index: int, kernel_id: str = None
    ):
        """Execute a specific cell in a notebook"""
        # Get the notebook
        notebook_data = await self.get_notebook(notebook_path)
        notebook = notebook_data["content"]

        # Verify cell index
        if cell_index < 0 or cell_index >= len(notebook["cells"]):
            raise ValueError(
                f"Cell index {cell_index} out of range for notebook with {len(notebook['cells'])} cells"
            )

        # Get the cell
        cell = notebook["cells"][cell_index]

        # Only code cells can be executed
        if cell["cell_type"] != "code":
            raise ValueError(
                f"Cell {cell_index} is not a code cell (type: {cell['cell_type']})"
            )

        # Get the cell content
        code = cell["source"]

        console.print(
            f"[yellow]Executing cell {cell_index} in notebook {notebook_path}[/yellow]"
        )

        # Execute the code
        result = await self.kernel_manager.execute(code, kernel_id)

        # Update the cell with the result
        cell["execution_count"] = result["execution_count"]

        # Add output to the cell
        if result["status"] == "ok":
            if result["output"]:
                cell["outputs"] = [
                    {
                        "output_type": "stream",
                        "name": "stdout",
                        "text": result["output"],
                    }
                ]
        else:
            cell["outputs"] = [
                {
                    "output_type": "error",
                    "ename": "Error",
                    "evalue": "Execution failed",
                    "traceback": result["output"].split("\n"),
                }
            ]

        # Save the updated notebook
        await self.save_notebook(notebook_path, notebook)

        return result

    async def execute_notebook(self, notebook_path: str, kernel_id: str = None):
        """Execute all code cells in a notebook in order"""
        console.print(
            f"[yellow]Executing all cells in notebook: {notebook_path}[/yellow]"
        )

        # Get the notebook
        notebook_data = await self.get_notebook(notebook_path)
        notebook = notebook_data["content"]

        results = []

        # Execute each code cell
        for i, cell in enumerate(notebook["cells"]):
            if cell["cell_type"] == "code":
                console.print(f"[yellow]Executing cell {i}...[/yellow]")
                try:
                    result = await self.execute_cell(notebook_path, i, kernel_id)
                    results.append({"index": i, "status": result["status"]})
                    console.print(f"[green]Cell {i} execution complete[/green]")
                except Exception as e:
                    console.print(f"[red]Error executing cell {i}: {e}[/red]")
                    results.append({"index": i, "status": "error", "error": str(e)})

        console.print("[green]Notebook execution complete[/green]")
        return results

    async def delete_notebook(self, path: str):
        """Delete a notebook by path"""
        console.print(f"[yellow]Deleting notebook: {path}[/yellow]")
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self.jupyter_url}/api/contents/{path}", headers=self.headers
            )
            response.raise_for_status()
            console.print(f"[green]Notebook deleted: {path}[/green]")
            return True

    async def execute_code(self, code: str, kernel_id: str = None):
        """Execute code directly on a kernel"""
        return await self.kernel_manager.execute(code, kernel_id)


class SandboxState:
    """Represents the state of a sandbox instance."""

    def __init__(self):
        self.jupyter_url = None
        self.active_kernels = []
        self.exposed_services = {}
        self.installed_packages = []


class MorphSandbox:
    """Main class for managing a computational sandbox based on MorphCloud and JupyterLab."""

    def __init__(self):
        """Initialize the MorphSandbox."""
        self.client = MorphCloudClient()
        self.instance = None
        self.jupyter_url = None
        self.jupyter_client = None
        self.state = SandboxState()

    @classmethod
    async def create(
        cls, snapshot_id=None, verify=True, ttl_seconds=None, ttl_action="stop"
    ):
        """Create a new sandbox from scratch or from a snapshot.

        Args:
            snapshot_id: Optional ID of a snapshot to start from
            verify: Whether to verify the snapshot contains a valid sandbox environment
            ttl_seconds: Optional time-to-live in seconds for the instance
            ttl_action: Action to take when TTL expires, either "stop" or "pause"

        Returns:
            MorphSandbox: An initialized sandbox instance

        Raises:
            InvalidSandboxSnapshotError: If the snapshot is not a valid sandbox environment
        """
        sandbox = cls()

        if snapshot_id:
            console.print(
                f"[yellow]Starting sandbox from snapshot {snapshot_id}...[/yellow]"
            )
            try:
                sandbox.instance = await sandbox.client.instances.astart(
                    snapshot_id, ttl_seconds=ttl_seconds, ttl_action=ttl_action
                )
                console.print(f"[green]Instance started: {sandbox.instance.id}[/green]")

                if ttl_seconds:
                    console.print(
                        f"[yellow]Instance will {ttl_action} after {ttl_seconds} seconds[/yellow]"
                    )

                # Wait for the instance to be ready
                console.print("[yellow]Waiting for instance to be ready...[/yellow]")
                await sandbox.instance.await_until_ready()
                console.print("[green]Instance is ready![/green]")

                # Verify the snapshot if requested
                if verify:
                    await sandbox._verify_snapshot_services()
            except Exception as e:
                # Clean up in case of error
                if sandbox.instance:
                    console.print("[yellow]Stopping instance due to error...[/yellow]")
                    await sandbox.instance.astop()
                    sandbox.instance = None

                # Raise a specific error
                raise InvalidSandboxSnapshotError(
                    f"Snapshot {snapshot_id} is not a valid sandbox: {str(e)}\n"
                    "Please create a new sandbox with MorphSandbox.create()"
                ) from e
        else:
            console.print("[yellow]Creating new sandbox from scratch...[/yellow]")
            snapshot = await sandbox._setup_jupyterlab_instance()

            # Start an instance from the snapshot
            console.print("[yellow]Starting instance from snapshot...[/yellow]")
            sandbox.instance = await sandbox.client.instances.astart(
                snapshot.id, ttl_seconds=ttl_seconds, ttl_action=ttl_action
            )
            console.print(f"[green]Instance started: {sandbox.instance.id}[/green]")

            if ttl_seconds:
                console.print(
                    f"[yellow]Instance will {ttl_action} after {ttl_seconds} seconds[/yellow]"
                )

            # Wait for instance to be ready
            console.print("[yellow]Waiting for instance to be ready...[/yellow]")
            await sandbox.instance.await_until_ready()
            console.print("[green]Instance is ready![/green]")

        # Initialize Jupyter client by discovering the service
        await sandbox._discover_services()
        sandbox.jupyter_client = JupyterNotebookClient(sandbox.jupyter_url)

        # Connect to existing kernels or start new ones
        await sandbox.jupyter_client.connect_to_existing()

        # Capture the initial state
        await sandbox._capture_state()

        return sandbox

    async def _verify_snapshot_services(self):
        """Verify all required services are present and running."""
        console.print("[yellow]Verifying sandbox snapshot...[/yellow]")
        try:
            # Check required files exist
            result = await self.instance.aexec(
                """
                test -f /root/start_jupyter.sh && \
                test -d /root/notebooks && \
                test -d /root/venv && \
                systemctl is-active jupyter
            """
            )
            if result.exit_code != 0:
                raise InvalidSandboxSnapshotError(
                    f"Missing required files or services: {result.stdout} {result.stderr}"
                )
            console.print("[green]Required files and directories verified[/green]")

            # Check JupyterLab is responding
            result = await self.instance.aexec(
                "curl -s http://localhost:8888/api/status"
            )
            if result.exit_code != 0:
                console.print(
                    "[yellow]JupyterLab service not responding, attempting to restart...[/yellow]"
                )
                # Try restarting service
                await self.instance.aexec("systemctl restart jupyter")
                await asyncio.sleep(5)

                # Check again
                result = await self.instance.aexec(
                    "curl -s http://localhost:8888/api/status"
                )
                if result.exit_code != 0:
                    raise InvalidSandboxSnapshotError(
                        f"JupyterLab service not responding after restart: {result.stdout} {result.stderr}"
                    )
            console.print("[green]JupyterLab service verified[/green]")

            # Verify Python environment
            result = await self.instance.aexec(
                """
                source /root/venv/bin/activate && \
                python3 -c "import jupyter_core; print('Jupyter installed')"
            """
            )
            if result.exit_code != 0 or "Jupyter installed" not in result.stdout:
                raise InvalidSandboxSnapshotError(
                    f"Python environment not valid: {result.stdout} {result.stderr}"
                )
            console.print("[green]Python environment verified[/green]")

            console.print("[green]Snapshot verification successful[/green]")

        except Exception as e:
            raise InvalidSandboxSnapshotError(f"Verification failed: {str(e)}")

    async def _discover_services(self):
        """Discover existing exposed services from snapshot."""
        console.print("[yellow]Discovering exposed services...[/yellow]")

        # Get the list of HTTP services
        services = self.instance.networking.http_services

        # Find JupyterLab service (typically on port 8888)
        jupyter_service = next((s for s in services if s.port == 8888), None)

        if not jupyter_service:
            console.print(
                "[yellow]JupyterLab service not found, exposing it now...[/yellow]"
            )
            self.jupyter_url = await self.instance.aexpose_http_service(
                "jupyterlab", 8888
            )
        else:
            self.jupyter_url = jupyter_service.url

        console.print(
            f"[green]JupyterLab service available at: {self.jupyter_url}[/green]"
        )

        # Store all discovered services in state
        self.state.exposed_services = {s.name: s.url for s in services}

        return self.jupyter_url

    async def _capture_state(self):
        """Capture current state of sandbox for monitoring/recovery."""
        console.print("[yellow]Capturing sandbox state...[/yellow]")

        # Store Jupyter URL
        self.state.jupyter_url = self.jupyter_url

        # Get active kernels
        if self.jupyter_client:
            self.state.active_kernels = (
                await self.jupyter_client.kernel_manager.list_kernels()
            )

        # Get installed packages
        result = await self.instance.aexec(
            "source /root/venv/bin/activate && pip freeze"
        )
        self.state.installed_packages = result.stdout.splitlines()

        console.print(
            f"[green]State captured: {len(self.state.active_kernels)} kernels, {len(self.state.installed_packages)} packages[/green]"
        )
        return self.state

    async def _setup_jupyterlab_instance(self):
        """Set up a JupyterLab instance in Morph and return the snapshot"""
        console.print("\n[bold blue]🚀 Setting up JupyterLab Instance[/bold blue]\n")

        # Start with base snapshot
        console.print("[yellow]Creating base snapshot...[/yellow]")
        base_snapshot = await self.client.snapshots.acreate(
            vcpus=4,
            memory=16384,  # 16GB RAM
            disk_size=40960,  # 40GB disk
            digest="jupyterlab-base-v1",
        )
        console.print(f"[green]Created base snapshot: {base_snapshot.id}[/green]")

        # Setup base system
        console.print("\n[yellow]Installing system dependencies...[/yellow]")
        snapshot = await base_snapshot.asetup(
            """
            apt-get update && \
            apt-get install -y python3 python3-pip python3-venv curl net-tools jq && \
            python3 --version
        """
        )

        # Create virtual environment and install packages
        console.print(
            "\n[yellow]Setting up Python environment and installing JupyterLab...[/yellow]"
        )
        snapshot = await snapshot.asetup(
            """
            # Create directories
            mkdir -p /root/notebooks /root/data /root/logs
            
            # Create virtual environment
            python3 -m venv /root/venv
            
            # Activate virtual environment and install packages
            source /root/venv/bin/activate && \
            pip install --upgrade pip && \
            pip install \
                jupyterlab \
                notebook \
                ipykernel \
                pandas \
                numpy \
                matplotlib \
                scikit-learn \
                seaborn \
                plotly
        """
        )

        # Verify installations
        console.print("\n[yellow]Verifying JupyterLab installation...[/yellow]")
        snapshot = await snapshot.asetup(
            """
            source /root/venv/bin/activate && \
            python3 --version && \
            jupyter --version && \
            jupyter lab --version
        """
        )

        # Create startup script
        console.print("\n[yellow]Creating JupyterLab startup script...[/yellow]")
        jupyter_startup_script = """#!/bin/bash
source /root/venv/bin/activate

# Create empty token file for compatibility with existing code
echo "" > /root/jupyter_token.txt
echo "Token authentication disabled for easier access"

# Start JupyterLab
jupyter lab \
    --no-browser \
    --ServerApp.token="" \
    --ServerApp.password="" \
    --ServerApp.allow_origin='*' \
    --ServerApp.ip=0.0.0.0 \
    --ServerApp.port=8888 \
    --ServerApp.allow_remote_access=True \
    --ServerApp.disable_check_xsrf=True \
    --notebook-dir=/root/notebooks \
    --ServerApp.terminado_settings="{'shell_command': ['/bin/bash']}" \
    --allow-root \
    >> /root/logs/jupyter.log 2>&1
"""

        snapshot = await snapshot.asetup(
            f"""
            cat > /root/start_jupyter.sh << 'EOL'
{jupyter_startup_script}
EOL
            chmod +x /root/start_jupyter.sh
        """
        )

        # Create a systemd service to start JupyterLab at boot
        console.print("\n[yellow]Creating JupyterLab service...[/yellow]")
        jupyter_service = """[Unit]
Description=JupyterLab Service
After=network.target

[Service]
Type=simple
User=root
ExecStart=/root/start_jupyter.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""

        snapshot = await snapshot.asetup(
            f"""
            cat > /etc/systemd/system/jupyter.service << 'EOL'
{jupyter_service}
EOL
            systemctl daemon-reload
            systemctl enable jupyter.service
        """
        )

        # Start JupyterLab service
        console.print("\n[yellow]Starting JupyterLab service...[/yellow]")
        snapshot = await snapshot.asetup(
            """
            # Start service
            systemctl start jupyter
            
            # Check status
            sleep 5
            systemctl status jupyter
            ps aux | grep jupyter
            netstat -tulpn | grep 8888
            
            # Show logs
            echo "JupyterLab logs:"
            tail -n 20 /root/logs/jupyter.log
        """
        )

        # Create a sample notebook
        console.print("\n[yellow]Creating sample notebook...[/yellow]")
        sample_notebook = """#!/bin/bash
source /root/venv/bin/activate

# Create a sample notebook
cat > /root/notebooks/welcome.ipynb << 'EOL'
{
 "cells": [
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "# Welcome to JupyterLab!\n",
    "\n",
    "This notebook was created automatically during setup. You can use it to verify your installation."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": [
    "import sys\n",
    "print(f\"Python version: {sys.version}\")\n",
    "\n",
    "# List installed packages\n",
    "import pkg_resources\n",
    "packages = sorted([f\"{pkg.key}=={pkg.version}\" for pkg in pkg_resources.working_set])\n",
    "print(\"\\nInstalled packages:\")\n",
    "for pkg in packages[:10]:  # Show first 10 packages\n",
    "    print(f\"  {pkg}\")\n",
    "print(f\"...and {len(packages)-10} more\")"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## Testing NumPy and Matplotlib"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": [
    "import numpy as np\n",
    "import matplotlib.pyplot as plt\n",
    "\n",
    "# Generate some data\n",
    "x = np.linspace(0, 10, 100)\n",
    "y = np.sin(x)\n",
    "\n",
    "# Create a plot\n",
    "plt.figure(figsize=(10, 6))\n",
    "plt.plot(x, y, 'b-', label='sin(x)')\n",
    "plt.title('Sine Wave')\n",
    "plt.xlabel('x')\n",
    "plt.ylabel('sin(x)')\n",
    "plt.grid(True)\n",
    "plt.legend()\n",
    "plt.show()"
   ]
  }
 ],
 "metadata": {
  "kernelspec": {
   "display_name": "Python 3",
   "language": "python",
   "name": "python3"
  },
  "language_info": {
   "codemirror_mode": {
    "name": "ipython",
    "version": 3
   },
   "file_extension": ".py",
   "mimetype": "text/x-python",
   "name": "python",
   "nbconvert_exporter": "python",
   "pygments_lexer": "ipython3",
   "version": "3.10.12"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 4
}
EOL

echo "Sample notebook created"
"""

        snapshot = await snapshot.asetup(
            f"""
            cat > /root/create_sample.sh << 'EOL'
{sample_notebook}
EOL
            chmod +x /root/create_sample.sh
            /root/create_sample.sh
        """
        )

        console.print("\n[bold green]✅ JupyterLab setup complete![/bold green]")
        return snapshot

    async def snapshot(self, digest=None):
        """Create a snapshot of the current sandbox state."""
        if not self.instance:
            raise ValueError("Cannot create snapshot: No active instance")

        console.print(
            f"[yellow]Creating snapshot{' with digest '+digest if digest else ''}...[/yellow]"
        )
        snapshot = await self.instance.asnapshot(digest=digest)
        console.print(f"[green]Snapshot created with ID: {snapshot.id}[/green]")

        return snapshot.id

    async def stop(self):
        """Stop the sandbox instance."""
        if self.instance:
            console.print("[yellow]Stopping sandbox instance...[/yellow]")

            # Close Jupyter client first
            if self.jupyter_client:
                await self.jupyter_client.close()

            # Then stop the instance
            await self.instance.astop()
            self.instance = None
            console.print("[green]Sandbox instance stopped[/green]")

    # Context manager support
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    # Notebook operations
    async def list_notebooks(self, path=""):
        """List all notebooks in the specified path."""
        if not self.jupyter_client:
            raise ValueError("Jupyter client not initialized")

        return await self.jupyter_client.list_notebooks(path)

    async def create_notebook(self, name, kernel="python3"):
        """Create a new notebook with the given name."""
        if not self.jupyter_client:
            raise ValueError("Jupyter client not initialized")

        return await self.jupyter_client.create_notebook(name, kernel_name=kernel)

    async def get_notebook(self, path):
        """Get a notebook by path."""
        if not self.jupyter_client:
            raise ValueError("Jupyter client not initialized")

        return await self.jupyter_client.get_notebook(path)

    async def delete_notebook(self, path):
        """Delete a notebook by path."""
        if not self.jupyter_client:
            raise ValueError("Jupyter client not initialized")

        return await self.jupyter_client.delete_notebook(path)

    async def add_cell(self, notebook_path, content, cell_type="code", index=None):
        """Add a cell to a notebook."""
        if not self.jupyter_client:
            raise ValueError("Jupyter client not initialized")

        return await self.jupyter_client.add_cell(
            notebook_path, content, cell_type, index
        )

    async def execute_cell(self, notebook_path, cell_index, kernel_id=None):
        """Execute a specific cell in a notebook."""
        if not self.jupyter_client:
            raise ValueError("Jupyter client not initialized")

        return await self.jupyter_client.execute_cell(
            notebook_path, cell_index, kernel_id
        )

    async def execute_notebook(self, notebook_path, kernel_id=None):
        """Execute all code cells in a notebook in order."""
        if not self.jupyter_client:
            raise ValueError("Jupyter client not initialized")

        return await self.jupyter_client.execute_notebook(notebook_path, kernel_id)

    async def list_kernels(self):
        """List all available kernels."""
        if not self.jupyter_client:
            raise ValueError("Jupyter client not initialized")

        return await self.jupyter_client.kernel_manager.list_kernels()

    async def start_new_kernel(self, kernel_name="python3"):
        """Start a new kernel and return its ID."""
        if not self.jupyter_client:
            raise ValueError("Jupyter client not initialized")

        return await self.jupyter_client.kernel_manager.start_new_kernel(kernel_name)

    async def restart_kernel(self, kernel_id=None):
        """Restart specified kernel or default kernel."""
        if not self.jupyter_client:
            raise ValueError("Jupyter client not initialized")

        return await self.jupyter_client.kernel_manager.restart_kernel(kernel_id)

    async def interrupt_kernel(self, kernel_id=None):
        """Interrupt specified kernel or default kernel."""
        if not self.jupyter_client:
            raise ValueError("Jupyter client not initialized")

        return await self.jupyter_client.kernel_manager.interrupt_kernel(kernel_id)

    # Direct code execution
    async def execute_code(self, code, kernel_id=None):
        """Execute code directly using the kernel client."""
        if not self.jupyter_client:
            raise ValueError("Jupyter client not initialized")

        return await self.jupyter_client.execute_code(code, kernel_id)

    # File operations
    async def upload_file(self, local_path, remote_path, recursive=False):
        """Upload a file or directory to the sandbox using SFTP.

        Args:
            local_path (str): Path to the local file or directory
            remote_path (str): Path on the remote instance
            recursive (bool, optional): Whether to copy directories recursively. Defaults to False.

        Returns:
            bool: True if the upload was successful

        Raises:
            ValueError: If no active instance is available
        """
        import os
        import pathlib
        import stat

        if not self.instance:
            raise ValueError("No active instance")

        console.print(f"[yellow]Uploading: {local_path} -> {remote_path}[/yellow]")

        # Make sure the instance is ready
        await self.instance.await_until_ready()

        # Create an SSH connection and SFTP client
        with self.instance.ssh() as ssh:
            sftp = ssh._client.open_sftp()
            try:
                # Helper function to recursively create directories on remote
                def ensure_remote_dir(path):
                    try:
                        sftp.stat(path)
                    except FileNotFoundError:
                        # Directory doesn't exist, create it
                        try:
                            sftp.mkdir(path)
                        except FileNotFoundError:
                            # Parent directory doesn't exist, create it recursively
                            ensure_remote_dir(os.path.dirname(path))
                            sftp.mkdir(path)

                # Helper function to recursively upload a directory
                def upload_recursive(local_dir, remote_dir):
                    local_path_obj = pathlib.Path(local_dir)

                    # Make sure remote directory exists
                    try:
                        sftp.stat(remote_dir)
                    except FileNotFoundError:
                        ensure_remote_dir(remote_dir)

                    # Upload all items in the directory
                    for item in local_path_obj.iterdir():
                        local_item_path = str(item)
                        remote_item_path = os.path.join(remote_dir, item.name)

                        if item.is_dir():
                            upload_recursive(local_item_path, remote_item_path)
                        else:
                            try:
                                sftp.put(local_item_path, remote_item_path)
                            except FileNotFoundError:
                                # Create parent directory if needed
                                ensure_remote_dir(os.path.dirname(remote_item_path))
                                sftp.put(local_item_path, remote_item_path)

                # Logic for handling the upload
                local_path_obj = pathlib.Path(local_path)

                if recursive and local_path_obj.is_dir():
                    upload_recursive(local_path, remote_path)
                else:
                    # For single file upload
                    try:
                        sftp.put(local_path, remote_path)
                    except FileNotFoundError:
                        # Create parent directory if needed
                        ensure_remote_dir(os.path.dirname(remote_path))
                        sftp.put(local_path, remote_path)
            finally:
                sftp.close()

        console.print(f"[green]Upload completed: {local_path} -> {remote_path}[/green]")
        return True

    async def download_file(self, remote_path, local_path, recursive=False):
        """Download a file or directory from the sandbox using SFTP.

        Args:
            remote_path (str): Path on the remote instance
            local_path (str): Path to save the file locally
            recursive (bool, optional): Whether to copy directories recursively. Defaults to False.

        Returns:
            bool: True if the download was successful

        Raises:
            ValueError: If no active instance is available
        """
        import os
        import pathlib
        import stat

        if not self.instance:
            raise ValueError("No active instance")

        console.print(f"[yellow]Downloading: {remote_path} -> {local_path}[/yellow]")

        # Make sure the instance is ready
        await self.instance.await_until_ready()

        # Create an SSH connection and SFTP client
        with self.instance.ssh() as ssh:
            sftp = ssh._client.open_sftp()
            try:
                # Helper function to recursively download a directory
                def download_recursive(remote_dir, local_dir):
                    local_path_obj = pathlib.Path(local_dir)

                    # Make sure local directory exists
                    local_path_obj.mkdir(parents=True, exist_ok=True)

                    # Get remote directory contents
                    items = sftp.listdir_attr(remote_dir)

                    # Download all items
                    for item in items:
                        remote_item_path = os.path.join(remote_dir, item.filename)
                        local_item_path = local_path_obj / item.filename

                        if stat.S_ISDIR(item.st_mode):
                            download_recursive(remote_item_path, local_item_path)
                        else:
                            # Ensure parent dir exists (should already, but just in case)
                            local_item_path.parent.mkdir(parents=True, exist_ok=True)
                            sftp.get(remote_item_path, str(local_item_path))

                # Logic for handling the download
                local_path_obj = pathlib.Path(local_path)

                try:
                    # Check if remote path is a directory
                    remote_stat = sftp.stat(remote_path)
                    is_dir = stat.S_ISDIR(remote_stat.st_mode)

                    if recursive and is_dir:
                        download_recursive(remote_path, local_path)
                    else:
                        # For single file download
                        # Make sure parent directory exists
                        local_path_obj.parent.mkdir(parents=True, exist_ok=True)
                        sftp.get(remote_path, str(local_path_obj))
                except FileNotFoundError:
                    console.print(
                        f"[red]Error: Remote path '{remote_path}' not found[/red]"
                    )
                    raise
            finally:
                sftp.close()

        console.print(
            f"[green]Download completed: {remote_path} -> {local_path}[/green]"
        )
        return True

    async def copy_files(self, source, destination, recursive=False):
        """Copy files to or from the sandbox.

        This is a more general version of upload_file and download_file that can
        handle both directions.

        Args:
            source (str): Source path. For uploads, a local path. For downloads,
                          use format ":/remote/path" to indicate a remote path.
            destination (str): Destination path. For uploads, use format ":/remote/path"
                              to indicate a remote path. For downloads, a local path.
            recursive (bool, optional): Whether to copy directories recursively. Defaults to False.

        Returns:
            bool: True if the copy was successful

        Raises:
            ValueError: If no active instance is available or if paths are invalid
        """
        if not self.instance:
            raise ValueError("No active instance")

        # Determine if this is an upload or download
        is_upload = not source.startswith(":") and destination.startswith(":")
        is_download = source.startswith(":") and not destination.startswith(":")

        if not (is_upload or is_download):
            raise ValueError(
                "Either source or destination must be a remote path (starting with ':'), but not both"
            )

        if is_upload:
            # Upload: local -> remote
            remote_path = destination[1:]  # Remove the leading ':'
            return await self.upload_file(source, remote_path, recursive=recursive)
        else:
            # Download: remote -> local
            remote_path = source[1:]  # Remove the leading ':'
            return await self.download_file(
                remote_path, destination, recursive=recursive
            )

    async def list_remote_files(self, remote_path):
        """List files in a remote directory.

        Args:
            remote_path (str): Path on the remote instance

        Returns:
            list: List of dictionaries containing file information

        Raises:
            ValueError: If no active instance is available
        """
        import stat

        if not self.instance:
            raise ValueError("No active instance")

        console.print(f"[yellow]Listing files in: {remote_path}[/yellow]")

        # Make sure the instance is ready
        await self.instance.await_until_ready()

        files = []

        # Create an SSH connection and SFTP client
        with self.instance.ssh() as ssh:
            sftp = ssh._client.open_sftp()
            try:
                # List directory contents with attributes
                items = sftp.listdir_attr(remote_path)

                for item in items:
                    file_type = "directory" if stat.S_ISDIR(item.st_mode) else "file"
                    size = item.st_size

                    # Format permissions similar to ls -l
                    perms = ""
                    perms += "d" if stat.S_ISDIR(item.st_mode) else "-"
                    perms += "r" if item.st_mode & stat.S_IRUSR else "-"
                    perms += "w" if item.st_mode & stat.S_IWUSR else "-"
                    perms += "x" if item.st_mode & stat.S_IXUSR else "-"
                    perms += "r" if item.st_mode & stat.S_IRGRP else "-"
                    perms += "w" if item.st_mode & stat.S_IWGRP else "-"
                    perms += "x" if item.st_mode & stat.S_IXGRP else "-"
                    perms += "r" if item.st_mode & stat.S_IROTH else "-"
                    perms += "w" if item.st_mode & stat.S_IWOTH else "-"
                    perms += "x" if item.st_mode & stat.S_IXOTH else "-"

                    # Get modification time
                    mtime = time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(item.st_mtime)
                    )

                    files.append(
                        {
                            "name": item.filename,
                            "type": file_type,
                            "size": size,
                            "permissions": perms,
                            "modified": mtime,
                        }
                    )
            except FileNotFoundError:
                console.print(
                    f"[red]Error: Remote path '{remote_path}' not found[/red]"
                )
                raise
            finally:
                sftp.close()

        # Print a nice table of results
        if files:
            console.print("\n[green]Files found:[/green]")
            for file in files:
                icon = "📁" if file["type"] == "directory" else "📄"
                console.print(
                    f"{icon} {file['name']} ({file['size']} bytes, {file['modified']})"
                )
        else:
            console.print("[yellow]No files found[/yellow]")

        return files

    async def ensure_remote_directory(self, remote_path):
        """Create a directory on the remote instance, including parent directories.

        Args:
            remote_path (str): Path to create on the remote instance

        Returns:
            bool: True if successful

        Raises:
            ValueError: If no active instance is available
        """
        import os

        if not self.instance:
            raise ValueError("No active instance")

        console.print(f"[yellow]Creating remote directory: {remote_path}[/yellow]")

        # Make sure the instance is ready
        await self.instance.await_until_ready()

        with self.instance.ssh() as ssh:
            sftp = ssh._client.open_sftp()
            try:
                # Helper function to recursively create directories
                def create_dir_recursive(path):
                    try:
                        sftp.stat(path)
                    except FileNotFoundError:
                        # Directory doesn't exist, create it
                        try:
                            sftp.mkdir(path)
                        except FileNotFoundError:
                            # Parent directory doesn't exist, create it recursively
                            create_dir_recursive(os.path.dirname(path))
                            sftp.mkdir(path)

                create_dir_recursive(remote_path)
                console.print(f"[green]Remote directory created: {remote_path}[/green]")
                return True
            finally:
                sftp.close()

    async def remove_remote_file(self, remote_path, recursive=False):
        """Remove a file or directory from the remote instance.

        Args:
            remote_path (str): Path on the remote instance
            recursive (bool, optional): Whether to remove directories recursively. Defaults to False.

        Returns:
            bool: True if successful

        Raises:
            ValueError: If no active instance is available
        """
        import stat

        if not self.instance:
            raise ValueError("No active instance")

        console.print(f"[yellow]Removing remote path: {remote_path}[/yellow]")

        # Make sure the instance is ready
        await self.instance.await_until_ready()

        with self.instance.ssh() as ssh:
            sftp = ssh._client.open_sftp()
            try:
                # Helper function to recursively remove directories
                def remove_recursive(path):
                    try:
                        attr = sftp.stat(path)

                        if stat.S_ISDIR(attr.st_mode):
                            # It's a directory - list contents and remove each item
                            for item in sftp.listdir(path):
                                item_path = f"{path}/{item}"
                                remove_recursive(item_path)

                            # Remove the now-empty directory
                            sftp.rmdir(path)
                        else:
                            # It's a file - remove it
                            sftp.remove(path)
                    except FileNotFoundError:
                        pass  # Already gone

                try:
                    attr = sftp.stat(remote_path)

                    if stat.S_ISDIR(attr.st_mode):
                        if recursive:
                            remove_recursive(remote_path)
                        else:
                            # Try to remove as empty directory
                            try:
                                sftp.rmdir(remote_path)
                            except OSError:
                                console.print(
                                    f"[red]Error: Directory '{remote_path}' is not empty. Use recursive=True to remove.[/red]"
                                )
                                return False
                    else:
                        # It's a file - remove it
                        sftp.remove(remote_path)

                    console.print(f"[green]Remote path removed: {remote_path}[/green]")
                    return True
                except FileNotFoundError:
                    console.print(
                        f"[yellow]Warning: Remote path '{remote_path}' not found[/yellow]"
                    )
                    return False
            finally:
                sftp.close()

    # Terminal command execution
    async def execute_command(self, command):
        """Execute a shell command on the sandbox."""
        if not self.instance:
            raise ValueError("No active instance")

        result = await self.instance.aexec(command)
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
