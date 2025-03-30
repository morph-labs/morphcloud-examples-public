"""
E.V.A. - Executions with Verified Agents

A minimal yet expressive framework for verification-centered task execution 
integrated with MorphCloud for virtual machine instance provisioning.

Copyright 2025 Morph Labs, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
from __future__ import annotations

import logging
import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Generic, List, Optional, Sequence, TypeVar, Union, Tuple

# Import MorphCloud API
from morphcloud.api import MorphCloudClient, Instance, Snapshot

# Configure colorful logging
import colorlog

# Global MorphCloud client
morph_client = MorphCloudClient(
    api_key=os.environ.get("MORPH_API_KEY"),
    base_url=os.environ.get("MORPH_BASE_URL")
)

# Type variables for generic components
S = TypeVar('S')  # State type
A = TypeVar('A')  # Action type
R = TypeVar('R')  # Verification result type
T = TypeVar('T')  # Snapshot type

# Setup logging with colors
class LogLevel(Enum):
    INFO = 'info'
    SUCCESS = 'success'
    WARNING = 'warning'
    ERROR = 'error'
    DEBUG = 'debug'

# Configure the color logger
handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    '%(log_color)s[%(levelname)s] %(message)s',
    log_colors={
        'DEBUG': 'cyan',
        'INFO': 'green',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'red,bg_white',
        'SUCCESS': 'bold_green',
    },
    secondary_log_colors={
        'message': {
            'DEBUG': 'cyan',
            'INFO': 'white',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'red',
            'SUCCESS': 'green',
        }
    }
))

logger = colorlog.getLogger('eva')
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Add a custom success level
logging.SUCCESS = 25  # Between INFO and WARNING
logging.addLevelName(logging.SUCCESS, 'SUCCESS')

def success(self, message, *args, **kwargs):
    if self.isEnabledFor(logging.SUCCESS):
        self.log(logging.SUCCESS, message, *args, **kwargs)

logging.Logger.success = success

def log(level: Union[LogLevel, str], message: str, *args, **kwargs):
    """Unified logging function with color support."""
    if isinstance(level, str):
        level = LogLevel(level)
    
    if level == LogLevel.INFO:
        logger.info(message, *args, **kwargs)
    elif level == LogLevel.SUCCESS:
        logger.success(message, *args, **kwargs)
    elif level == LogLevel.WARNING:
        logger.warning(message, *args, **kwargs)
    elif level == LogLevel.ERROR:
        logger.error(message, *args, **kwargs)
    elif level == LogLevel.DEBUG:
        logger.debug(message, *args, **kwargs)


@dataclass(frozen=True)
class Instance(Generic[S, T]):
    """An immutable snapshot of state."""
    state: S
    
    @abstractmethod
    def snapshot(self) -> T:
        """
        Create a serializable snapshot of the current state.
        
        This snapshot will be used for visualization and debugging purposes.
        """
        pass


@dataclass(frozen=True)
class VerificationResult(Generic[R]):
    """The result of verifying a task."""
    value: R
    success: bool
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    
    def log(self):
        """Log the verification result with appropriate color."""
        if self.success:
            log(LogLevel.SUCCESS, f"✓ Verification succeeded: {self.message}")
            if self.details:
                log(LogLevel.DEBUG, f"  Details: {self.details}")
        else:
            log(LogLevel.ERROR, f"✗ Verification failed: {self.message}")
            if self.details:
                log(LogLevel.DEBUG, f"  Details: {self.details}")


@dataclass(frozen=True)
class VerifiedTask(Generic[S, A, R, T]):
    """
    A task with verification criteria.
    
    Attributes:
        instruction: What needs to be done
        snapshot_id: ID of the MorphCloud snapshot to start from
        verifier: Function that checks if the task was completed successfully
    """
    instruction: str
    snapshot_id: str
    verifier: Callable[[Instance[S, T], Sequence[A]], VerificationResult[R]]
    metadata: Dict[str, str] = field(default_factory=dict)
    
    def __post_init__(self):
        log(LogLevel.INFO, f"Created task: {self.instruction}")
        log(LogLevel.INFO, f"Using snapshot: {self.snapshot_id}")
    
    def verify(self, final_state: Instance[S, T], actions: Sequence[A]) -> VerificationResult[R]:
        """Verify if the task was completed correctly."""
        log(LogLevel.INFO, f"Verifying task: {self.instruction}")
        log(LogLevel.DEBUG, f"  Actions: {actions}")
        
        result = self.verifier(final_state, actions)
        result.log()
        return result


@dataclass
class TrajectoryStep(Generic[S, A, R, T]):
    """A single step in a trajectory."""
    state: Instance[S, T]
    snapshot: T  # Every step has a snapshot for visualization
    action: Optional[A] = None  # None for initial state
    result: Optional[VerificationResult[R]] = None  # Result if verification was performed
    timestamp: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        action_str = f" -> {self.action}" if self.action else " (initial)"
        log(LogLevel.DEBUG, f"Trajectory step{action_str}")


@dataclass
class Trajectory(Generic[S, A, R, T]):
    """A record of states, actions, and verification results."""
    steps: List[TrajectoryStep[S, A, R, T]] = field(default_factory=list)
    
    def add_step(self, state: Instance[S, T], 
                 action: Optional[A] = None,
                 result: Optional[VerificationResult[R]] = None) -> None:
        """Add a step to the trajectory."""
        snapshot = state.snapshot()  # Always create a snapshot
        step = TrajectoryStep(state, snapshot, action, result)
        self.steps.append(step)
        
        if len(self.steps) == 1:
            log(LogLevel.INFO, "Started new trajectory")
        else:
            action_str = f"{action}" if action else "None"
            log(LogLevel.INFO, f"Step {len(self.steps)-1}: Action={action_str}")
    
    @property
    def current_state(self) -> Optional[Instance[S, T]]:
        """Get the current state, if any."""
        if not self.steps:
            return None
        return self.steps[-1].state
    
    @property
    def actions(self) -> List[A]:
        """Get all actions taken."""
        return [step.action for step in self.steps if step.action is not None]
    
    @property
    def final_result(self) -> Optional[VerificationResult[R]]:
        """Get the final verification result, if any."""
        for step in reversed(self.steps):
            if step.result is not None:
                return step.result
        return None
    
    @property
    def snapshots(self) -> List[T]:
        """Get all snapshots for visualization."""
        return [step.snapshot for step in self.steps]
    
    def summarize(self):
        """Log a summary of the trajectory."""
        log(LogLevel.INFO, f"Trajectory summary: {len(self.steps)} steps")
        
        if self.final_result:
            if self.final_result.success:
                log(LogLevel.SUCCESS, f"Final result: Success - {self.final_result.message}")
            else:
                log(LogLevel.ERROR, f"Final result: Failure - {self.final_result.message}")
        else:
            log(LogLevel.WARNING, "No final verification result")


class Agent(ABC, Generic[S, A, R, T]):
    """
    An agent that executes a verified task.
    """
    
    def __init__(self):
        self.trajectory = None
        log(LogLevel.INFO, f"Initializing agent")

    def set_objective(self, objective: str) -> None:
        """
        Optional method to inform the agent of its current objective.
        
        Args:
            objective: The instruction or goal for the agent to accomplish
            
        Note:
            This method has a no-op default implementation.
            Agent subclasses can override it to make use of objective information.
        """
        # Default implementation does nothing
        pass
    
    @abstractmethod
    async def run_step(self, state: Instance[S, T]) -> A:
        """
        Execute a single step based on the current state.
        
        This method must be implemented by concrete agent classes.
        """
        pass
    
    @abstractmethod
    async def apply_action(self, state: S, action: A) -> S:
        """
        Apply an action to a state to produce a new state.
        
        This method must be implemented by concrete agent classes.
        """
        pass
    
    @abstractmethod
    async def initialize_state(self, morph_instance: 'MorphInstance') -> Instance[S, T]:
        """
        Initialize the state from a MorphCloud instance.
        
        This method must be implemented by concrete agent classes.
        """
        pass


async def run(task: VerifiedTask[S, A, R, T], agent: Agent[S, A, R, T], max_steps: int = 100, 
        verify_every_step: bool = False, ttl_seconds: Optional[int] = None) -> Tuple[VerificationResult[R], Trajectory[S, A, R, T]]:
    """
    Run an agent on a task until the task is complete or max_steps is reached.
    """
    log(LogLevel.INFO, f"Running agent for task: {task.instruction}")
    log(LogLevel.INFO, f"Max steps: {max_steps}, verify_every_step: {verify_every_step}")

    agent.set_objective(task.instruction)

    # Start a Morph instance from the task's snapshot
    log(LogLevel.INFO, f"Starting Morph instance from snapshot: {task.snapshot_id}")
    morph_instance = MorphInstance(task.snapshot_id, task.metadata, ttl_seconds)
    
    try:
        # Initialize the agent's state and trajectory
        initial_state = await agent.initialize_state(morph_instance)
        
        # Set morph_instance reference
        if hasattr(initial_state.state, '_morph_instance'):
            object.__setattr__(initial_state.state, '_morph_instance', morph_instance)
        
        trajectory = Trajectory[S, A, R, T]()
        agent.trajectory = trajectory
        
        # Bind the agent to the instance
        if hasattr(agent, 'bind_instance'):
            agent.bind_instance(morph_instance)
        
        # Initialize with the initial state
        trajectory.add_step(initial_state)
        
        current_state = trajectory.current_state
        if current_state is None:
            error_msg = "No initial state available"
            log(LogLevel.ERROR, error_msg)
            raise ValueError(error_msg)
        
        for step_num in range(max_steps):
            log(LogLevel.INFO, f"Step {step_num+1}/{max_steps}")
            
            # Execute a step - now with await
            log(LogLevel.INFO, "Determining next action...")
            action = await agent.run_step(current_state)
            log(LogLevel.INFO, f"Selected action: {action}")
            
            # Apply the action to get a new state - now with await
            log(LogLevel.INFO, f"Applying action: {action}")
            new_state_value = await agent.apply_action(current_state.state, action)
            new_state = current_state.__class__(new_state_value)
            
            # Ensure morph_instance reference is preserved
            if hasattr(new_state.state, '_morph_instance'):
                object.__setattr__(new_state.state, '_morph_instance', morph_instance)
            
            # Record the step
            trajectory.add_step(new_state, action)
            
            # Update current state
            current_state = new_state
            
            # Check if we should verify
            if verify_every_step or step_num == max_steps - 1:
                log(LogLevel.INFO, "Verifying current state...")
                result = task.verify(current_state, trajectory.actions)
                trajectory.steps[-1].result = result
                
                if result.success:
                    log(LogLevel.SUCCESS, f"Task completed successfully after {step_num+1} steps")
                    trajectory.summarize()
                    return result, trajectory
        
        # If we reached max steps without success:
        log(LogLevel.WARNING, f"Reached maximum steps ({max_steps}) without success")
        
        if trajectory.final_result is not None:
            trajectory.summarize()
            return trajectory.final_result, trajectory
        
        result = VerificationResult(
            value=None,
            success=False,
            message=f"Failed to complete task within {max_steps} steps",
            details={"last_state": current_state.state}
        )
        result.log()
        trajectory.summarize()
        return result, trajectory
        
    finally:
        # Always clean up the Morph instance
        morph_instance.stop()



async def run_step(task: VerifiedTask[S, A, R, T], agent: Agent[S, A, R, T], 
             trajectory: Trajectory[S, A, R, T], verify: bool = False) -> Tuple[Instance[S, T], Optional[VerificationResult[R]]]:
    """
    Run a single step of an agent on a task.
    """
    if not trajectory.steps:
        raise ValueError("Trajectory is empty. Initialize it with an initial state first.")
    
    current_state = trajectory.current_state
    
    # Execute a step - now with await
    log(LogLevel.INFO, "Determining next action...")
    action = await agent.run_step(current_state)
    log(LogLevel.INFO, f"Selected action: {action}")
    
    # Apply the action to get a new state - now with await
    log(LogLevel.INFO, f"Applying action: {action}")
    new_state_value = await agent.apply_action(current_state.state, action)
    new_state = current_state.__class__(new_state_value)
    
    # Record the step
    trajectory.add_step(new_state, action)
    
    # Verify if requested
    result = None
    if verify:
        log(LogLevel.INFO, "Verifying current state...")
        result = task.verify(new_state, trajectory.actions)
        trajectory.steps[-1].result = result
    
    return new_state, result

# --- Composition Utilities ---


def sequential_tasks(tasks: Sequence[VerifiedTask[S, A, R, T]], 
                     name: str = "Sequential Tasks",
                     metadata: Optional[Dict[str, str]] = None) -> VerifiedTask[S, A, List[R], T]:
    """
    Combine multiple tasks into a sequence.

