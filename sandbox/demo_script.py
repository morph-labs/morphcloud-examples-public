#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "morphcloud",     # For instance management
#     "websockets",     # For Jupyter kernel communication
#     "jupyter_client", # For message protocol
#     "httpx",          # For HTTP requests
#     "pydantic",       # For type definitions
#     "rich",           # For nice terminal output
#     "anthropic",      # For Claude API (Example 6)
#     "pandas",         # For test data
#     "numpy"           # For test data
# ]
# ///

import asyncio
import os
import tempfile

from anthropic import Anthropic
# Import the MorphSandbox class
from morph_sandbox import MorphSandbox
from rich.console import Console
from rich.panel import Panel

# Create console for nice output
console = Console()

# Check for API key
if "MORPH_API_KEY" not in os.environ:
    console.print(
        "[bold red]ERROR: You must set the MORPH_API_KEY environment variable[/bold red]"
    )
    console.print('Example: export MORPH_API_KEY="your_api_key_here"')
    exit(1)


async def test_quickstart():
    """Test the quickstart example from the README"""
    console.print(
        Panel(
            "Testing Quickstart Example",
            title="Example: Quickstart",
            border_style="blue",
        )
    )

    async def main():
        # Use context manager for automatic cleanup
        async with await MorphSandbox.create() as sandbox:
            # Execute Python code directly
            result = await sandbox.execute_code("x = 42")

            result = await sandbox.execute_code("print(f'The answer is {x}')")
            print(result["output"])

    await main()
    console.print("[green]✅ Quickstart test completed[/green]\n")


async def test_sandbox_creation():
    """Test creating and managing a sandbox"""
    console.print(
        Panel("Testing Example: Create and manage a sandbox", border_style="blue")
    )

    import asyncio

    from morph_sandbox import MorphSandbox

    async def main():
        # Use context manager for automatic cleanup
        async with await MorphSandbox.create() as sandbox:
            # Your code here
            result = await sandbox.execute_code("print('Example 1 works!')")
            print(result["output"])

    await main()
    console.print("[green]✅ Sandbox creation test completed[/green]\n")


async def test_code_execution():
    """Test code execution functionality"""
    console.print(Panel("Testing Example: Execute code directly", border_style="blue"))

    async def run_code_example():
        async with await MorphSandbox.create() as sandbox:
            # Execute Python code directly
            result = await sandbox.execute_code("x = 42")

            # Access the result
            result = await sandbox.execute_code("print(f'The value is {x}')")
            print(result["output"])  # outputs: The value is 42

    await run_code_example()
    console.print("[green]✅ Code execution test completed[/green]\n")


async def test_notebook_operations():
    """Test notebook operations"""
    console.print(Panel("Testing Example: Work with notebooks", border_style="blue"))

    async def notebook_example():
        async with await MorphSandbox.create() as sandbox:
            # Create a new notebook
            notebook = await sandbox.create_notebook("analysis.ipynb")

            # Add cells to the notebook
            cell = await sandbox.add_cell(
                notebook_path="analysis.ipynb",
                content="import pandas as pd\nimport matplotlib.pyplot as plt",
                cell_type="code",
            )

            # Execute a specific cell
            await sandbox.execute_cell("analysis.ipynb", cell["index"])

            # Execute the entire notebook
            await sandbox.execute_notebook("analysis.ipynb")

    await notebook_example()
    console.print("[green]✅ Notebook operations test completed[/green]\n")


async def test_file_operations():
    """Test file operations"""
    console.print(Panel("Testing Example: File operations", border_style="blue"))

    # Create temp directory for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create files for testing
        with open(f"{temp_dir}/data.csv", "w") as f:
            f.write("id,value\n1,100\n2,200\n3,300")

        # Create project_data directory
        os.makedirs(f"{temp_dir}/project_data")
        with open(f"{temp_dir}/project_data/file1.txt", "w") as f:
            f.write("Example file 1")
        with open(f"{temp_dir}/project_data/file2.txt", "w") as f:
            f.write("Example file 2")

        async def file_operations_example():
            async with await MorphSandbox.create() as sandbox:
                # Upload a single file to the sandbox
                await sandbox.upload_file(
                    local_path=f"{temp_dir}/data.csv",
                    remote_path="/root/notebooks/data.csv",
                )

                # Upload a directory recursively
                await sandbox.upload_file(
                    local_path=f"{temp_dir}/project_data/",
                    remote_path="/root/notebooks/project_data",
                    recursive=True,
                )

                # List files in a directory
                files = await sandbox.list_remote_files("/root/notebooks")
                print(f"Files in directory: {len(files)} files found")

                # Create a results file to download
                code = "with open('/root/notebooks/results.csv', 'w') as f: f.write('result1,10\\nresult2,20')"
                await sandbox.execute_code(code)

                # Create output directory with files
                code = """
import os
os.makedirs('/root/notebooks/output_data', exist_ok=True)
with open('/root/notebooks/output_data/file1.txt', 'w') as f: f.write('Output 1')
with open('/root/notebooks/output_data/file2.txt', 'w') as f: f.write('Output 2')
"""
                await sandbox.execute_code(code)

                # Download a single file from the sandbox
                await sandbox.download_file(
                    remote_path="/root/notebooks/results.csv",
                    local_path=f"{temp_dir}/results.csv",
                )
                print(
                    f"Downloaded file exists: {os.path.exists(f'{temp_dir}/results.csv')}"
                )

                # Download a directory recursively
                await sandbox.download_file(
                    remote_path="/root/notebooks/output_data",
                    local_path=f"{temp_dir}/local_output",
                    recursive=True,
                )
                print(
                    f"Downloaded directory exists: {os.path.exists(f'{temp_dir}/local_output')}"
                )
                if os.path.exists(f"{temp_dir}/local_output"):
                    print(
                        f"Files in downloaded directory: {os.listdir(f'{temp_dir}/local_output')}"
                    )

        await file_operations_example()
    console.print("[green]✅ File operations test completed[/green]\n")


