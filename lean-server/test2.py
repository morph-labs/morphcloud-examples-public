#!/usr/bin/env python3
import requests
import json
import time
import argparse
from typing import Dict, Any, Optional, List, Tuple
from colorama import Fore, Style, init

# Initialize colorama
init()

class PantographAPITester:
    """Client for testing the PyPantograph daemon API."""
    
    def __init__(self, base_url: str = "http://localhost:5326"):
        self.base_url = base_url
        self.current_handle = None
    
    def print_response(self, resp: requests.Response, label: str = "") -> Dict[str, Any]:
        """Print a formatted response and return the JSON data."""
        prefix = f"{label}: " if label else ""
        
        try:
            data = resp.json()
            if resp.status_code >= 400:
                print(f"{prefix}{Fore.RED}Status: {resp.status_code}, Response: {json.dumps(data, indent=2)}{Style.RESET_ALL}")
            else:
                print(f"{prefix}{Fore.GREEN}Status: {resp.status_code}{Style.RESET_ALL}")
                print(f"{json.dumps(data, indent=2)}")
            return data
        except ValueError:
            print(f"{prefix}{Fore.YELLOW}Status: {resp.status_code}, Raw response: {resp.text}{Style.RESET_ALL}")
            return {}

    def test_goal_start(self, term: str = "forall (p q: Prop), p -> p") -> str:
        """Test the goal_start endpoint."""
        print(f"\n{Fore.CYAN}Testing goal_start with term: {term}{Style.RESET_ALL}")
        
        url = f"{self.base_url}/goal_start"
        resp = requests.post(url, params={"term": term})
        data = self.print_response(resp, "goal_start")
        
        if "handle" in data:
            self.current_handle = data["handle"]
            return self.current_handle
        return None

    def test_goal_tactic(self, handle: str, goal_id: int, tactic: str) -> str:
        """Test the goal_tactic endpoint."""
        print(f"\n{Fore.CYAN}Testing goal_tactic with: Handle={handle}, Goal ID={goal_id}, Tactic='{tactic}'{Style.RESET_ALL}")
        
        url = f"{self.base_url}/goal_tactic"
        params = {"handle": handle, "goal_id": goal_id, "tactic": tactic}
        resp = requests.post(url, params=params)
        data = self.print_response(resp, "goal_tactic")
        
        if "handle" in data:
            return data["handle"]
        return None

    def test_goal_state(self, handle: str) -> Dict[str, Any]:
        """Test the goal_state endpoint."""
        print(f"\n{Fore.CYAN}Testing goal_state with handle: {handle}{Style.RESET_ALL}")
        
        url = f"{self.base_url}/goal_state/{handle}"
        resp = requests.get(url)
        return self.print_response(resp, "goal_state")

    def test_goal_continue(self, handle: str) -> str:
        """Test the goal_continue endpoint."""
        print(f"\n{Fore.CYAN}Testing goal_continue with handle: {handle}{Style.RESET_ALL}")
        
        url = f"{self.base_url}/goal_continue"
        params = {"handle": handle}
        resp = requests.post(url, params=params)
        data = self.print_response(resp, "goal_continue")
        
        if "handle" in data:
            return data["handle"]
        return None

    def test_expr_type(self, expr: str = "forall (p q: Prop), p -> p") -> Dict[str, Any]:
        """Test the expr_type endpoint."""
        print(f"\n{Fore.CYAN}Testing expr_type with expression: {expr}{Style.RESET_ALL}")
        
        url = f"{self.base_url}/expr_type"
        resp = requests.post(url, params={"expr": expr})
        return self.print_response(resp, "expr_type")

    def test_gc(self) -> Dict[str, Any]:
        """Test the gc endpoint."""
        print(f"\n{Fore.CYAN}Testing gc endpoint{Style.RESET_ALL}")
        
        url = f"{self.base_url}/gc"
        resp = requests.post(url)
        return self.print_response(resp, "gc")

    def test_goal_save(self, handle: str, path: str = "test_goal.save") -> Dict[str, Any]:
        """Test the goal_save endpoint."""
        print(f"\n{Fore.CYAN}Testing goal_save with: Handle={handle}, Path={path}{Style.RESET_ALL}")
        
        url = f"{self.base_url}/goal_save"
        params = {"handle": handle, "path": path}
        resp = requests.post(url, params=params)
        return self.print_response(resp, "goal_save")

    def test_goal_load(self, path: str = "test_goal.save") -> str:
        """Test the goal_load endpoint."""
        print(f"\n{Fore.CYAN}Testing goal_load with path: {path}{Style.RESET_ALL}")
        
        url = f"{self.base_url}/goal_load"
        params = {"path": path}
        resp = requests.post(url, params=params)
        data = self.print_response(resp, "goal_load")
        
        if "handle" in data:
            return data["handle"]
        return None

    def test_compile(self, content: str = "example (p: Prop): p -> p := fun h => h") -> Dict[str, Any]:
        """Test the compile endpoint."""
        print(f"\n{Fore.CYAN}Testing compile with content {content}{Style.RESET_ALL}")
        
        url = f"{self.base_url}/compile"
        data = {"content": content}
        resp = requests.post(url, params=data)
        return self.print_response(resp, "compile")

    def test_tactic_invocations(self, file_name: str = "Agent.lean") -> Dict[str, Any]:
        """Test the tactic_invocations endpoint."""
        print(f"\n{Fore.CYAN}Testing tactic_invocations{Style.RESET_ALL}")
        
        url = f"{self.base_url}/tactic_invocations"
        data = {"file_name": file_name}
        resp = requests.post(url, params=data)
        return self.print_response(resp, "tactic_invocations")
        
    def test_process_full_lean_file(self, lean_code: str = None) -> Dict[str, Any]:
        """Process a full Lean file and get all outstanding goals/issues.
        
        This is the idiomatic way to take a complete Lean file as a string and 
        extract all outstanding goals and issues in a structured format.
        """
        if lean_code is None:
            lean_code = """
theorem add_comm_proved_formal_sketch : ∀ n m : Nat, n + m = m + n := 
by
   -- Consider some n and m in Nats.
   intros n m
   -- Perform induction on n.
   induction n with
   | zero =>
     -- Base case: When n = 0, we need to show 0 + m = m + 0.
     -- We have the fact 0 + m = m by the definition of addition.
     have h_base: 0 + m = m := sorry
     -- We also have the fact m + 0 = m by the definition of addition.
     have h_symm: m + 0 = m := sorry
     -- Combine facts to close goal
     sorry
   | succ n ih =>
     sorry
"""
        
        print(f"\n{Fore.CYAN}Processing complete Lean file{Style.RESET_ALL}")
        
        # Option 1: Using load_sorry to get all sorry-marked goals
        url = f"{self.base_url}/load_sorry"
        resp = requests.post(url, json={"content": lean_code})
        data = self.print_response(resp, "load_sorry")
        
        # Extract and organize goals and issues
        compilation_units = data.get("units", [])
        goals = []
        issues = []
        
        for unit in compilation_units:
            # Check for goals (from sorries)
            if "goal_handle" in unit:
                # Get details for this goal
                goal_state = self.test_goal_state(unit["goal_handle"])
                goals.append({
                    "unit": unit.get("file_name", "unknown"),
                    "handle": unit["goal_handle"],
                    "state": goal_state
                })
            
            # Check for messages/errors
            if "messages" in unit:
                for msg in unit["messages"]:
                    issues.append({
                        "unit": unit.get("file_name", "unknown"),
                        "message": msg
                    })
        
        result = {
            "goals": goals,
            "issues": issues,
            "compilation_units": compilation_units
        }
        
        # Print a summary
        print(f"\n{Fore.BLUE}Summary of Lean File Analysis:{Style.RESET_ALL}")
        print(f"- Found {len(goals)} outstanding goals")
        print(f"- Found {len(issues)} messages/issues")
        
        return result

    def run_simple_proof_test(self):
        """Run a simple proof test using multiple API endpoints."""
        print(f"\n{Fore.BLUE}========== Running Simple Proof Test =========={Style.RESET_ALL}")
        
        # Start a new goal
        handle = self.test_goal_start("forall (p: Prop), p -> p")
        if not handle:
            print(f"{Fore.RED}Failed to initialize goal{Style.RESET_ALL}")
            return
        
        # Execute tactics to complete the proof
        handle = self.test_goal_tactic(handle, 0, "intro p")
        if not handle:
            print(f"{Fore.RED}Failed to apply first tactic{Style.RESET_ALL}")
            return
            
        handle = self.test_goal_tactic(handle, 0, "intro h")
        if not handle:
            print(f"{Fore.RED}Failed to apply second tactic{Style.RESET_ALL}")
            return
            
        handle = self.test_goal_tactic(handle, 0, "exact h")
        if not handle:
            print(f"{Fore.RED}Failed to apply third tactic{Style.RESET_ALL}")
            return
            
        # Check the goal state (should be solved)
        state = self.test_goal_state(handle)
        print(f"\n{Fore.GREEN}Proof completed successfully!{Style.RESET_ALL}" if not state.get("goals", []) else f"\n{Fore.RED}Proof not completed!{Style.RESET_ALL}")

    def run_complex_proof_test(self):
        """Run a more complex proof test using multiple API endpoints."""
        print(f"\n{Fore.BLUE}========== Running Complex Proof Test =========={Style.RESET_ALL}")
        
        # Start a new goal
        handle = self.test_goal_start("forall (p q: Prop), Or p q -> Or q p")
        if not handle:
            print(f"{Fore.RED}Failed to initialize goal{Style.RESET_ALL}")
            return
        
        # Step 1: Introduce variables (providing complete binders)
        handle = self.test_goal_tactic(handle, 0, "intro p")
        if not handle: return
        handle = self.test_goal_tactic(handle, 0, "intro q")
        if not handle: return
        handle = self.test_goal_tactic(handle, 0, "intro h")
        if not handle: return
            
        # Step 2: Case analysis
        handle = self.test_goal_tactic(handle, 0, "cases h")
        if not handle:
            return
            
        # Get the current state
        state = self.test_goal_state(handle)
        
        # Step 3: Handle first case (inl)
        handle = self.test_goal_tactic(handle, 0, "apply Or.inr")
        if not handle:
            return
            
        handle = self.test_goal_tactic(handle, 0, "assumption")
        if not handle:
            return
            
        # Step 4: Handle second case (inr)
        handle = self.test_goal_tactic(handle, 0, "apply Or.inl")
        if not handle:
            return
            
        handle = self.test_goal_tactic(handle, 0, "assumption")
        if not handle:
            return
            
        # Check the goal state (should be solved)
        state = self.test_goal_state(handle)
        print(f"\n{Fore.GREEN}Proof completed successfully!{Style.RESET_ALL}" if not state.get("goals", []) else f"\n{Fore.RED}Proof not completed!{Style.RESET_ALL}")
        
        # Test save/load functionality with this completed proof
        self.test_goal_save(handle, "complex_proof.save")
        loaded_handle = self.test_goal_load("complex_proof.save")
        if loaded_handle:
            self.test_goal_state(loaded_handle)

    def run_error_test(self):
        """Test error handling in the API."""
        print(f"\n{Fore.BLUE}========== Testing Error Handling =========={Style.RESET_ALL}")
        
        # Start a new goal
        handle = self.test_goal_start("forall (p: Prop), p -> p")
        if not handle:
            print(f"{Fore.RED}Failed to initialize goal{Style.RESET_ALL}")
            return
        
        # Test with an invalid tactic
        print(f"\n{Fore.YELLOW}Testing with an invalid tactic (should fail):{Style.RESET_ALL}")
        self.test_goal_tactic(handle, 0, "invalid_tactic")
        
        # Test with an invalid handle
        print(f"\n{Fore.YELLOW}Testing with an invalid handle (should fail):{Style.RESET_ALL}")
        self.test_goal_state("invalid_handle")
        
        # Test with invalid goal ID
        print(f"\n{Fore.YELLOW}Testing with invalid goal ID (should fail):{Style.RESET_ALL}")
        self.test_goal_tactic(handle, 999, "intro p")
        
        # Test with invalid expression
        print(f"\n{Fore.YELLOW}Testing expr_type with invalid expression (should fail):{Style.RESET_ALL}")
        self.test_expr_type("this is not valid Lean code")