The resulting task is successful only if all constituent tasks are successful.
    """
    
    if not tasks:
        error_msg = "Cannot create sequential tasks from empty sequence"
        log(LogLevel.ERROR, error_msg)
        raise ValueError(error_msg)

    

    log(LogLevel.INFO, f"Creating sequential task '{name}' with {len(tasks)} subtasks")

    # Use the snapshot_id from the first task

    snapshot_id = tasks[0].snapshot_id
    log(LogLevel.DEBUG, f"Using snapshot_id from first task: {snapshot_id}")
    

    def sequential_verifier(state: Instance[S, T], 
                           actions: Sequence[A]) -> VerificationResult[List[R]]:
        log(LogLevel.INFO, f"Verifying sequential task '{name}'")
        

        results = []
        success = True
        messages = []

        for i, task in enumerate(tasks):
            log(LogLevel.INFO, f"Verifying subtask {i+1}/{len(tasks)}: {task.instruction}")
            result = task.verify(state, actions)
            results.append(result.value)


            if result.success:
                log(LogLevel.SUCCESS, f"Subtask {i+1} succeeded")

            else:
                log(LogLevel.ERROR, f"Subtask {i+1} failed: {result.message}")
                success = False
                messages.append(result.message)

        

        if success:
            log(LogLevel.SUCCESS, "All subtasks completed successfully")
            message = "All tasks completed successfully"

        else:
            log(LogLevel.ERROR, f"Some subtasks failed: {messages}")
            message = f"Failed tasks: {'; '.join(messages)}"

        

        return VerificationResult(
            value=results,
            success=success,
            message=message,
            details={"task_count": len(tasks)}

        )

    

    return VerifiedTask(
        instruction=name,
        snapshot_id=snapshot_id,
        verifier=sequential_verifier,
        metadata=metadata or {}

    )





def any_of_tasks(tasks: Sequence[VerifiedTask[S, A, R, T]], 

                name: str = "Any Task",

                metadata: Optional[Dict[str, str]] = None) -> VerifiedTask[S, A, R, T]:

    """

    Combine multiple tasks where success of any constitutes overall success.

    

    The resulting task is successful if any constituent task is successful.

    """

    if not tasks:
        error_msg = "Cannot create any_of tasks from empty sequence"
        log(LogLevel.ERROR, error_msg)
        raise ValueError(error_msg)

    

    log(LogLevel.INFO, f"Creating any-of task '{name}' with {len(tasks)} subtasks")

    # Use the snapshot_id from the first task

    snapshot_id = tasks[0].snapshot_id
    log(LogLevel.DEBUG, f"Using snapshot_id from first task: {snapshot_id}")

    

    def any_verifier(state: Instance[S, T], 
                    actions: Sequence[A]) -> VerificationResult[R]:
        log(LogLevel.INFO, f"Verifying any-of task '{name}'")

        

        for i, task in enumerate(tasks):
            log(LogLevel.INFO, f"Verifying subtask {i+1}/{len(tasks)}: {task.instruction}")
            result = task.verify(state, actions)


            if result.success:
                log(LogLevel.SUCCESS, f"Subtask {i+1} succeeded, overall task successful")
                return result

            else:
                log(LogLevel.WARNING, f"Subtask {i+1} failed, trying next subtask")

        

        # If we get here, no task succeeded

        log(LogLevel.ERROR, "All subtasks failed, overall task failed")

        return VerificationResult(
            value=None,
            success=False,
            message="None of the tasks completed successfully",
            details={"task_count": len(tasks)}
        )

    

    return VerifiedTask(
        instruction=name,
        snapshot_id=snapshot_id,
        verifier=any_verifier,
        metadata=metadata or {}

    )

# --- Example Implementations with MorphCloud ---

# MorphCloud Instance wrapper
class MorphInstance:
    """A wrapper for a MorphCloud instance that handles startup and cleanup."""
    
    def __init__(self, snapshot_id: str, metadata: Optional[Dict[str, str]] = None, ttl_seconds: Optional[int] = None):
        """
        Create a new MorphCloud instance from a snapshot.
        
        Args:
            snapshot_id: The ID of the snapshot to start from
            metadata: Optional metadata for the instance
            ttl_seconds: Optional time-to-live in seconds
        """
        self.snapshot_id = snapshot_id
        self.metadata = metadata or {}
        self.instance = None
        
        log(LogLevel.INFO, f"Creating MorphCloud instance from snapshot {snapshot_id}")
        self.instance = morph_client.instances.start(
            snapshot_id=snapshot_id,
            metadata=metadata,
            ttl_seconds=ttl_seconds,
            ttl_action="stop"
        )
        
        log(LogLevel.INFO, f"Waiting for instance {self.instance.id} to be ready...")
        log(LogLevel.SUCCESS, f"Instance {self.instance.id} is ready")
    
    def exec(self, command: str) -> Dict[str, Any]:
        """Execute a command on the instance and return the result."""
        if not self.instance:
            raise ValueError("Instance is not running")
        
        log(LogLevel.INFO, f"Executing command: {command}")
        result = self.instance.exec(command)
        
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    
    def stop(self) -> None:
        """Stop the instance if it's running."""
        if self.instance:
            log(LogLevel.INFO, f"Stopping instance {self.instance.id}")
            self.instance.stop()
            self.instance = None
            log(LogLevel.SUCCESS, "Instance stopped")
    
    def __del__(self) -> None:
        """Ensure the instance is stopped when this object is garbage collected."""
        self.stop()


