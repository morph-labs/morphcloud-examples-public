# morphcloud-examples-public

A collection of example scripts to easily create and set up specialized VMs/snapshots on Morph Cloud.

## Overview

This repository contains ready-to-use scripts for creating preconfigured Morph Cloud instances for various use cases. Each script handles VM creation, setup, and service configuration automatically.

## Examples

### remote-desktop
- Sets up a VM with XFCE4 desktop environment accessible via web browser
- Uses TigerVNC + noVNC for browser-based remote desktop access
- No VNC client required - just open the provided URL

### openvscode-server
- Creates a VM running OpenVSCode Server in a Docker container
- Provides a full VS Code experience through your browser
- Includes a persistent workspace mounted at /home/workspace

### docker-buildkit
- Configures a VM with Docker BuildKit for containerized development
- Enables accelerated container builds with caching
- Optimized for efficient CI/CD pipelines and container workflows

### fullstack-devbox
- Sets up a Bun development environment with integrated PostgreSQL
- Includes a React Todo app demo with Bun's HMR (Hot Module Reloading)
- Provides a complete fullstack development environment ready for use
- Claude code setup instructions included for AI fullstack development

## Prerequisites

- A Morph Cloud [account](https://cloud.morph.so/docs/developers)
- Morph Cloud API key exported in your environment:
  ```bash
  export MORPH_API_KEY=your_api_key_here
  ```
- Python 3.11+ with pip or uv package manager

## Usage

Each example has its own directory with a detailed README and setup script.

## Resources

- [Morph Cloud Documentation](https://cloud.morph.so/docs/developers)
- [Morph Cloud Python SDK](https://github.com/morph-labs/morph-python-sdk/)
- [Morph Cloud Typescript SDK](https://github.com/morph-labs/morph-typescript-sdk/)
