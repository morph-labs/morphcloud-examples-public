# tasks.py
from typing import Dict, Any, List, Callable, Optional, Sequence
from dataclasses import dataclass, field
from eva import (
    Instance, VerificationResult, VerifiedTask, Agent, run, 
    MorphInstance, log, LogLevel
)


class PokemonVerifiedTask(VerifiedTask[Dict[str, Any], str, bool, Dict[str, Any]]):
    """A task for a Pokemon game goal verified by checking game state."""
    
    @staticmethod
    def create(
        instruction: str,
        snapshot_id: str,
        verification_function: Callable[[Dict[str, Any]], bool],
        verification_message: str,
        metadata: Optional[Dict[str, str]] = None
    ) -> 'PokemonVerifiedTask':
        """
        Create a Pokemon verified task.
        
        Args:
            instruction: The goal to accomplish in Pokemon
            snapshot_id: The MorphCloud snapshot ID to start from
            verification_function: Function that determines if the goal was achieved
            verification_message: Message explaining what constitutes success
            metadata: Optional metadata for the task
            
        Returns:
            A PokemonVerifiedTask instance
        """
        log(LogLevel.INFO, f"Creating Pokemon task: {instruction}", 
            extra={"snapshot_id": snapshot_id, "verification_message": verification_message})
        
        def pokemon_verifier(state: Instance[Dict[str, Any], Dict[str, Any]], 
                          actions: Sequence[str]) -> VerificationResult[bool]:
            log(LogLevel.INFO, f"Verifying Pokemon task", 
                extra={"task": instruction, "action_count": len(actions)})
            
            # Extract game state from the Instance
            game_state = state.state.get("game_state", {})
            log(LogLevel.INFO, f"Game state summary", 
                extra={"game_state": game_state, "action_count": len(actions)})
            
            # Check if the goal is achieved using the verification function
            try:
                success = verification_function(game_state)
                
                if success:
                    log(LogLevel.SUCCESS, f"Goal achieved", 
                        extra={"task": instruction, "actions_taken": len(actions)})
                    return VerificationResult(
                        value=True,
                        success=True,
                        message=f"Goal achieved: {instruction}",
                        details={
                            "actions_taken": len(actions)
                        }
                    )
                else:
                    log(LogLevel.INFO, f"Goal not yet achieved", 
                        extra={"task": instruction, "verification_message": verification_message})
                    return VerificationResult(
                        value=False,
                        success=False,
                        message=f"Goal not yet achieved: {instruction}",
                        details={
                            "verification_message": verification_message
                        }
                    )
            except Exception as e:
                log(LogLevel.ERROR, f"Error in verification", 
                    extra={"error": str(e), "task": instruction})
                return VerificationResult(
                    value=False,
                    success=False,
                    message=f"Verification error: {str(e)}",
                    details={"error": str(e)}
                )
            
        return PokemonVerifiedTask(
            instruction=instruction,
            snapshot_id=snapshot_id,
            verifier=pokemon_verifier,
            metadata=metadata or {}
        )


# ============= Verification Functions =============

def verify_player_names(game_state: Dict[str, Any]) -> bool:
    """Verify player name is 'CLAUDE' and rival name is 'WACLAUD'."""
    if isinstance(game_state, str):
        player_name = None
        rival_name = None
        for line in game_state.split('\n'):
            if line.startswith("Player:"):
                player_name = line.replace("Player:", "").strip()
            elif line.startswith("Rival:"):
                rival_name = line.replace("Rival:", "").strip()
        return (player_name == "CLAUDE" and rival_name == "WACLAUD")
    return False

def verify_left_mount_moon(game_state: Dict[str, Any]) -> bool:
    """Verify player has left Mount Moon and is on Route 4."""
    if isinstance(game_state, str):
        for line in game_state.split('\n'):
            if line.startswith("Location:"):
                location = line.replace("Location:", "").strip()
                return ("CERULEAN_CITY" in location)
    return False

def verify_beat_first_gym(game_state: Dict[str, Any]) -> bool:
    """Verify player has earned the Boulder Badge from Brock."""
    if isinstance(game_state, str):
        for line in game_state.split('\n'):
            if line.startswith("Badges:"):
                badges_str = line.replace("Badges:", "").strip()
                badges = [b.strip() for b in badges_str.split(',')]
                return "BOULDER" in badges
    return False

def verify_beat_second_gym(game_state: Dict[str, Any]) -> bool:
    """Verify player has earned the Cascade Badge from Misty."""
    if isinstance(game_state, str):
        for line in game_state.split('\n'):
            if line.startswith("Badges:"):
                badges_str = line.replace("Badges:", "").strip()
                badges = [b.strip() for b in badges_str.split(',')]
                return "CASCADE" in badges
    return False

