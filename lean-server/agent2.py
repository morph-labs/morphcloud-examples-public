#!/usr/bin/env python3
import concurrent.futures
import requests
import time
import random
import json
from typing import Dict, Any, List
from morphcloud.api import MorphCloudClient
from colorama import Fore, Style, init

# Initialize colorama
init()

# ASCII Art Banner
BANNER = f"""
{Fore.CYAN}
 ╔═════════════════════════════════════════════════════════╗
 ║ {Fore.YELLOW}╔═╗╔═╗╦═╗╔═╗╦  ╦  ╔═╗╦    ╔═╗╦═╗╔═╗╔═╗╔═╗╔═╗{Fore.CYAN}            ║
 ║ {Fore.YELLOW}╠═╝╠═╣╠╦╝╠═╣║  ║  ║╣ ║    ╠═╝╠╦╝║ ║║ ║╠╣ ╚═╗{Fore.CYAN}            ║
 ║ {Fore.YELLOW}╩  ╩ ╩╩╚═╩ ╩╩═╝╩═╝╚═╝╩═╝  ╩  ╩╚═╚═╝╚═╝╚  ╚═╝{Fore.CYAN}            ║
 ╚═════════════════════════════════════════════════════════╝
  {Fore.GREEN}Using MorphCloud's InfiniBranch for Parallel Tactics 🚀
{Style.RESET_ALL}"""

# Initialize MorphCloud client
mc = MorphCloudClient()

# Initial base URL and extract instance ID
INITIAL_BASE_URL = "https://pantograph-morphvm-8xlie2k0.http.cloud.morph.so"
INITIAL_INSTANCE_ID = "morphvm_8xlie2k0"  # Note: URL uses hyphen, instance ID uses underscore

# Base URL template for new instances
BASE_URL_TEMPLATE = "https://pantograph-morphvm-{}.http.cloud.morph.so"

# Different tactics to try in parallel (second part only after intro)
TACTICS = [
    "rw[add_comm]",
    "rw[add_assoc]",
    "rw[mul_assoc]",
    "rw[mul_comm]", 
    "simp",
    "ring_nf",
    "simp only[add_comm, add_assoc, mul_assoc, mul_comm]",
    "norm_num"
]

def print_goal_state(state: Dict[str, Any], prefix: str = ""):
    """Print the goal state in a readable format."""
    if "error" in state:
        print(f"{prefix}{Fore.RED}Error retrieving goal state: {state['error']}{Style.RESET_ALL}")
        return
    
    goals = state.get("goals", [])
    if not goals:
        print(f"{prefix}{Fore.GREEN}✅ No goals remaining - proof is complete! 🎉{Style.RESET_ALL}")
        return
    
    print(f"{prefix}{Fore.CYAN}==== Goal State ({len(goals)} goals) ===={Style.RESET_ALL}")
    
    for i, goal in enumerate(goals):
        print(f"{prefix}{Fore.YELLOW}Goal {i}:{Style.RESET_ALL}")
        
        # Print hypotheses
        hypotheses = goal.get("hyps", [])
        if hypotheses:
            print(f"{prefix}  {Fore.MAGENTA}Hypotheses:{Style.RESET_ALL}")
            for hyp in hypotheses:
                name = hyp.get("id", "")
                type_str = hyp.get("type", "")
                print(f"{prefix}    {Fore.BLUE}{name}{Style.RESET_ALL} : {Fore.GREEN}{type_str}{Style.RESET_ALL}")
        
        # Print target
        target = goal.get("target", "")
        print(f"{prefix}  {Fore.MAGENTA}Target:{Style.RESET_ALL} {Fore.CYAN}{target}{Style.RESET_ALL}")
        print()
    
    print(f"{prefix}{Fore.CYAN}============================{Style.RESET_ALL}")

