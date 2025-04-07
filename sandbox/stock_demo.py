#!/usr/bin/env python3
# Script to set up MorphSandbox with Tesla stock data and run parallel agents

import asyncio
import json
import os
import sys
import tempfile
import webbrowser
from typing import Any, Dict, List, Optional

from agents import Agent, RunContextWrapper, Runner, function_tool
from morph_sandbox import MorphSandbox

#######################
# Setup Functions
#######################


def open_url_in_browser(url, delay=0):
    """Open a URL in the browser with an optional delay.

    Args:
        url: URL to open
        delay: Delay in seconds before opening
    """
    if delay:
        import time

        time.sleep(delay)
    print(f"Opening in browser: {url}")
    webbrowser.open(url)


async def setup_initial_sandbox(snapshot_id=None):
    """Set up the initial sandbox with Tesla stock data and a simple Streamlit app.

    Args:
        snapshot_id: Optional ID of a snapshot to restore from

    Returns:
        Dict with sandbox info and snapshot ID
    """
    # Create a new sandbox or restore from snapshot
    if snapshot_id:
        print(f"Creating MorphSandbox from snapshot {snapshot_id}...")
        sandbox = await MorphSandbox.create(snapshot_id=snapshot_id)
        is_from_snapshot = True
    else:
        print("Creating new MorphSandbox...")
        sandbox = await MorphSandbox.create()
        is_from_snapshot = False

    try:
        print(f"Sandbox created! JupyterLab URL: {sandbox.jupyter_url}")
        open_url_in_browser(sandbox.jupyter_url)

        # Make sure the sandbox is ready
        print("Waiting for sandbox to be fully ready...")
        await sandbox.instance.await_until_ready()

        # Install only packages that might not be in the base sandbox
        if not is_from_snapshot:
            print("\nInstalling additional packages...")
            await sandbox.execute_command(
                "source /root/venv/bin/activate && "
                "pip install streamlit yfinance plotly seaborn"
            )
        else:
            print("\nSkipping package installation (using snapshot)")

        # Check if the dataset exists already (for snapshots)
        check_dataset = await sandbox.execute_command(
            "ls -la /root/notebooks/data/tesla_stock.csv 2>/dev/null || echo 'not_found'"
        )
        has_dataset = "not_found" not in check_dataset["stdout"]

        # Create data directory if it doesn't exist
        await sandbox.execute_command("mkdir -p /root/notebooks/data")

        # Download and process dataset (only if needed)
        if not is_from_snapshot and not has_dataset:
            print("\nCreating notebook...")
            notebook = await sandbox.create_notebook("tesla_stock.ipynb")

            # Add cell to download the dataset
            print("Adding cell to download Tesla stock data...")
            download_cell = """
# Download Tesla stock data using yfinance
import yfinance as yf
import pandas as pd
import os

# Create data directory
os.makedirs('/root/notebooks/data', exist_ok=True)

# Download Tesla data
# 5 years of daily data
tesla_daily = yf.download('TSLA', period='5y')
tesla_daily.to_csv('/root/notebooks/data/tesla_daily.csv')
print(f"Downloaded {len(tesla_daily)} days of Tesla daily data")

# 60 days of hourly data
tesla_hourly = yf.download('TSLA', period='60d', interval='1h')
tesla_hourly.to_csv('/root/notebooks/data/tesla_hourly.csv')
print(f"Downloaded {len(tesla_hourly)} hours of Tesla hourly data")

# 7 days of 5-minute data
tesla_5min = yf.download('TSLA', period='7d', interval='5m')
tesla_5min.to_csv('/root/notebooks/data/tesla_5min.csv')
print(f"Downloaded {len(tesla_5min)} 5-minute intervals of Tesla data")

# Save a combined dataset for easy access
tesla_data = {
    'daily': tesla_daily,
    'hourly': tesla_hourly,
    '5min': tesla_5min
}

import pickle
with open('/root/notebooks/data/tesla_stock.pkl', 'wb') as f:
    pickle.dump(tesla_data, f)
print("Saved combined dataset to tesla_stock.pkl")
"""
            download_cell_result = await sandbox.add_cell(
                "tesla_stock.ipynb", download_cell
            )

            # Add cell to load and explore the dataset
            print("Adding cell to load and explore dataset...")
            explore_cell = """
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# Load the datasets
tesla_daily = pd.read_csv('/root/notebooks/data/tesla_daily.csv', index_col=0, parse_dates=True)
tesla_hourly = pd.read_csv('/root/notebooks/data/tesla_hourly.csv', index_col=0, parse_dates=True)
tesla_5min = pd.read_csv('/root/notebooks/data/tesla_5min.csv', index_col=0, parse_dates=True)

# Basic exploration of daily data
print("Daily data shape:", tesla_daily.shape)
print("Daily data first 5 rows:")
tesla_daily.head()

# Plot daily close prices
plt.figure(figsize=(12, 6))
tesla_daily['Close'].plot()
plt.title('Tesla Daily Close Price (5 Years)')
plt.tight_layout()
plt.show()

# Plot hourly close prices for the last week
plt.figure(figsize=(12, 6))
tesla_hourly['Close'][-168:].plot()  # last week (7 days x 24 hours)
plt.title('Tesla Hourly Close Price (Last Week)')
plt.tight_layout()
plt.show()

print("Data exploration complete!")
"""
            explore_cell_result = await sandbox.add_cell(
                "tesla_stock.ipynb", explore_cell
            )

            # Execute notebook cells
            print("\nDownloading and exploring Tesla stock data...")
            try:
                # Execute dataset download cell
                await sandbox.execute_cell(
                    "tesla_stock.ipynb", download_cell_result["index"]
                )
                print("Tesla stock data downloaded successfully!")

                # Execute exploration cell
                await sandbox.execute_cell(
                    "tesla_stock.ipynb", explore_cell_result["index"]
                )
                print("Data exploration completed!")
            except Exception as e:
                print(f"Error executing notebook cells: {str(e)}")

        # Create simplified Streamlit app
        print("\nCreating simplified Streamlit app...")
        streamlit_app = """import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Page config
st.set_page_config(
    page_title="Tesla Stock Analysis",
    page_icon="📈"
)

# Title
st.title("Tesla Hourly Stock Data")

# Load hourly data directly
hourly_data = pd.read_csv('/root/notebooks/data/tesla_hourly.csv', index_col=0, parse_dates=True)

# Convert columns to numeric
for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
    hourly_data[col] = pd.to_numeric(hourly_data[col], errors='coerce')

# Drop any rows with missing Close prices
hourly_data = hourly_data.dropna(subset=['Close'])

# Sort by date
hourly_data = hourly_data.sort_index()

# Display basic info
st.write(f"Loaded {len(hourly_data)} hours of Tesla data")

# Create OHLCV chart with volume subplot
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                   vertical_spacing=0.1, row_heights=[0.7, 0.3])

# Add candlestick trace
fig.add_trace(go.Candlestick(
    x=hourly_data.index,
    open=hourly_data['Open'],
    high=hourly_data['High'],
    low=hourly_data['Low'],
    close=hourly_data['Close'],
    name='Price'
), row=1, col=1)

# Add volume bar chart
fig.add_trace(go.Bar(
    x=hourly_data.index,
    y=hourly_data['Volume'],
    name='Volume',
    marker_color='rgba(0, 0, 255, 0.5)'
), row=2, col=1)

# Update layout
fig.update_layout(
    xaxis_title='Date',
    yaxis_title='Price (USD)',
    xaxis_rangeslider_visible=False,
    height=600,
    showlegend=False
)

# Set x-axis to category type to remove gaps
fig.update_xaxes(type='category')

# Show the figure
st.plotly_chart(fig, use_container_width=True)

# Show basic stats
latest_close = hourly_data['Close'].iloc[-1]
period_high = hourly_data['High'].max()
period_low = hourly_data['Low'].min()

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Latest Close", f"${latest_close:.2f}")
with col2:
    st.metric("Period High", f"${period_high:.2f}")
with col3:
    st.metric("Period Low", f"${period_low:.2f}")

# Show raw data if requested
if st.checkbox("Show Raw Data"):
    st.dataframe(hourly_data)"""

        # Create Streamlit directory
        await sandbox.execute_command("mkdir -p /root/notebooks/streamlit")

        # Use a temporary file approach to avoid escaping issues
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as temp_file:
            temp_file.write(streamlit_app)
            temp_file_path = temp_file.name

        # Upload the file to the sandbox
        await sandbox.upload_file(temp_file_path, "/root/notebooks/streamlit/app.py")
        os.remove(temp_file_path)

        # Create script to run Streamlit app
        run_script = """#!/bin/bash
source /root/venv/bin/activate
cd /root/notebooks/streamlit
streamlit run app.py --server.port=8501 --server.address=0.0.0.0
"""
        # Create and upload run script
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as temp_script:
            temp_script.write(run_script)
            temp_script_path = temp_script.name

        await sandbox.upload_file(
            temp_script_path, "/root/notebooks/streamlit/run_app.sh"
        )
        os.remove(temp_script_path)

        await sandbox.execute_command("chmod +x /root/notebooks/streamlit/run_app.sh")

        # Install tmux if not available
        tmux_check = await sandbox.execute_command("which tmux || echo 'not_found'")
        if "not_found" in tmux_check["stdout"]:
            print("\nInstalling tmux...")
            await sandbox.execute_command("apt-get update && apt-get install -y tmux")

        # Start Streamlit in tmux
        print("\nStarting Streamlit app in tmux...")
        tmux_script = """
# Kill any existing tmux sessions
tmux kill-session -t streamlit 2>/dev/null || true

# Create new tmux session
tmux new-session -d -s streamlit

# Send command to the session
tmux send-keys -t streamlit 'cd /root/notebooks/streamlit && source /root/venv/bin/activate && ./run_app.sh' C-m
"""
        # Create and upload tmux script
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as temp_tmux:
            temp_tmux.write(tmux_script)
            temp_tmux_path = temp_tmux.name

        await sandbox.upload_file(temp_tmux_path, "/root/start_tmux.sh")
        os.remove(temp_tmux_path)

        await sandbox.execute_command(
            "chmod +x /root/start_tmux.sh && /root/start_tmux.sh"
        )

        # Verify Streamlit is running
        print("\nVerifying Streamlit is running...")
        streamlit_check = await sandbox.execute_command(
            "ps aux | grep streamlit | grep -v grep"
        )
        if streamlit_check["stdout"].strip():
            print("✅ Streamlit is running")
        else:
            print("❌ Streamlit not detected, attempting to start again...")
            await sandbox.execute_command("/root/start_tmux.sh")
            await asyncio.sleep(2)  # Give it a moment to start

        # Expose the Streamlit app
        print("\nExposing Streamlit app via HTTP...")
        streamlit_url = await sandbox.instance.aexpose_http_service("streamlit", 8501)
        print(f"Streamlit app URL: {streamlit_url}")

        # Now create the snapshot AFTER everything is set up and running
        if not is_from_snapshot:
            print("\nCreating snapshot of the environment...")
            snapshot_id = await sandbox.snapshot(digest="tesla-stock-env")
            print(f"Snapshot created with ID: {snapshot_id}")
        else:
            print("\nUsing existing environment from snapshot")
            snapshot_id = snapshot_id or sandbox.instance.id

        print("\n====== Initial Setup Complete ======")
        print(f"JupyterLab URL: {sandbox.jupyter_url}")
        print(f"Streamlit app URL: {streamlit_url}")
        print(f"Snapshot ID: {snapshot_id}")

        # Automatically open URLs in browser
        open_url_in_browser(streamlit_url, delay=1)

        return {
            "sandbox": sandbox,
            "jupyter_url": sandbox.jupyter_url,
            "streamlit_url": streamlit_url,
            "snapshot_id": snapshot_id,
        }

    except Exception as e:
        print(f"Error during setup: {str(e)}")
        await sandbox.stop()
        raise