@dataclass(frozen=True)
class BashState:
    """State for bash command execution."""
    env: Dict[str, str] = field(default_factory=dict)
    cwd: str = "/"
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    _morph_instance: Optional[Any] = None  # Reference to the MorphInstance for verification


@dataclass(frozen=True)
class BashInstance(Instance[BashState, Dict[str, Any]]):
    """Bash-specific instance implementation."""
    
    def snapshot(self) -> Dict[str, Any]:
        """Create a serializable snapshot of the bash state."""
        return {
            "env": dict(self.state.env),
            "cwd": self.state.cwd,
            "stdout": self.state.stdout,
            "stderr": self.state.stderr,
            "exit_code": self.state.exit_code,
            "timestamp": str(datetime.now()),  # For visualization timeline
        }


class BashVerifiedTask(VerifiedTask[BashState, str, int, Dict[str, Any]]):
    """
    A task verified by running a separate verification bash command and checking its exit code.
    The verification command is distinct from the commands executed during the task.
    """
    
    @staticmethod
    def create(instruction: str,
               snapshot_id: str,
               verification_command: str,
               expected_exit_code: int = 0,
               metadata: Optional[Dict[str, str]] = None) -> BashVerifiedTask:
        """
        Create a bash verified task.
        
        Args:
            instruction: The instruction for what to accomplish
            snapshot_id: The MorphCloud snapshot ID to start from
            verification_command: The command to run to verify the task's success
            expected_exit_code: The exit code that indicates success
            metadata: Optional metadata for the task and MorphCloud instance
            
        Returns:
            A BashVerifiedTask instance
        """
        log(LogLevel.INFO, f"Creating bash task: {instruction}")
        log(LogLevel.DEBUG, f"  Snapshot ID: {snapshot_id}")
        log(LogLevel.DEBUG, f"  Verification command: {verification_command}")
        log(LogLevel.DEBUG, f"  Expected exit code: {expected_exit_code}")
        
        def bash_verifier(state: Instance[BashState, Dict[str, Any]], 
                          actions: Sequence[str]) -> VerificationResult[int]:
            log(LogLevel.INFO, f"Verifying bash task using command: {verification_command}")
            
            # We need to run the verification command on the current MorphCloud instance
            # This is different from the commands that were executed during the task
            try:
                # This will be provided by the run() function context
                morph_instance = state.state._morph_instance
                
                # Execute the verification command
                log(LogLevel.INFO, f"Running verification command: {verification_command}")
                result = morph_instance.exec(verification_command)
                
                exit_code = result["exit_code"]
                success = exit_code == expected_exit_code
                
                if success:
                    log(LogLevel.SUCCESS, f"Verification succeeded with exit code {exit_code}")
                else:
                    log(LogLevel.ERROR, f"Verification failed with exit code {exit_code}")
                
                return VerificationResult(
                    value=exit_code,
                    success=success,
                    message=f"Verification {'succeeded' if success else 'failed'} with exit code {exit_code}",
                    details={
                        "stdout": result["stdout"],
                        "stderr": result["stderr"],
                        "verification_command": verification_command,
                        "actions": actions
                    }
                )
            except AttributeError:
                log(LogLevel.ERROR, "MorphCloud instance not available for verification")
                return VerificationResult(
                    value=None,
                    success=False,
                    message="Unable to run verification command: MorphCloud instance not available",
                    details={"verification_command": verification_command}
                )
            except Exception as e:
                log(LogLevel.ERROR, f"Error running verification command: {str(e)}")
                return VerificationResult(
                    value=None,
                    success=False,
                    message=f"Error running verification command: {str(e)}",
                    details={"verification_command": verification_command}
                )
            
        return BashVerifiedTask(
            instruction=instruction,
            snapshot_id=snapshot_id,
            verifier=bash_verifier,
            metadata=metadata or {},
        )


