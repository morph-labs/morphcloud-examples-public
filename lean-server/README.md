# pantograph-morph-cloud

A ready-to-use Lean 4 server on Morph Cloud powered by PyPantograph. This service allows you to interact with the Lean theorem prover through HTTP endpoints, making it ideal for building tools, editors, and proof assistants that use Lean as a backend.

## What is this?

This repository provides:
- A setup script that creates a Morph Cloud VM with Lean 4, PyPantograph, and Mathlib4
- A FastAPI server that exposes PyPantograph's functionality over HTTP
- Documentation for all API endpoints

## Prerequisites

- A Morph Cloud account with API access
- Python 3.11+ installed locally
- The Morph Cloud Python SDK: `pip install morphcloud`

## Deployment

1. Clone this repository
2. Make sure your Morph Cloud token is configured (set as environment variable `MORPHCLOUD_API_KEY`)
3. Run the setup script:

```bash
python setup.py
```

The setup script will:
- Create a VM snapshot with all necessary dependencies
- Start the Lean server on port 5326
- Print the URL to access your server

When complete, you'll see something like:

```
Snapshot ready: snapshot_abcd1234
Pantograph server ready at: https://pantograph-morphvm-abcd1234.http.cloud.morph.so
```

## API Usage

The server exposes several HTTP endpoints for interacting with Lean. Here are the main endpoints:

### Goal Management

- `POST /goal_start` - Start a goal state with an initial term
  ```json
  {"term": "∀ (n : Nat), n + 0 = n"}
  ```

- `POST /goal_tactic` - Apply a tactic to a specific goal
  ```json
  {"handle": "gs_1234abcd", "goal_id": 0, "tactic": "intro n"}
  ```

- `GET /goal_state/{handle}` - Get the current state of a goal

### State Management

- `POST /goal_save` - Save the current goal state
  ```json
  {"handle": "gs_1234abcd", "path": "saved_goal.state"}
  ```

- `POST /goal_load` - Load a previously saved goal state
  ```json
  {"path": "saved_goal.state"}
  ```

### Compilation and Type Checking

- `POST /compile` - Compile Lean code and return messages
  ```json
  {"content": "theorem ex : 1 + 1 = 2 := by sorry"}
  ```

- `POST /expr_type` - Get the type of an expression
  ```json
  {"expr": "Nat.succ"}
  ```

- `POST /tactic_invocations` - Parse tactic invocations in Lean code
  ```json
  {"file_name": "Example.lean"}
  ```