#!/usr/bin/env python3
import requests
import time
import random
import json
from typing import Dict, Any

# Base URL for the initial instance
BASE_URL = "https://pantograph-morphvm-8xlie2k0.http.cloud.morph.so"

def call_api_with_retry(endpoint: str, params: Dict[str, Any] = None, 
                         max_retries: int = 3, retry_delay: float = 2.0) -> Dict[str, Any]:
    """Call the Pantograph API endpoint with retry logic."""
    url = f"{BASE_URL}/{endpoint}"
    
    for attempt in range(max_retries):
        try:
            if endpoint.startswith("goal_state/"):
                # goal_state uses a GET request
                response = requests.get(url, timeout=30)
            else:
                # Other endpoints use POST requests with query parameters
                response = requests.post(url, params=params, timeout=30)
            
            if response.status_code >= 400:
                print(f"API Error: {response.status_code}, {response.text}")
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt) + random.uniform(0, 1)
                    print(f"Retrying in {wait_time:.2f} seconds... (Attempt {attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                return {"error": f"Error {response.status_code}: {response.text}"}
            
            # Print the full response for debugging
            print(f"Response status: {response.status_code}")
            try:
                return response.json()
            except json.JSONDecodeError as e:
                print(f"Failed to decode JSON response: {e}")
                print(f"Response content: {response.text[:1000]}")  # Show first 1000 chars
                return {"error": f"Invalid JSON response: {str(e)}"}
        
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt) + random.uniform(0, 1)
                print(f"Connection error: {str(e)}. Retrying in {wait_time:.2f} seconds... (Attempt {attempt+1}/{max_retries})")
                time.sleep(wait_time)
            else:
                print(f"Failed after {max_retries} attempts: {str(e)}")
                return {"error": f"Connection error: {str(e)}"}
    
    return {"error": "Maximum retries exceeded"}

def test_single_tactic():
    """Test starting a goal and applying a single tactic."""
    print(f"Starting goal on {BASE_URL}")
    
    # 1. Start a theorem proving goal
    theorem = "forall (p q : Prop), p -> q -> And p q"
    result = call_api_with_retry("goal_start", {"term": theorem})
    
    if "handle" not in result:
        print(f"Failed to start goal: {result}")
        return
    
    handle = result["handle"]
    print(f"Goal started with handle: {handle}")
    
    # 2. Get the initial state
    print("Getting initial state...")
    initial_state = call_api_with_retry(f"goal_state/{handle}")
    if "error" in initial_state:
        print(f"Failed to get initial state: {initial_state}")
        return
    
    print(f"Initial state:")
    print(json.dumps(initial_state, indent=2))
    
    # 3. Apply a single tactic
    tactic = "intro p q hp hq"
    print(f"Applying tactic: '{tactic}'")
    
    result = call_api_with_retry("goal_tactic", {
        "handle": handle,
        "goal_id": 0,
        "tactic": tactic
    })
    
    if "error" in result:
        print(f"Failed to apply tactic: {result}")
        return
    
    # 4. Get the state after applying the tactic
    new_handle = result.get("handle", handle)
    print(f"New handle after tactic: {new_handle}")
    
    final_state = call_api_with_retry(f"goal_state/{new_handle}")
    if "error" in final_state:
        print(f"Failed to get final state: {final_state}")
        return
    
    print(f"Final state after applying '{tactic}':")
    print(json.dumps(final_state, indent=2))
    
    # 5. Check if the proof is complete
    goals = final_state.get("goals", [])
    status = "Proof completed!" if not goals else f"{len(goals)} goals remaining"
    print(f"Status: {status}")

if __name__ == "__main__":
    test_single_tactic()