def call_api_with_retry(base_url: str, endpoint: str, params: Dict[str, Any] = None, 
                         max_retries: int = 3, retry_delay: float = 2.0) -> Dict[str, Any]:
    """Call the Pantograph API endpoint with retry logic."""
    url = f"{base_url}/{endpoint}"
    
    for attempt in range(max_retries):
        try:
            if endpoint.startswith("goal_state/"):
                # goal_state uses a GET request
                response = requests.get(url, timeout=30)
            else:
                # Other endpoints use POST requests with query parameters
                response = requests.post(url, params=params, timeout=30)
            
            # Special handling for 502 errors (invalid tactic)
            if response.status_code == 502:
                print(f"{Fore.RED}⚠️ Error 502: Tactic returned an error (Bad Gateway){Style.RESET_ALL}")
                return {"error": "Tactic error: The provided tactic caused a server error"}
            
            if response.status_code >= 400:
                print(f"{Fore.RED}🔴 API Error: {response.status_code}, {response.text}{Style.RESET_ALL}")
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt) + random.uniform(0, 1)
                    print(f"{Fore.YELLOW}🔄 Retrying in {wait_time:.2f} seconds... (Attempt {attempt+1}/{max_retries}){Style.RESET_ALL}")
                    time.sleep(wait_time)
                    continue
                return {"error": f"Error {response.status_code}: {response.text}"}
            
            return response.json()
        
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt) + random.uniform(0, 1)
                print(f"{Fore.YELLOW}🔌 Connection error: {str(e)}. Retrying in {wait_time:.2f} seconds... (Attempt {attempt+1}/{max_retries}){Style.RESET_ALL}")
                time.sleep(wait_time)
            else:
                print(f"{Fore.RED}❌ Failed after {max_retries} attempts: {str(e)}{Style.RESET_ALL}")
                return {"error": f"Connection error: {str(e)}"}
    
    return {"error": "Maximum retries exceeded"}

def apply_tactic_on_branch(branch_index: int, instance, handle: str, tactic: str) -> Dict[str, Any]:
    """Apply a tactic on a branched instance."""
    try:
        # Extract the instance ID (the part after "morphvm_")
        instance_id = instance.id.split("_")[1]
        
        # Create the new base URL (note: URL uses hyphen instead of underscore)
        branch_url = BASE_URL_TEMPLATE.format(instance_id)
        
        print(f"{Fore.CYAN}🌿 Branch {branch_index}: Applying tactic '{Fore.YELLOW}{tactic}{Fore.CYAN}' on {branch_url}{Style.RESET_ALL}")
        
        # Add a short delay to allow server to be ready
        time.sleep(1 + random.uniform(0, 1))
        
        # Apply the tactic on the branched instance with retry
        result = call_api_with_retry(branch_url, "goal_tactic", {
            "handle": handle,
            "goal_id": 0,
            "tactic": tactic
        })
        
        if "error" in result:
            return {
                "branch_index": branch_index,
                "tactic": tactic,
                "error": result["error"]
            }
        
        # Get the state after applying the tactic
        new_handle = result.get("handle", handle)
        state = call_api_with_retry(branch_url, f"goal_state/{new_handle}")
        
        # Print the goal state for this branch
        print(f"\n{Fore.GREEN}🔍 Result from Branch {branch_index} (tactic: '{tactic}'):{Style.RESET_ALL}")
        print_goal_state(state, prefix="  ")
        
        return {
            "branch_index": branch_index,
            "branch_url": branch_url,
            "tactic": tactic,
            "result": result,
            "state": state
        }
    except Exception as e:
        print(f"{Fore.RED}❌ Error in branch {branch_index}: {str(e)}{Style.RESET_ALL}")
        return {
            "branch_index": branch_index,
            "tactic": tactic,
            "error": str(e)
        }

