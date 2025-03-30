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
import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Generic, List, Optional, Sequence, TypeVar, Union, Tuple 

# Import MorphCloud API
from morphcloud.api import MorphCloudClient, Instance, Snapshot

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

# Setup logging with JSON formatting
class LogLevel(Enum):
    INFO = 'info'
    SUCCESS = 'success'
    WARNING = 'warning'
    ERROR = 'error'
    DEBUG = 'debug'

# Define built-in log record attributes to filter from custom fields
LOG_RECORD_BUILTIN_ATTRS = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "module", "msecs",
    "message", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
}

class JSONLFormatter(logging.Formatter):
    """JSONL formatter for structured logging."""
    
    def __init__(self, fmt_keys=None):
        super().__init__()
        self.fmt_keys = fmt_keys if fmt_keys is not None else {
            "timestamp": "created",
            "level": "levelname",
            "logger": "name",
            "message": "message"
        }
    
    def format(self, record: logging.LogRecord) -> str:
        message = self._prepare_log_dict(record)
        return json.dumps(message, default=str)
    
    def _prepare_log_dict(self, record: logging.LogRecord) -> dict:
        always_fields = {
            "message": record.getMessage(),
            "timestamp": dt.datetime.fromtimestamp(
                record.created, tz=dt.timezone.utc
            ).isoformat(),
        }
        
        if record.exc_info is not None:
            always_fields["exc_info"] = self.formatException(record.exc_info)
        
        if record.stack_info is not None:
            always_fields["stack_info"] = self.formatStack(record.stack_info)
        
        message = {
            key: always_fields.pop(val, None) if val in always_fields else getattr(record, val)
            for key, val in self.fmt_keys.items()
        }
        
        message.update(always_fields)
        
        # Add any custom attributes
        for key, val in record.__dict__.items():
            if key not in LOG_RECORD_BUILTIN_ATTRS:
                message[key] = val
        
        return message

# Configure logging with both file and console output
logger = logging.getLogger('eva')
# Remove any existing handlers
for handler in logger.handlers[:]:
    logger.removeHandler(handler)

# Add a custom success level
logging.SUCCESS = 25  # Between INFO and WARNING
logging.addLevelName(logging.SUCCESS, 'SUCCESS')

# Add success method to Logger class
def success(self, message, *args, **kwargs):
    if self.isEnabledFor(logging.SUCCESS):
        self.log(logging.SUCCESS, message, *args, **kwargs)

logging.Logger.success = success

