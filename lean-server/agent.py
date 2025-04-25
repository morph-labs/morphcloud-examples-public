import os, requests, json
from anthropic import Anthropic
from typing import List, Dict, Any, Optional

# Initialize Claude client
client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# Update with your deployed instance URL
BASE_URL = "https://pantograph-morphvm-8xlie2k0.http.cloud.morph.so"

# Define the pantograph tools
pantograph_tools = [
    {
        "name": "goal_start",
        "description": "Start a new Lean proof goal from a theorem statement.",
        "input_schema": {
            "type": "object",
            "properties": {"term": {"type": "string"}},
            "required": ["term"]
        }
    },
    {
        "name": "goal_tactic",
        "description": "Apply a tactic to a proof state.",
        "input_schema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string"},
                "goal_id": {"type": "integer"},
                "tactic": {"type": "string"}
            },
            "required": ["handle", "goal_id", "tactic"]
        }
    },
    {
        "name": "goal_state",
        "description": "Get the current state of a proof goal.",
        "input_schema": {
            "type": "object",
            "properties": {"handle": {"type": "string"}},
            "required": ["handle"]
        }
    }
]

# System message to guide Claude in theorem proving
SYSTEM_MESSAGE = """You are a Lean theorem prover assistant. Your goal is to prove mathematical theorems using Lean tactics.
When presented with a theorem to prove:
1. Use goal_start to begin the proof and get a goal state.
2. Analyze the goal state to determine what tactics to apply.
3. Use goal_tactic to apply appropriate tactics, updating the proof state.
4. Use goal_state as needed to check the current state.
5. Continue until you've successfully proven the theorem.

Common Lean tactics:
- intro/intros: Introduce variables and hypotheses
- rw: Rewrite using an equation
- simp: Simplify expressions
- exact: Provide an exact proof term

When you've completed the proof, explain your approach and summarize the key steps.
"""

def call_pantograph_api(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Call the Pantograph API endpoint."""
    print(f"\n🔧 Calling {tool_name} with params: {json.dumps(params, indent=2)}")
    
    if tool_name == "goal_state":
        # goal_state uses a GET request with handle in the URL path
        handle = params.get("handle")
        response = requests.get(f"{BASE_URL}/{tool_name}/{handle}")
    else:
        # Other endpoints use POST requests with query parameters (not JSON)
        response = requests.post(f"{BASE_URL}/{tool_name}", params=params)
    
    if response.status_code >= 400:
        print(f"⚠️ API Error: {response.status_code}, {response.text}")
        return {"error": f"Error {response.status_code}: {response.text}"}
    
    result = response.json()
    print(f"📊 Result: {json.dumps(result, indent=2)}")
    return result

def run_proof_agent(theorem: str, max_iterations: int = 15):
    """Run the proof agent to solve a theorem."""
    print(f"\n🔍 Starting proof for: {theorem}")
    
    # Initialize conversation
    messages = [{"role": "user", "content": f"Prove {theorem}"}]
    
    for i in range(max_iterations):
        print(f"\n🔄 Iteration {i+1}/{max_iterations}")
        
        # Get Claude's response
        response = client.messages.create(
            model="claude-3-7-sonnet-20250219",
            system=SYSTEM_MESSAGE,
            messages=messages,
            tools=pantograph_tools,
            max_tokens=1000,
            temperature=0
        )
        
        # Extract text content and tool calls
        text_blocks = [b for b in response.content if b.type == "text"]
        tool_calls = [b for b in response.content if b.type == "tool_use"]
        
        # Record Claude's full response
        if tool_calls:
            # Store the full response including tool calls
            messages.append({"role": "assistant", "content": response.content})
            
            # Process tool use
            tool_call = tool_calls[0]
            tool_name = tool_call.name
            tool_input = tool_call.input
            tool_id = tool_call.id
            
            # Call the Pantograph API
            result = call_pantograph_api(tool_name, tool_input)
            
            # Convert result dict to a JSON string for the tool_result
            result_str = json.dumps(result)
            
            # Send the tool result back as a user message with tool_result
            messages.append({
                "role": "user", 
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result_str  # Use string instead of dict
                    }
                ]
            })
        else:
            # No tool call, Claude is just responding with text
            if text_blocks:
                print(f"\n🤖 Claude says: {text_blocks[0].text}")
                messages.append({"role": "assistant", "content": text_blocks[0].text})
                print("\n✅ Proof completed!")
                return
    
    print("\n⚠️ Reached maximum iterations without completing the proof")

if __name__ == "__main__":
    # Example theorem
    theorem = "forall (p q : Prop), p -> q -> And p q"
    run_proof_agent(theorem)