#######################
# Sandbox Tools for Agents
#######################


@function_tool
async def create_notebook(
    ctx: RunContextWrapper[MorphSandbox], name: str
) -> Dict[str, Any]:
    """Create a new notebook in the sandbox.

    Args:
        name: Name of the notebook to create
    """
    sandbox = ctx.context
    result = await sandbox.create_notebook(name)
    return result


@function_tool
async def add_code_cell(
    ctx: RunContextWrapper[MorphSandbox], notebook_path: str, cell_content: str
) -> Dict[str, Any]:
    """Add a code cell to a notebook.

    Args:
        notebook_path: Path to the notebook
        cell_content: Content of the cell
    """
    sandbox = ctx.context
    result = await sandbox.add_cell(notebook_path, cell_content, "code")
    return result


@function_tool
async def add_markdown_cell(
    ctx: RunContextWrapper[MorphSandbox], notebook_path: str, cell_content: str
) -> Dict[str, Any]:
    """Add a markdown cell to a notebook.

    Args:
        notebook_path: Path to the notebook
        cell_content: Content of the cell
    """
    sandbox = ctx.context
    result = await sandbox.add_cell(notebook_path, cell_content, "markdown")
    return result


@function_tool
async def execute_cell(
    ctx: RunContextWrapper[MorphSandbox], notebook_path: str, cell_index: int
) -> Dict[str, Any]:
    """Execute a specific cell in a notebook.

    Args:
        notebook_path: Path to the notebook
        cell_index: Index of the cell to execute
    """
    sandbox = ctx.context
    result = await sandbox.execute_cell(notebook_path, cell_index)
    return result