def main():
    print(BANNER)
    
    # Start a goal on the initial instance
    print(f"{Fore.GREEN}🚀 Starting goal on initial instance {Fore.BLUE}{INITIAL_BASE_URL}{Style.RESET_ALL}")
    
    # Start a theorem proving goal
    theorem = "forall (n m a b : Nat), n * a + m * b + a * b = b * m + (b * a + a * n)"
    result = call_api_with_retry(INITIAL_BASE_URL, "goal_start", {"term": theorem})
    
    if "handle" not in result:
        raise Exception(f"Failed to start goal: {result}")
    
    handle = result["handle"]
    print(f"{Fore.GREEN}✅ Goal started with handle: {Fore.YELLOW}{handle}{Style.RESET_ALL}")
    
    # Get initial state
    initial_state = call_api_with_retry(INITIAL_BASE_URL, f"goal_state/{handle}")
    print(f"\n{Fore.CYAN}📊 Initial goal state:{Style.RESET_ALL}")
    print_goal_state(initial_state)
    
    # First apply the common intro tactic to the initial instance
    print(f"\n{Fore.YELLOW}⚙️ Applying common tactic 'intro n m a b' on initial instance...{Style.RESET_ALL}")
    common_tactic_result = call_api_with_retry(INITIAL_BASE_URL, "goal_tactic", {
        "handle": handle,
        "goal_id": 0,
        "tactic": "intro n m a b"
    })
    
    if "error" in common_tactic_result:
        raise Exception(f"Failed to apply common tactic: {common_tactic_result}")
    
    # Get the updated handle after applying the common tactic
    handle = common_tactic_result.get("handle", handle)
    print(f"{Fore.GREEN}✅ New handle after common tactic: {Fore.YELLOW}{handle}{Style.RESET_ALL}")
    
    # Get the state after the common tactic
    state = call_api_with_retry(INITIAL_BASE_URL, f"goal_state/{handle}")
    if "error" in state:
        raise Exception(f"Failed to get state after common tactic: {state}")
    
    # Print the goal state before branching
    print(f"\n{Fore.CYAN}📊 Goal state after applying 'intro n m a b' (before branching):{Style.RESET_ALL}")
    print_goal_state(state)
    
    goals = state.get("goals", [])
    if not goals:
        print(f"{Fore.GREEN}🎉 Proof already completed after common tactic!{Style.RESET_ALL}")
        return
    
    # Get the initial instance object
    initial_instance = mc.instances.get(INITIAL_INSTANCE_ID)
    
    # Branch ASCII Art
    print(f"""
{Fore.CYAN}
      ┌───────┐
      │ Start │
      └───┬───┘
          │
    ┌─────┴─────┐
    │ Common    │
    │ Tactic    │
    └─────┬─────┘
          │
          ▼
{Fore.YELLOW}    ╔═══════════╗           {Fore.MAGENTA}BRANCHING{Fore.YELLOW}           ╔═══════════╗
    ║  Branch 1 ║◄───────────┬─────────────────►║  Branch n ║
    ╚═════╦═════╝            │                  ╚═════╦═════╝
          ▼                  │                        ▼
    ┌─────┴─────┐      ┌─────┴─────┐            ┌─────┴─────┐
    │ Tactic 1  │      │    ...    │            │ Tactic n  │
    └─────┬─────┘      └───────────┘            └─────┬─────┘
          │                                           │
          ▼                                           ▼
    ┌─────┴─────┐                               ┌─────┴─────┐
    │ Result 1  │                               │ Result n  │
    └───────────┘                               └───────────┘
{Style.RESET_ALL}
    """)
    
    # Branch the instance all at once (proper SDK usage)
    branch_count = min(len(TACTICS), 15)
    print(f"{Fore.YELLOW}🔀 Creating {branch_count} branches in one operation...{Style.RESET_ALL}")
    
    try:
        # The branch method returns a tuple: (snapshot, list_of_instances)
        snapshot, branch_instances = initial_instance.branch(branch_count)
        print(f"{Fore.GREEN}✅ Created {len(branch_instances)} branches from snapshot {Fore.BLUE}{snapshot.id}{Style.RESET_ALL}")
        
        # Expose HTTP service for each branch instance
        print(f"{Fore.YELLOW}🌐 Exposing HTTP service for each branch...{Style.RESET_ALL}")
        for i, instance in enumerate(branch_instances):
            # Make sure instance is ready (the SDK already waits in branch(), but this is explicit)
            instance.wait_until_ready()
            
            # Expose the HTTP service
            url = instance.expose_http_service('pantograph', 5326)
            print(f"{Fore.CYAN}🔗 Branch {i+1}: HTTP service exposed at {Fore.BLUE}{url}{Style.RESET_ALL}")
        
        # Map the branches to tactics
        branches = [
            {
                "index": i + 1,
                "instance": branch_instances[i],
                "tactic": TACTICS[i]
            }
            for i in range(len(branch_instances))
        ]
    except Exception as e:
        print(f"{Fore.RED}❌ Failed to create branches: {str(e)}{Style.RESET_ALL}")
        return
    
    # Wait a bit after exposing all HTTP services
    print(f"{Fore.YELLOW}⏳ Waiting for all HTTP services to initialize...{Style.RESET_ALL}")
    time.sleep(5)
    
    # Execute tactics on branches in parallel with a smaller number of workers
    max_workers = min(5, len(branches))  # Limit concurrent executions to reduce server load
    print(f"\n{Fore.GREEN}⚡ Executing tactics in parallel with {max_workers} workers...{Style.RESET_ALL}")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit tasks for parallel execution
        futures = {
            executor.submit(
                apply_tactic_on_branch,
                branch["index"],
                branch["instance"],
                handle,
                branch["tactic"]
            ): branch
            for branch in branches
        }
        
        # Process results as they complete
        results = []
        for future in concurrent.futures.as_completed(futures):
            branch = futures[future]
            try:
                result = future.result()
                results.append(result)
                
                # Status is already printed in apply_tactic_on_branch
            except Exception as e:
                print(f"{Fore.RED}❌ Error processing branch {branch['index']}: {str(e)}{Style.RESET_ALL}")
    
    # Print summary
    print(f"\n{Fore.YELLOW}╔═══════════════════════════════════════════════╗")
    print(f"║ 📊 SUMMARY OF PARALLEL TACTIC EXECUTION 📊    ║")
    print(f"╚═══════════════════════════════════════════════╝{Style.RESET_ALL}")
    
    # Count successes and failures
    successes = sum(1 for r in results if "error" not in r)
    completions = sum(1 for r in results if "error" not in r and not r["state"].get("goals", []))
    
    for result in sorted(results, key=lambda r: r.get("branch_index", 999)):
        if "error" in result:
            print(f"{Fore.RED}❌ Branch {result['branch_index']}: Tactic '{Fore.YELLOW}{result['tactic']}{Fore.RED}' - Error: {result['error']}{Style.RESET_ALL}")
        else:
            goals = result["state"].get("goals", [])
            if not goals:
                status = f"{Fore.GREEN}🎉 Proof completed!{Style.RESET_ALL}"
            else:
                status = f"{Fore.YELLOW}⏳ {len(goals)} goals remaining{Style.RESET_ALL}"
            print(f"{Fore.BLUE}🔸 Branch {result['branch_index']}: Tactic '{Fore.YELLOW}{result['tactic']}{Fore.BLUE}' - {status}")
    
    # Final statistics
    print(f"\n{Fore.CYAN}📈 Statistics: {Fore.GREEN}{successes}/{len(results)} tactics succeeded, {Fore.YELLOW}{completions} completed the proof{Style.RESET_ALL}")
    
    # Closing ASCII Art
    print(f"""
{Fore.GREEN}
    ╔═════════════════════════════════════════════════════╗
    ║                                                     ║
    ║  ╔═╗╦═╗╔═╗╔═╗╔═╗  ╔═╗╔═╗╔╦╗╔═╗╦  ╔═╗╔╦╗╔═╗╔╦╗       ║
    ║  ╠═╝╠╦╝║ ║║ ║╠╣   ║  ║ ║║║║╠═╝║  ║╣  ║ ║╣  ║║       ║
    ║  ╩  ╩╚═╚═╝╚═╝╚    ╚═╝╚═╝╩ ╩╩  ╩═╝╚═╝ ╩ ╚═╝═╩╝       ║
    ║                                                     ║
    ╚═════════════════════════════════════════════════════╝
{Style.RESET_ALL}
    """)

if __name__ == "__main__":
    main()