class BashAgent(Agent[BashState, str, int, Dict[str, Any]]):
    """An agent that executes bash commands using MorphCloud instances."""
    
    def __init__(self):
        super().__init__()
        log(LogLevel.INFO, "Initializing BashAgent")
    
    async def initialize_state(self, morph_instance: MorphInstance) -> BashInstance:
        """Initialize the state from a MorphCloud instance."""
        initial_state = BashState(
            env={},  # We could get this from the instance but we'll start empty
            cwd="/",
            stdout="",
            stderr="",
            exit_code=None
        )
        return BashInstance(initial_state)
    
    async def run_step(self, state: Instance[BashState, Dict[str, Any]]) -> str:
        """
        Determine the next bash command to execute.
        """
        log(LogLevel.INFO, "BashAgent determining next command")
        return "echo 'Hello, world!'"
    
    async def apply_action(self, state: BashState, action: str) -> BashState:
        """
        Execute a bash command on the MorphCloud instance and return the new state.
        """
        log(LogLevel.INFO, f"Executing bash command: {action}")
        
        # Execute the command on the instance
        try:
            result = self._morph_instance.exec(action)
            
            # Update the state with the result
            log(LogLevel.SUCCESS, f"Command executed with exit code {result['exit_code']}")
            return BashState(
                env=state.env.copy(),
                cwd=state.cwd,
                stdout=result["stdout"],
                stderr=result["stderr"],
                exit_code=result["exit_code"]
            )
        except Exception as e:
            log(LogLevel.ERROR, f"Command execution failed: {str(e)}")
            return BashState(
                env=state.env.copy(),
                cwd=state.cwd,
                stdout="",
                stderr=f"Execution error: {str(e)}\n",
                exit_code=1
            )
    
    def bind_instance(self, morph_instance: MorphInstance) -> None:
        """Bind a MorphCloud instance to this agent for command execution."""
        self._morph_instance = morph_instance


# Entry point for running examples
if __name__ == "__main__":
    # Examples to run
    import asyncio
    
    # Uncomment one of these to run the example
    # asyncio.run(example_usage())