@function_tool
async def execute_code(
    ctx: RunContextWrapper[MorphSandbox], code: str
) -> Dict[str, Any]:
    """Execute Python code directly in the sandbox.

    Args:
        code: Python code to execute
    """
    sandbox = ctx.context
    result = await sandbox.execute_code(code)
    return result


@function_tool
async def execute_command(
    ctx: RunContextWrapper[MorphSandbox], command: str
) -> Dict[str, str]:
    """Execute a shell command in the sandbox.

    Args:
        command: Shell command to execute
    """
    sandbox = ctx.context
    result = await sandbox.execute_command(command)
    return result


@function_tool
async def update_streamlit_app(
    ctx: RunContextWrapper[MorphSandbox], content: str, file_path: str
) -> Dict[str, str]:
    """Create or update a Streamlit application file and test for errors.

    Args:
        content: The complete content to write to the Streamlit app file
        file_path: The file path to write to (e.g. "/root/notebooks/streamlit/app.py")
    """
    sandbox = ctx.context

    # If file_path is not provided, use a default path
    target_path = file_path or "/root/notebooks/streamlit/app.py"

    # Create a temporary test file path
    test_path = f"{os.path.dirname(target_path)}/test_app.py"

    # Create temporary file with the content
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as temp_file:
        temp_file.write(content)
        temp_file_path = temp_file.name

    # Ensure the streamlit directory exists
    if "/" in target_path:
        dir_path = os.path.dirname(target_path)
        await sandbox.execute_command(f"mkdir -p {dir_path}")

    # Upload to the test file first
    await sandbox.upload_file(temp_file_path, test_path)
    os.remove(temp_file_path)

    # Create simple error log file
    error_file = "/tmp/streamlit_errors.log"
    await sandbox.execute_command(f"rm -f {error_file}")

    # Kill any existing test session
    await sandbox.execute_command(
        "tmux kill-session -t streamlit_test 2>/dev/null || true"
    )

    # Create a new tmux session and run Streamlit test on port 8502
    test_command = f"cd $(dirname {test_path}) && source /root/venv/bin/activate && streamlit run {test_path} --server.port=8502 --server.headless=true 2> {error_file}"
    await sandbox.execute_command(
        f"tmux new-session -d -s streamlit_test '{test_command}'"
    )

    # Wait briefly for any immediate errors
    await asyncio.sleep(3)

    # Kill the test session
    await sandbox.execute_command(
        "tmux kill-session -t streamlit_test 2>/dev/null || true"
    )

    # Check for errors
    error_output = await sandbox.execute_command(f"cat {error_file}")
    errors = error_output["stdout"]

    if errors.strip():
        # Clean up test file
        await sandbox.execute_command(f"rm -f {test_path}")

        return {
            "status": "error",
            "message": "Errors detected in Streamlit app - main app not updated",
            "error_details": errors,
        }
    else:
        # No errors, update the main app file
        await sandbox.execute_command(f"cp {test_path} {target_path}")

        # Clean up test file
        await sandbox.execute_command(f"rm -f {test_path}")

        # Restart the main Streamlit process
        await sandbox.execute_command("/root/start_tmux.sh")

        return {
            "status": "success",
            "message": f"Successfully updated Streamlit app at {target_path}",
        }


