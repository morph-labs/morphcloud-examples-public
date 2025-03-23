# Morph Sandbox: JupyterLab Environment on Morph Cloud

This project introduces **Morph Sandbox**, a Python class (`morph_sandbox.py`) designed to simplify the management of JupyterLab environments on [Morph Cloud](https://morphcloud.ai/). Morph Sandbox provides a flexible infrastructure for data analysis, computational tasks, and interactive dashboard development with tools like JupyterLab and Streamlit.

The project also includes a **stock analysis demo script** (`stock_demo.py`) as an example of how to use Morph Sandbox to create data analysis environments and run parallel agent-based workflows for financial data analysis.

## Scripts Overview

* **`morph_sandbox.py`**: This script defines the core `MorphSandbox` class. It handles the creation, startup, and management of JupyterLab instances on Morph Cloud. The class provides methods for notebook creation, code execution, file operations, and snapshot management. Morph Sandbox is designed to be a reusable component for any project needing a remote, cloud-based JupyterLab environment.

* **`stock_demo.py`**: This script demonstrates how to use `MorphSandbox` to create a complete environment for stock analysis. It sets up a JupyterLab environment with Tesla stock data, configures a Streamlit dashboard, and runs parallel analysis agents that work independently to explore different aspects of the stock data. It showcases both the infrastructure capabilities of Morph Sandbox and how it can be integrated with agent-based workflows.

## Key Features of Morph Sandbox (`morph_sandbox.py`)

* **JupyterLab Environment Management:** Simplifies the lifecycle of JupyterLab instances on Morph Cloud, handling creation, startup, and shutdown.
* **Jupyter Notebook Operations:** Provides methods for creating, modifying, and executing notebooks and individual cells.
* **Direct Code Execution:** Supports executing Python code directly in the kernel without creating notebook cells.
* **File Operations:** Offers comprehensive file management with upload, download, and manipulation capabilities.
* **Service Management:** Manages additional services like Streamlit for dashboard creation.
* **Snapshotting:** Allows you to create snapshots of environments, enabling you to save and restore configured sandbox states.

## Prerequisites

Before you begin, ensure you have the following:

1. **Morph Cloud Account and API Key:** You need an account on [Morph Cloud](https://morphcloud.ai/) and an active API key.
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