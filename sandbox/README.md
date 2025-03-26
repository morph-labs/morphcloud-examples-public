# Morph Sandbox: JupyterLab Environment on Morph Cloud

This project introduces **Morph Sandbox**, a Python class (`morph_sandbox.py`) designed to simplify the management of JupyterLab environments on [Morph Cloud](https://cloud.morph.so/web/). Morph Sandbox provides a flexible infrastructure for data analysis, computational tasks, and interactive dashboard development with tools like JupyterLab and Streamlit.

The project also includes a **stock analysis demo script** (`stock_demo.py`) as an example of how to use Morph Sandbox to create data analysis environments and run parallel agent-based workflows for financial data analysis.

**Quickstart**
```python
import asyncio
from morph_sandbox import MorphSandbox

async def main():
    
   # Use context manager for automatic cleanup
   async with await MorphSandbox.create() as sandbox:

      # Execute Python code directly
      result = await sandbox.execute_code("x = 42")

      result = await sandbox.execute_code("print(f'the answer is {x}')
      print(result['output'])
      pass

asyncio.run(main())
```

## Scripts Overview

* **`morph_sandbox.py`**: This script defines the core `MorphSandbox` class. It handles the creation, startup, and management of JupyterLab instances on Morph Cloud. The class provides methods for notebook creation, code execution, file operations, and snapshot management. Morph Sandbox is designed to be a reusable component for any project needing a remote, cloud-based JupyterLab environment.

* **`stock_demo.py`**: This script demonstrates how to use `MorphSandbox` to create a complete environment for stock analysis. It sets up a JupyterLab environment with Tesla stock data, configures a Streamlit dashboard, and runs parallel analysis agents that work independently to explore different aspects of the stock data. It showcases both the infrastructure capabilities of Morph Sandbox and how it can be integrated with agent-based workflows.

## Key Features of Morph Sandbox (`morph_sandbox.py`)

* **JupyterLab Environment Management:** Simplifies the lifecycle of JupyterLab instances on Morph Cloud, handling creation, startup, and shutdown.
* **Jupyter Notebook Operations:** Provides methods for creating, modifying, and executing notebooks and individual cells.
* **Direct Code Execution:** Supports executing Python code directly in the kernel without creating notebook cells.
* **Data Visualization:** Captures and returns plot outputs from matplotlib and other visualization libraries.
* **File Operations:** Offers comprehensive file management with upload, download, and manipulation capabilities.
* **Service Management:** Manages additional services like Streamlit for dashboard creation.
* **Snapshotting:** Allows you to create snapshots of environments, enabling you to save and restore configured sandbox states.

## Prerequisites

Before you begin, ensure you have the following:

1. **Morph Cloud Account and API Key:** You need an account on [Morph Cloud](https://cloud.morph.so/web/) and an active API key.
2. **Python 3.11 or higher:** The scripts require Python 3.11 or a later version.
3. **uv installed**: Ensure you have [uv](https://astral.sh/uv) installed, which is a fast Python package installer and runner. Follow the installation instructions on the uv website.

## Setup Instructions

Follow these steps to set up the project and prepare it for running the stock demo:

1. **Environment Variables:** Before running the scripts, you **must** export your API key as an environment variable in your terminal.

   ```bash
   export MORPH_API_KEY="YOUR_MORPH_CLOUD_API_KEY"
   ```
   **Replace `"YOUR_MORPH_CLOUD_API_KEY"` with your actual API key.**

2. **Run the stock demo using `uv`:** The demo script is configured to create a complete environment for stock analysis. Run the script using `uv run`:

   ```bash
   uv run stock_demo.py
   ```
   **`uv run` will automatically install the required Python dependencies listed in the script's header.**

3. **Follow On-Screen Instructions:** The script will guide you through the setup process and provide URLs for accessing the JupyterLab environment and Streamlit dashboard.

## Stock Demo Features

The stock demo (`stock_demo.py`) showcases:

* **Automated Environment Setup:** Creates a fully configured JupyterLab environment with Tesla stock data.
* **Streamlit Dashboard Integration:** Sets up a Streamlit app for interactive data visualization.
* **Parallel Agent Analysis:** Runs two independent AI agents simultaneously, each exploring different aspects of the stock data:
  * An intraday analysis agent that explores short-term patterns
  * A long-term analysis agent that examines multi-year trends and investment strategies
* **Snapshot Management:** Creates snapshots at key points, allowing you to restore the environment at different stages.

## Using Morph Sandbox in Your Own Projects

`morph_sandbox.py` is designed to be a generic, reusable component. To use Morph Sandbox in your own Python projects:

1. **Include `morph_sandbox.py`:** Place `morph_sandbox.py` in your project directory.
2. **Import `MorphSandbox` Class:** In your Python script, import the `MorphSandbox` class:

   ```python
   from morph_sandbox import MorphSandbox
   ```

3. **Create and Manage Sandbox Instances:** Use `MorphSandbox.create()` to create a new sandbox instance (from scratch or a snapshot). Manage the sandbox lifecycle using `async with` context manager or by calling `await sandbox_instance.stop()` when done. **Remember to export your `MORPH_API_KEY` environment variable before running your scripts.**

Morph Sandbox aims to provide a flexible and reusable foundation for computational environments on Morph Cloud. The `stock_demo.py` is just one example of its potential applications. Adapt and extend Morph Sandbox for your specific computational needs, from data analysis to machine learning workflows.


## Quick Examples

**1. Create and manage a sandbox**
```python
import asyncio
from morph_sandbox import MorphSandbox

async def main():
    # Create a new sandbox instance
    sandbox = await MorphSandbox.create()
    
    # Use context manager for automatic cleanup
    async with await MorphSandbox.create() as sandbox:
        # Your code here
        pass

asyncio.run(main())
```

**2. Execute code directly**
```python
async def run_code_example():
    async with await MorphSandbox.create() as sandbox:
        # Execute Python code directly
        result = await sandbox.execute_code("x = 42")
        
        # Access the result
        result = await sandbox.execute_code("print(f'The value is {x}')")
        print(result["output"])  # outputs: The value is 42

asyncio.run(run_code_example())
```

**3. Work with notebooks**
```python
async def notebook_example():
    async with await MorphSandbox.create() as sandbox:
        # Create a new notebook
        notebook = await sandbox.create_notebook("analysis.ipynb")
        
        # Add cells to the notebook
        cell = await sandbox.add_cell(
            notebook_path="analysis.ipynb",
            content="import pandas as pd\nimport matplotlib.pyplot as plt",
            cell_type="code"
        )
        
        # Execute a specific cell
        await sandbox.execute_cell("analysis.ipynb", cell["index"])
        
        # Execute the entire notebook
        await sandbox.execute_notebook("analysis.ipynb")

asyncio.run(notebook_example())
```

**4. File operations**
```python
async def file_operations_example():
    async with await MorphSandbox.create() as sandbox:
        # Upload a single file to the sandbox
        await sandbox.upload_file(
            local_path="data.csv", 
            remote_path="/root/notebooks/data.csv"
        )
        
        # Upload a directory recursively
        await sandbox.upload_file(
            local_path="./project_data/", 
            remote_path="/root/notebooks/project_data",
            recursive=True
        )
        
        # List files in a directory
        files = await sandbox.list_remote_files("/root/notebooks")
        
        # Download a single file from the sandbox
        await sandbox.download_file(
            remote_path="/root/notebooks/results.csv",
            local_path="./results.csv"
        )
        
        # Download a directory recursively
        await sandbox.download_file(
            remote_path="/root/notebooks/output_data",
            local_path="./local_output",
            recursive=True
        )

asyncio.run(file_operations_example())
```

**5. Create and restore snapshots**
```python
async def snapshot_example():
    # Create a sandbox and take a snapshot
    sandbox = await MorphSandbox.create()
    snapshot_id = await sandbox.snapshot(digest="my-configured-environment")
    await sandbox.stop()
    
    # Later, restore from the snapshot
    restored_sandbox = await MorphSandbox.create(snapshot_id=snapshot_id)
    
    # Clean up when done
    await restored_sandbox.stop()

asyncio.run(snapshot_example())
```

**6. Create and display plots**
```python
import asyncio
from morph_sandbox import MorphSandbox

async def plot_example():
    # Use context manager for automatic cleanup
    async with await MorphSandbox.create() as sandbox:
        # Install matplotlib if needed
        await sandbox.execute_code("import sys; !{sys.executable} -m pip install matplotlib numpy")
        
        # Python code that creates a plot using matplotlib
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

# Show the plot - MorphSandbox automatically captures plot outputs
plt.show()
        """
        
        # Execute the code
        result = await sandbox.execute_code(plot_code)
        
        # Check if we have images in the result
        if "images" in result:
            images = result["images"]
            print(f"Successfully captured {len(images)} images!")
            
            # Save the first image if it's a PNG
            if len(images) > 0 and images[0]["mime_type"] == "image/png":
                import base64
                
                # Save image to file
                image_path = "plot_1.png"
                img_data = base64.b64decode(images[0]["data"])
                with open(image_path, "wb") as f:
                    f.write(img_data)
                print(f"Saved image to {image_path}")

# Run the example
asyncio.run(plot_example())
```

**7. Integrate with Anthropic's Claude API**
```python
# pip install anthropic morph_sandbox
import asyncio
from anthropic import Anthropic
from morph_sandbox import MorphSandbox

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
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
    )
    
    # Extract code from response
    code = response.content[0].text
    
    # Execute code in MorphSandbox
    async with await MorphSandbox.create() as sandbox:
        result = await sandbox.execute_code(code)
        output = result["output"]
    
    print(output)

# Run the example
asyncio.run(claude_code_execution())
```
