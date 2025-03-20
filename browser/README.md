# Morph Browser: Branching CDP-Enabled Browser on Morph Cloud

This project introduces **Morph Browser**, a Python class (`morph_browser.py`) designed to simplify the management of branching Chrome browser instances on [Morph Cloud](https://morphcloud.ai/). Morph Browser provides a generic, CDP (Chrome DevTools Protocol) enabled browser infrastructure that can be used with various browser automation libraries, including `browser-use`, Playwright, and Selenium.

The project also includes a **shopping demo script** (`shopping_demo.py`) as an example of how to use Morph Browser to automate and scale browser workflows with [browser-use](https://github.com/browser-use/browser-use), specifically demonstrating automated parallel book shopping on Amazon.

## Scripts Overview

*   **`morph_browser.py`**: This script defines the core `MorphBrowser` class. It handles the creation, startup, service verification, snapshotting, and stopping of browser VMs on Morph Cloud. Importantly, it exposes a standard CDP URL (`cdp_url` property) that can be used by any CDP-compatible browser automation tool. Morph Browser is designed to be a reusable component for any project needing a remote, cloud-based Chrome instance. The first setup of the browser on the Morph VM gets cached - so you only do the long setup once!
*   **`shopping_demo.py`**: This script is an example application that uses `MorphBrowser` and the `browser-use` library to automate the process of finding and adding books to an Amazon shopping cart. It reads book titles from `books.csv`, uses `MorphBrowser` to manage browser instances on Morph Cloud, and leverages `browser-use` and `langchain-anthropic` to automate Amazon interactions. It showcases how to build a specific automation task on top of the generic Morph Browser infrastructure.

## Key Features of Morph Browser (`morph_browser.py`)

*   **Generic CDP Interface:** Provides a standard `cdp_url` property, making it compatible with any browser automation library that can connect to a Chrome DevTools Protocol endpoint.
*   **Morph Cloud Instance Management:** Simplifies the lifecycle of browser VMs on Morph Cloud, handling creation, startup, and shutdown.
*   **Service Verification:** Robustly verifies that essential browser services (Chrome, VNC, noVNC, nginx) are running correctly within the Morph Cloud instance.
*   **Snapshotting:** Allows you to create snapshots of browser states, enabling you to save and restore configured browser environments (e.g., logged-in sessions, browser settings).
*   **User Setup Support:** Provides a mechanism to easily create a browser instance with VNC access for interactive user setup (e.g., logging into websites, configuring browser extensions) before creating a snapshot for automated tasks.

## Prerequisites

Before you begin, ensure you have the following:

1.  **Morph Cloud Account and API Key:** You need an account on [Morph Cloud](https://morphcloud.ai/) and an active API key.
2.  **Anthropic API Key:** You will need an API key from Anthropic to use the language model in the shopping demo.
3.  **Python 3.11 or higher:** The scripts require Python 3.11 or a later version.
4.  **uv installed**: Ensure you have [uv](https://astral.sh/uv) installed, which is a fast Python package installer and runner. Follow the installation instructions on the uv website.

## Setup Instructions

Follow these steps to set up the project and prepare it for running the shopping demo:

1.  **Environment Variables:** Before running the scripts, you **must** export your API keys as environment variables in your terminal.

    ```bash
    export MORPH_API_KEY="YOUR_MORPH_CLOUD_API_KEY"
    export ANTHROPIC_API_KEY="YOUR_ANTHROPIC_API_KEY"
    ```
    **Replace `"YOUR_MORPH_CLOUD_API_KEY"` and `"YOUR_ANTHROPIC_API_KEY"` with your actual API keys.**

2.  **Create `books.csv`:** Create a CSV file named `books.csv` in the same directory as the scripts. An example is given.

3.  **Initial Amazon Login Setup (Snapshot Creation):**
    Before running the shopping demo, you need to create a snapshot of a Morph Cloud browser instance logged into Amazon. To do this:

    *   **Run `shopping_demo.py` in setup mode using `uv`:** By default, `shopping_demo.py` is configured for user setup (`perform_user_setup = True`). Run the script using `uv run`:

        ```bash
        uv run shopping_demo.py
        ```
        **`uv run` will automatically install the required Python dependencies listed in the script's header.**

    *   **Follow On-Screen Instructions:** The script will guide you to log in to Amazon via a VNC connection to a Morph Browser instance.
    *   **Log in to Amazon:** In the VNC browser, navigate to Amazon.com and log in to your account.
    *   **Wait for Amazon Homepage:** Ensure you are logged in and the Amazon homepage is loaded.
    *   **Press Enter in Terminal:** Return to your terminal and press Enter.
    *   **Snapshot Creation:** The script will create a snapshot named `"amazon-logged-in"`. Note the snapshot ID if needed.

## Running the Shopping Demo (`shopping_demo.py`)

After setup, run `shopping_demo.py` to process books from `books.csv` using `uv run`:

```bash
uv run shopping_demo.py
```

Monitor the console output and check `amazon_books_results.json` and `amazon_books_results.csv` for results.

## Using Morph Browser in Your Own Projects

`morph_browser.py` is designed to be a generic, reusable component. To use Morph Browser in your own Python projects that require a CDP-enabled browser on Morph Cloud:

1.  **Include `morph_browser.py`:** Place `morph_browser.py` in your project directory.
2.  **Import `MorphBrowser` Class:** In your Python script, import the `MorphBrowser` class:

    ```python
    from morph_browser import MorphBrowser
    ```

3.  **Create and Manage Morph Browser Instances:** Use `MorphBrowser.create()` to create a new browser instance (from scratch or a snapshot). Access the CDP URL using `browser_instance.cdp_url`. Manage the browser lifecycle using `async with` context manager or by calling `await browser_instance.stop()` when done. **Remember to export your `MORPH_API_KEY` environment variable before running your scripts.**

Morph Browser aims to provide a flexible and reusable foundation for browser automation on Morph Cloud. The `shopping_demo.py` is just one example of its potential applications. Adapt and extend Morph Browser and the demo script to suit your specific automation needs.