def verify_reach_cerulean(game_state: Dict[str, Any]) -> bool:
    """Verify player has reached Cerulean City."""
    if isinstance(game_state, str):
        for line in game_state.split('\n'):
            if line.startswith("Location:"):
                location = line.replace("Location:", "").strip()
                return "CERULEAN" in location
    return False

# Store verification functions in a registry for lookup by name
VERIFICATION_FUNCTIONS = {
    "verify_player_names": verify_player_names,
    "verify_escape_mount_moon": verify_left_mount_moon,
    "verify_beat_first_gym": verify_beat_first_gym,
    "verify_beat_second_gym": verify_beat_second_gym,
    "verify_reach_cerulean": verify_reach_cerulean,
}

# ============= Task Definition =============

@dataclass
class TaskDefinition:
    """Definition of a Pokemon task with verification details."""
    id: str  # Unique identifier for the task
    instruction: str  # Human-readable instruction
    verification_fn_name: str  # Name of verification function
    verification_message: str  # Message to show if verification fails
    snapshot_id: str = ""  # Starting snapshot ID (can be set at runtime)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def get_verification_function(self) -> Callable[[Dict[str, Any]], bool]:
        """Get the verification function for this task."""
        if self.verification_fn_name not in VERIFICATION_FUNCTIONS:
            raise ValueError(f"Unknown verification function: {self.verification_fn_name}")
        return VERIFICATION_FUNCTIONS[self.verification_fn_name]

# ============= Task Registry =============

# Define all available tasks
REGISTERED_TASKS = [
    TaskDefinition(
        id="escape-mt-moon",
        instruction="Navigate through Mount Moon and exit to Route 4",
        verification_fn_name="verify_escape_mount_moon",
        verification_message="Reach Route 4 after leaving Mt. Moon.",
        metadata={"game": "Pokemon Red", "objective": "mount_moon"},
    ),
    TaskDefinition(
        id="beat-brock",
        instruction="Defeat Brock at Pewter Gym and obtain the Boulder Badge",
        verification_fn_name="verify_beat_first_gym",
        verification_message="Defeat Brock to acquire the Boulder Badge.",
        metadata={"game": "Pokemon Red", "objective": "first_gym"},
    ),
    TaskDefinition(
        id="check-player-names",
        instruction="Have the player's name set to CLAUDE and the rival's to WACLAUD",
        verification_fn_name="verify_player_names",
        verification_message="Player name must be 'CLAUDE' and rival name 'WACLAUD'.",
        metadata={"game": "Pokemon Red", "objective": "naming"},
    ),
    TaskDefinition(
        id="reach-cerulean",
        instruction="Travel to Cerulean City",
        verification_fn_name="verify_reach_cerulean",
        verification_message="Reach Cerulean City.",
        metadata={"game": "Pokemon Red", "objective": "navigation"},
    ),
    TaskDefinition(
        id="beat-misty",
        instruction="Defeat Misty at Cerulean Gym and obtain the Cascade Badge",
        verification_fn_name="verify_beat_second_gym",
        verification_message="Defeat Misty to acquire the Cascade Badge.",
        metadata={"game": "Pokemon Red", "objective": "second_gym"},
    ),
]

# ============= Helper Functions =============

def get_task_by_id(task_id: str) -> Optional[TaskDefinition]:
    """Get a task definition by its ID."""
    for task in REGISTERED_TASKS:
        if task.id == task_id:
            return task
    return None

def create_pokemon_verified_task(task_id: str, snapshot_id: str = None):
    """
    Create a PokemonVerifiedTask instance for the given task ID.
    
    Example usage:
    ```
    from pokemon_eva_agent import PokemonVerifiedTask
    from tasks import create_pokemon_verified_task
    
    # Create task
    task = create_pokemon_verified_task("beat-brock", "snap_12345")
    
    # Run task with agent
    from eva import run
    result, _ = await run(task=task, agent=agent, max_steps=100)
    ```
    """
    # This function needs to be used where PokemonVerifiedTask is available
    # It's defined here but meant to be imported and used with the agent module
    task_def = get_task_by_id(task_id)
    if not task_def:
        raise ValueError(f"Unknown task ID: {task_id}")
    
    # Set snapshot ID if provided
    if snapshot_id:
        task_def.snapshot_id = snapshot_id
    
    # Import dynamically to avoid circular imports
    # This assumes this is called in a context where PokemonVerifiedTask is available
    
    return PokemonVerifiedTask.create(
        instruction=task_def.instruction,
        snapshot_id=task_def.snapshot_id,
        verification_function=task_def.get_verification_function(),
        verification_message=task_def.verification_message,
        metadata=task_def.metadata
    )