@function_tool
async def create_snapshot(ctx: RunContextWrapper[MorphSandbox], digest: str) -> str:
    """Create a snapshot of the current sandbox state.

    Args:
        digest: Name for the snapshot
    """
    sandbox = ctx.context
    snapshot_id = await sandbox.snapshot(digest)
    return snapshot_id


#######################
# Agent Definitions
#######################
# Intraday Analysis Agent - Exploratory approach
INTRADAY_AGENT_INSTRUCTIONS = """
You are a quantitative analyst with a passion for discovering interesting patterns in stock data.
You have access to a MorphSandbox environment with Tesla stock data at different timeframes.

## GOAL: Explore intraday Tesla stock patterns and share discoveries through an interactive Streamlit app
You'll use JupyterLab for data analysis and testing, while creating visualizations directly in Streamlit.

IMPORTANT - FIRST STEP: Before attempting to create any Streamlit app, you MUST first:
1. Explore the existing JupyterLab environment to understand the available data and its structure
2. Open and examine the tesla_stock.ipynb notebook that already exists
3. Run cells in this notebook to see what data is available, its columns, and basic statistics
4. Look at the existing data files in the /root/notebooks/data/ directory
5. Understand the column names, data types, and time periods available in the stock datasets

As you explore, consider these areas of investigation:
- Intraday volatility patterns
- Trading volume relationships with price
- Technical indicators that reveal interesting signals
- Day-to-day behavior and anomalies

Technical approach:
1. Start by exploring the existing notebook and data files to understand what's available
2. Create your own notebook "intraday_exploration.ipynb" for detailed analysis
3. Use the notebook ONLY for data exploration, calculations, and testing - NOT for visualizations
4. Focus on the hourly and 5-minute data (from '/root/notebooks/data/tesla_hourly.csv' and '/root/notebooks/data/tesla_5min.csv')
5. Create all visualizations directly in the Streamlit app using Plotly
6. Make sure your code correctly references the actual column names from the datasets

Exploratory workflow:
1. First examine existing files and understand the data structure
2. Use the notebook to analyze data and test calculations
3. When you discover something intriguing through your analysis, implement it directly in Streamlit
4. Continue exploring new angles in your notebook based on what you've learned
5. Update the Streamlit app whenever you have a new insight worth sharing

Streamlit implementation:
1. Create ALL visualizations directly in Streamlit using Plotly - not in the notebook
2. Add interactive elements that let users explore the patterns you've found
3. Include explanations about what makes these patterns meaningful
4. Verify your app works after each update

Remember:
- FIRST understand the data by exploring the existing notebook and files
- Let your curiosity guide your exploration
- Use notebooks for data analysis and calculations, Streamlit for visualizations
- There's no fixed endpoint - continue exploring as long as you're finding interesting patterns
- Think about what would be most valuable for someone interested in Tesla stock behavior
"""