async def test_snapshots():
    """Test snapshot creation and restoration"""
    console.print(
        Panel("Testing Example: Create and restore snapshots", border_style="blue")
    )

    async def snapshot_example():
        # Create a sandbox and take a snapshot
        sandbox = await MorphSandbox.create()
        snapshot_id = await sandbox.snapshot(digest="my-configured-environment")
        await sandbox.stop()

        # Later, restore from the snapshot
        restored_sandbox = await MorphSandbox.create(snapshot_id=snapshot_id)

        # Clean up when done
        await restored_sandbox.stop()

    await snapshot_example()
    console.print("[green]✅ Snapshots test completed[/green]\n")


async def test_claude_integration():
    """Test integration with Anthropic's Claude API"""
    console.print(
        Panel(
            "Testing Example: Integrate with Anthropic's Claude API",
            border_style="blue",
        )
    )

    # Check if ANTHROPIC_API_KEY is set
    if "ANTHROPIC_API_KEY" not in os.environ:
        console.print(
            "[yellow]⚠️ ANTHROPIC_API_KEY not set, skipping Claude integration test[/yellow]"
        )
        console.print(
            "To run this test, set the ANTHROPIC_API_KEY environment variable"
        )
        console.print("[yellow]Claude integration test skipped[/yellow]\n")
        return

    async def claude_code_execution():
        # Create Anthropic client
        anthropic = Anthropic()

        # Define system prompt and user question
        system_prompt = "You are a helpful assistant that can execute python code in a Jupyter notebook. Only respond with the code to be executed and nothing else. Strip backticks in code blocks."
        prompt = "Calculate how many r's are in the word 'strawberry'"

        # Send messages to Anthropic API
        response = anthropic.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )

        # Extract code from response
        code = response.content[0].text
        print("Code from Claude:")
        print(code)

        # Execute code in MorphSandbox
        async with await MorphSandbox.create() as sandbox:
            result = await sandbox.execute_code(code)
            output = result["output"]

        print(f"Result: {output}")

    await claude_code_execution()
    console.print("[green]✅ Claude integration test completed[/green]\n")


async def test_simple_plot():
    """Test simple matplotlib plotting functionality"""
    console.print(
        Panel("Testing Example: Create and display plots", border_style="blue")
    )

    async def plot_example():
        # Use context manager for automatic cleanup
        async with await MorphSandbox.create() as sandbox:
            # Install matplotlib if needed
            await sandbox.execute_code(
                "import sys; !{sys.executable} -m pip install matplotlib numpy"
            )

            # Python code that creates a plot and uses native plt.show()
            plot_code = """
import matplotlib.pyplot as plt
import numpy as np

# Generate data
x = np.linspace(0, 10, 100)
y = np.sin(x)

# Create plot
plt.figure(figsize=(10, 6))
plt.plot(x, y, 'b-', linewidth=2)
plt.title('Sine Wave')
plt.xlabel('x')
plt.ylabel('sin(x)')
plt.grid(True)

# Show the plot using the Jupyter/IPython display system
plt.show()
            """

            # Execute the code
            result = await sandbox.execute_code(plot_code)

            # Check if we have images in the result
            if "images" in result:
                images = result["images"]
                console.print(
                    f"[green]✅ Successfully captured {len(images)} images![/green]"
                )

                # Save the first image if it's a PNG
                if len(images) > 0 and images[0]["mime_type"] == "image/png":
                    try:
                        import base64

                        # Save image to file
                        image_path = "plot_1.png"
                        img_data = base64.b64decode(images[0]["data"])
                        with open(image_path, "wb") as f:
                            f.write(img_data)
                        console.print(f"[green]Saved image to {image_path}[/green]")

                    except Exception as e:
                        console.print(f"[red]Error saving image: {e}[/red]")
            else:
                console.print("[yellow]No images captured in the result[/yellow]")

    await plot_example()
    console.print("[green]✅ Plot generation test completed[/green]\n")


async def run_all_tests():
    """Run all the example tests"""
    console.print(
        Panel(
            "Morph Sandbox Demo Script - Testing all Quick Examples",
            border_style="green",
        )
    )

    # Run all tests
    await test_quickstart()
    await test_sandbox_creation()
    await test_code_execution()
    await test_notebook_operations()
    await test_file_operations()
    await test_snapshots()
    await test_claude_integration()
    await test_simple_plot()

    console.print(Panel("All examples tested successfully!", border_style="green"))


if __name__ == "__main__":
    asyncio.run(run_all_tests())