# Create a readable console formatter
class ColoredConsoleFormatter(logging.Formatter):
    """Formatter for console with optional color support"""
    
    COLORS = {
        'DEBUG': '\033[94m',  # Blue
        'INFO': '\033[92m',   # Green
        'SUCCESS': '\033[96m', # Cyan
        'WARNING': '\033[93m', # Yellow
        'ERROR': '\033[91m',   # Red
        'CRITICAL': '\033[91m\033[1m', # Bold Red
        'RESET': '\033[0m'    # Reset
    }
    
    def __init__(self, use_colors=True, fmt=None):
        super().__init__(fmt or '%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.use_colors = use_colors
    
    def format(self, record):
        log_message = super().format(record)
        if self.use_colors and record.levelname in self.COLORS:
            log_message = f"{self.COLORS[record.levelname]}{log_message}{self.COLORS['RESET']}"
        return log_message

# File path for JSONL logs
log_directory = os.environ.get("EVA_LOG_DIR", "logs")
os.makedirs(log_directory, exist_ok=True)
log_filename = os.path.join(log_directory, f"eva_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl")

# Create the file handler with JSON formatting
file_handler = logging.FileHandler(log_filename)
file_handler.setFormatter(JSONLFormatter())

# Create the console handler with readable formatting
console_handler = logging.StreamHandler()
console_handler.setFormatter(ColoredConsoleFormatter(use_colors=True))

# Add both handlers to the logger
logger.addHandler(file_handler)
logger.addHandler(console_handler)
logger.setLevel(logging.INFO)

# Update the log function to handle the dual logging
def log(level: Union[LogLevel, str], message: str, *args, **kwargs):
    """Unified logging function that logs to both file (JSON) and console (readable)."""
    if isinstance(level, str):
        level = LogLevel(level)
    
    # Extract any extra key-value pairs for the JSON log
    extra = kwargs.pop('extra', {})
    
    if level == LogLevel.INFO:
        logger.info(message, *args, extra=extra, **kwargs)
    elif level == LogLevel.SUCCESS:
        logger.success(message, *args, extra=extra, **kwargs)
    elif level == LogLevel.WARNING:
        logger.warning(message, *args, extra=extra, **kwargs)
    elif level == LogLevel.ERROR:
        logger.error(message, *args, extra=extra, **kwargs)
    elif level == LogLevel.DEBUG:
        logger.debug(message, *args, extra=extra, **kwargs)


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
        """Log the verification result with appropriate level."""
        if self.success:
            log(LogLevel.SUCCESS, f"Verification succeeded: {self.message}", 
                extra={"result_type": "verification", "details": self.details})
        else:
            log(LogLevel.ERROR, f"Verification failed: {self.message}", 
                extra={"result_type": "verification", "details": self.details})


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
        log(LogLevel.INFO, f"Created task: {self.instruction}", 
            extra={"task_id": self.snapshot_id, "metadata": self.metadata})
    
    def verify(self, final_state: Instance[S, T], actions: Sequence[A]) -> VerificationResult[R]:
        """Verify if the task was completed correctly."""
        log(LogLevel.INFO, f"Verifying task: {self.instruction}", 
            extra={"action_count": len(actions)})
        
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
        log(LogLevel.DEBUG, f"Trajectory step{action_str}", 
            extra={"step_type": "initial" if self.action is None else "action"})


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
            log(LogLevel.INFO, "Started new trajectory", extra={"step_index": 0})
        else:
            action_str = f"{action}" if action else "None"
            log(LogLevel.INFO, f"Step {len(self.steps)-1}: Action={action_str}", 
                extra={"step_index": len(self.steps)-1, "action": action_str})
    
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
        log(LogLevel.INFO, f"Trajectory summary", 
            extra={"step_count": len(self.steps), "has_result": self.final_result is not None})
        
        if self.final_result:
            if self.final_result.success:
                log(LogLevel.SUCCESS, f"Final result: Success - {self.final_result.message}",
                    extra={"result_details": self.final_result.details})
            else:
                log(LogLevel.ERROR, f"Final result: Failure - {self.final_result.message}",
                    extra={"result_details": self.final_result.details})
        else:
            log(LogLevel.WARNING, "No final verification result")


class Agent(ABC, Generic[S, A, R, T]):
    """
    An agent that executes a verified task.
    """
    
    def __init__(self):
        self.trajectory = None
        log(LogLevel.INFO, f"Initializing agent", extra={"agent_type": self.__class__.__name__})

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
    log(LogLevel.INFO, f"Running agent for task", 
        extra={"task": task.instruction, "max_steps": max_steps, "verify_every_step": verify_every_step})

    agent.set_objective(task.instruction)

    # Start a Morph instance from the task's snapshot
    log(LogLevel.INFO, f"Starting Morph instance", 
        extra={"snapshot_id": task.snapshot_id})
    morph_instance = MorphInstance(task.snapshot_id, task.metadata, ttl_seconds)
    
    try:
        # Initialize the agent's state and trajectory
        initial_state = await agent.initialize_state(morph_instance)
        
        # Set morph_instance reference
        if hasattr(initial_state.state, '_morph_instance'):
            object.__setattr__(initial_state.state, '_morph_instance', morph_instance)
        
        if hasattr(agent, 'trajectory') and agent.trajectory is not None:
            trajectory = agent.trajectory
        else:
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
            log(LogLevel.INFO, f"Starting step execution", 
                extra={"step_num": step_num+1, "max_steps": max_steps})
            
            # Execute a step - now with await
            log(LogLevel.INFO, "Determining next action...")
            action = await agent.run_step(current_state)
            log(LogLevel.INFO, f"Selected action", extra={"action": str(action)})
            
            # Apply the action to get a new state - now with await
            log(LogLevel.INFO, f"Applying action", extra={"action": str(action)})
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
                    log(LogLevel.SUCCESS, f"Task completed successfully", 
                        extra={"steps_taken": step_num+1})
                    trajectory.summarize()
                    return result, trajectory
        
        # If we reached max steps without success:
        log(LogLevel.WARNING, f"Reached maximum steps without success", 
            extra={"max_steps": max_steps})
        
        if trajectory.final_result is not None:
            trajectory.summarize()
            return trajectory.final_result, trajectory
        
        result = VerificationResult(
            value=None,
            success=False,
            message=f"Failed to complete task within {max_steps} steps",
            details={"last_state": str(current_state.state)}
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
    
    def create_snapshot(self) -> str:
        """
        Create a snapshot of the current instance state.
        
        Returns:
            str: The ID of the created snapshot
        """
        if not self.instance:
            raise ValueError("Instance is not running")
        
        log(LogLevel.INFO, f"Creating snapshot from instance {self.instance.id}")
        
        try:
            # Create the snapshot without parameters
            snapshot = self.instance.snapshot()
            
            snapshot_id = snapshot.id
            log(LogLevel.SUCCESS, f"Created snapshot", 
                extra={"snapshot_id": snapshot_id, "instance_id": self.instance.id})
            
            return snapshot_id
        except Exception as e:
            log(LogLevel.ERROR, f"Failed to create snapshot", 
                extra={"error": str(e), "instance_id": self.instance.id})
            import traceback
            log(LogLevel.ERROR, f"Snapshot error traceback", 
                extra={"traceback": traceback.format_exc()})
            raise
    
    def set_snapshot_metadata(self, snapshot_id: str, metadata: Dict[str, str]) -> None:
        """
        Set metadata on a snapshot.
        
        Args:
            snapshot_id: The ID of the snapshot to update
            metadata: Metadata to set on the snapshot
        """
        if not metadata:
            log(LogLevel.WARNING, f"No metadata provided for snapshot {snapshot_id}")
            return
            
        log(LogLevel.INFO, f"Setting metadata on snapshot {snapshot_id}", 
            extra={"metadata_keys": list(metadata.keys())})
            
        try:
            # Get the snapshot and set the metadata
            snapshot = morph_client.snapshots.get(snapshot_id)
            snapshot.set_metadata(metadata)
            snapshot._refresh()  # Refresh to get updated metadata
            
            log(LogLevel.SUCCESS, f"Set metadata on snapshot {snapshot_id}")
        except Exception as e:
            log(LogLevel.ERROR, f"Failed to set metadata on snapshot {snapshot_id}: {e}", 
                extra={"error": str(e)})
            import traceback
            log(LogLevel.ERROR, f"Metadata error traceback", 
                extra={"traceback": traceback.format_exc()})
            raise
    
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
        try:
            if hasattr(self, 'instance') and self.instance:
                self.stop()
        except (AttributeError, Exception):
            # Ignore errors during garbage collection
            pass