# Long-term Analysis Agent - Exploratory approach
LONG_TERM_AGENT_INSTRUCTIONS = """
You are a quantitative analyst with a passion for uncovering long-term market patterns.
You have access to a MorphSandbox environment with Tesla stock data at different timeframes.

## GOAL: Explore long-term Tesla stock behavior and share insights through an interactive Streamlit app
You'll use JupyterLab for numerical analysis and testing, while creating visualizations directly in Streamlit.

IMPORTANT - FIRST STEP: Before attempting to create any Streamlit app, you MUST first:
1. Explore the existing JupyterLab environment to understand the available data and its structure
2. Open and examine the tesla_stock.ipynb notebook that already exists
3. Run cells in this notebook to see what data is available, its columns, and basic statistics
4. Look at the existing data files in the /root/notebooks/data/ directory
5. Understand the column names, data types, and time periods available in the stock datasets

As you explore, consider these areas of investigation:
- Multi-year trends and cycles
- Volatility regimes over time
- Moving averages and their crossovers
- Support/resistance zones that have historical significance
- How different investment strategies would have performed

Technical approach:
1. Start by exploring the existing notebook and data files to understand what's available
2. Create your own notebook "long_term_exploration.ipynb" for detailed analysis
3. Use the notebook ONLY for data exploration, calculations, and testing - NOT for visualizations
4. Focus primarily on the daily data (from '/root/notebooks/data/tesla_daily.csv')
5. Create all visualizations directly in the Streamlit app using Plotly
6. Make sure your code correctly references the actual column names from the datasets

Exploratory workflow:
1. First examine existing files and understand the data structure
2. Use the notebook to run calculations, test strategies, and analyze data numerically
3. When your analysis reveals something interesting, implement the visualization directly in Streamlit
4. Continue your numerical analysis in the notebook to explore new questions
5. Update the Streamlit app when you have meaningful insights to share

Streamlit implementation:
1. Create ALL visualizations directly in Streamlit using Plotly - not in the notebook
2. Add interactive elements that let users engage with your findings
3. Include contextual explanations about the significance of what you've found
4. Verify your app works after each update

Remember:
- FIRST understand the data by exploring the existing notebook and files
- Follow your analytical curiosity rather than a predefined path
- Use notebooks for number-heavy analysis, Streamlit for all visualizations
- There's no fixed requirement for how many visualizations to create
- Consider what insights would be most valuable for long-term investors
"""