def main():
    parser = argparse.ArgumentParser(description="Test the PyPantograph daemon API")
    parser.add_argument("--url", default="http://localhost:5326", help="Base URL for the API")
    parser.add_argument("--test", choices=["all", "simple", "complex", "error", "endpoints", "full-file"], 
                        default="all", help="Which test(s) to run")
    parser.add_argument("--file", type=str, help="Path to a Lean file to process (for full-file test)")
    args = parser.parse_args()
    
    tester = PantographAPITester(args.url)
    
    if args.test in ["all", "endpoints"]:
        # Test individual endpoints
        handle = tester.test_goal_start()
        if handle:
            tester.test_goal_state(handle)
            tester.test_goal_tactic(handle, 0, "intro p")
            tester.test_goal_save(handle)
            tester.test_goal_continue(handle)
        
        tester.test_expr_type()
        tester.test_gc()
        tester.test_goal_load()
        tester.test_compile()
        tester.test_tactic_invocations()
    
    if args.test in ["all", "simple"]:
        tester.run_simple_proof_test()
    
    if args.test in ["all", "complex"]:
        tester.run_complex_proof_test()
    
    if args.test in ["all", "error"]:
        tester.run_error_test()
        
    if args.test in ["full-file"]:
        # Process a full Lean file
        if args.file:
            try:
                with open(args.file, 'r') as f:
                    file_content = f.read()
                tester.test_process_full_lean_file(file_content)
            except FileNotFoundError:
                print(f"{Fore.RED}Error: File '{args.file}' not found{Style.RESET_ALL}")
        else:
            # Use the default example
            tester.test_process_full_lean_file()

if __name__ == "__main__":
    main()