# Create the agents
intraday_agent = Agent(
    name="Intraday Analysis Agent",
    instructions=INTRADAY_AGENT_INSTRUCTIONS,
    tools=[
        create_notebook,
        add_code_cell,
        add_markdown_cell,
        execute_cell,
        execute_code,
        execute_command,
        update_streamlit_app,
        create_snapshot,
    ],
)

long_term_agent = Agent(
    name="Long-term Analysis Agent",
    instructions=LONG_TERM_AGENT_INSTRUCTIONS,
    tools=[
        create_notebook,
        add_code_cell,
        add_markdown_cell,
        execute_cell,
        execute_code,
        execute_command,
        update_streamlit_app,
        create_snapshot,
    ],
)

#######################
# Parallel Agent Runner
#######################


async def run_parallel_analysis(snapshot_id: str):
    """Run parallel stock analysis with two specialized agents.

    Args:
        snapshot_id: ID of the prepared environment snapshot
    """
    # Create two sandboxes from the same snapshot
    print("\nCreating sandboxes for parallel analysis...")

    # First sandbox for intraday analysis
    print("Creating sandbox for intraday analysis...")
    intraday_sandbox = await MorphSandbox.create(snapshot_id=snapshot_id)
    intraday_jupyter_url = intraday_sandbox.jupyter_url
    print(f"Intraday analysis sandbox ready at: {intraday_jupyter_url}")

    # Second sandbox for long-term analysis
    print("Creating sandbox for long-term analysis...")
    long_term_sandbox = await MorphSandbox.create(snapshot_id=snapshot_id)
    long_term_jupyter_url = long_term_sandbox.jupyter_url
    print(f"Long-term analysis sandbox ready at: {long_term_jupyter_url}")

    try:
        # Verify Streamlit is running in each sandbox
        print("\nVerifying Streamlit services...")

        # For intraday sandbox
        streamlit_check = await intraday_sandbox.execute_command(
            "ps aux | grep streamlit | grep -v grep"
        )
        if streamlit_check["stdout"].strip():
            print("✅ Streamlit is running in intraday analysis sandbox")
        else:
            print(
                "❌ Streamlit not detected in intraday analysis sandbox, attempting to start..."
            )
            await intraday_sandbox.execute_command("/root/start_tmux.sh")

        # For long-term sandbox
        streamlit_check = await long_term_sandbox.execute_command(
            "ps aux | grep streamlit | grep -v grep"
        )
        if streamlit_check["stdout"].strip():
            print("✅ Streamlit is running in long-term analysis sandbox")
        else:
            print(
                "❌ Streamlit not detected in long-term analysis sandbox, attempting to start..."
            )
            await long_term_sandbox.execute_command("/root/start_tmux.sh")

        # Get Streamlit URLs for both sandboxes
        print("\nGetting Streamlit URLs...")
        intraday_streamlit_url = await intraday_sandbox.instance.aexpose_http_service(
            "streamlit", 8501
        )
        long_term_streamlit_url = await long_term_sandbox.instance.aexpose_http_service(
            "streamlit", 8501
        )

        print(f"Intraday Analysis Streamlit URL: {intraday_streamlit_url}")
        print(f"Long-term Analysis Streamlit URL: {long_term_streamlit_url}")

        # Run both agents in parallel
        print("\nRunning both agents in parallel...")

        # Open URLs in browser before starting agent tasks
        print("\nOpening browser tabs for all services...")
        open_url_in_browser(intraday_jupyter_url)
        open_url_in_browser(intraday_streamlit_url, delay=1)
        open_url_in_browser(long_term_jupyter_url, delay=2)
        open_url_in_browser(long_term_streamlit_url, delay=3)

        # Create tasks for both agents to run concurrently
        intraday_task = Runner.run(
            intraday_agent,
            "Perform intraday analysis on Tesla stock data. Your task is complete ONLY when you've implemented all 5 stages with ALL requirements specified in the instructions. Make sure to verify each component works before moving on.",
            context=intraday_sandbox,
            max_turns=200,  # Increased max turns to give more time to complete all stages
        )

        long_term_task = Runner.run(
            long_term_agent,
            "Analyze long-term patterns and investment strategies for Tesla stock. Your task is complete ONLY when you've implemented all 5 stages with ALL requirements specified in the instructions. Make sure to verify each component works before moving on.",
            context=long_term_sandbox,
            max_turns=200,  # Increased max turns to give more time to complete all stages
        )

        # Wait for both agents to complete
        intraday_result, long_term_result = await asyncio.gather(
            intraday_task, long_term_task
        )

        print("Both agents have completed their analyses.")

        # Create snapshots of the final states AFTER agent work
        print("\nCreating snapshots of the analysis results...")
        intraday_snapshot_id = await intraday_sandbox.snapshot(
            digest="intraday-analysis-complete"
        )
        long_term_snapshot_id = await long_term_sandbox.snapshot(
            digest="long-term-analysis-complete"
        )
        print("\n====== Parallel Analysis Complete ======")
        print("\nIntraday Analysis:")
        print(f"JupyterLab URL: {intraday_jupyter_url}")
        print(f"Streamlit URL: {intraday_streamlit_url}")
        print(f"Snapshot ID: {intraday_snapshot_id}")
        print("\nLong-term Analysis:")
        print(f"JupyterLab URL: {long_term_jupyter_url}")
        print(f"Streamlit URL: {long_term_streamlit_url}")
        print(f"Snapshot ID: {long_term_snapshot_id}")

        # URLs already opened before agents started running
        print("\nAll browser tabs should already be open")

        # Ask if user wants to keep sandboxes running
        keep_running = (
            input("\nKeep analysis sandboxes running? (y/n, default: y): ").lower()
            != "n"
        )

        if not keep_running:
            print("Stopping analysis sandboxes...")
            await intraday_sandbox.stop()
            await long_term_sandbox.stop()
            print("Analysis sandboxes stopped.")
        else:
            print("Analysis sandboxes are still running.")

        return {
            "intraday_analysis": {
                "jupyter_url": intraday_jupyter_url,
                "streamlit_url": intraday_streamlit_url,
                "snapshot_id": intraday_snapshot_id,
                "result": intraday_result.final_output,
            },
            "long_term_analysis": {
                "jupyter_url": long_term_jupyter_url,
                "streamlit_url": long_term_streamlit_url,
                "snapshot_id": long_term_snapshot_id,
                "result": long_term_result.final_output,
            },
        }
    except Exception as e:
        print(f"Error during parallel analysis: {str(e)}")
        await intraday_sandbox.stop()
        await long_term_sandbox.stop()
        raise


#######################
# Main Function
#######################


async def main():
    """Main function to run the entire workflow."""
    # Parse command line arguments
    import argparse

    parser = argparse.ArgumentParser(
        description="Tesla Stock Analysis with MorphSandbox and Agents"
    )
    parser.add_argument(
        "--snapshot", help="Snapshot ID of prepared environment", default=None
    )
    parser.add_argument(
        "--setup-only",
        action="store_true",
        help="Only perform initial setup, no agent analysis",
    )
    parser.add_argument(
        "--analysis-only",
        action="store_true",
        help="Only perform agent analysis using existing snapshot",
    )
    args = parser.parse_args()

    try:
        # Determine workflow
        if args.analysis_only and args.snapshot:
            # Run only the analysis with existing snapshot
            print("Running only parallel agent analysis...")
            await run_parallel_analysis(args.snapshot)
        elif args.setup_only:
            # Run only the initial setup
            print("Running only initial environment setup...")
            result = await setup_initial_sandbox(args.snapshot)
            print(
                f"\nSetup complete! Use snapshot ID {result['snapshot_id']} for agent analysis."
            )
        else:
            # Run full workflow
            print("Running full workflow: initial setup + parallel agent analysis...")
            setup_result = await setup_initial_sandbox(args.snapshot)
            snapshot_id = setup_result["snapshot_id"]

            # Clean up the initial setup sandbox before agent analysis?
            keep_initial = (
                input("\nKeep initial sandbox running? (y/n, default: n): ").lower()
                == "y"
            )
            if not keep_initial:
                print("Stopping initial sandbox...")
                await setup_result["sandbox"].stop()
                print("Initial sandbox stopped.")

            # Run parallel analysis with agents
            await run_parallel_analysis(snapshot_id)
    except Exception as e:
        print(f"Error in main workflow: {str(e)}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
