import subprocess
import time
import shlex
import time
import base64
import io
import traceback
from morphcloud.api import MorphCloudClient

class MorphComputer:
    """
    Base MorphComputer class for interacting with cloud-based VM environments.
    
    This class provides the foundation for creating, managing, and interacting with
    remote desktop environments on the Morph Cloud platform. It supports:
    
    - Creating new instances from scratch or from existing snapshots
    - Managing instance lifecycle (start, stop)
    - Interacting with the desktop environment (mouse, keyboard, screenshots)
    - Creating new snapshots with metadata
    
    A MorphComputer can be initialized in three ways:
    1. With an instance_id to connect to an existing instance
    2. With a snapshot_id to create a new instance from a specific snapshot
    3. Without either, which will create a new instance from the best available snapshot
    """
    environment = "linux"
    dimensions = (1280, 800)  # Default from your script

    def __init__(
        self,
        instance_id=None,
        snapshot_id=None,
        display=":1",
        vcpus=4,
        memory=4096,
        disk_size=8192,
        setup_if_needed=True,
        auto_open_browser=False,
        skip_verification=False,
    ):
        """
        Initialize a MorphComputer instance.
        
        Args:
            instance_id (str, optional): ID of an existing instance to connect to
            snapshot_id (str, optional): ID of a specific snapshot to start from
            display (str, optional): X display to use. Defaults to ":1"
            vcpus (int, optional): Number of virtual CPUs. Defaults to 4
            memory (int, optional): Memory in MB. Defaults to 4096
            disk_size (int, optional): Disk size in MB. Defaults to 8192
            setup_if_needed (bool, optional): Whether to setup desktop if needed. Defaults to True
            auto_open_browser (bool, optional): Whether to auto-open browser. Defaults to False
            skip_verification (bool, optional): Skip snapshot verification. Defaults to False
        """
        self.instance_id = instance_id
        self.snapshot_id = snapshot_id
        self.display = display
        self.vcpus = vcpus
        self.memory = memory
        self.disk_size = disk_size
        self.setup_if_needed = setup_if_needed
        self.auto_open_browser = auto_open_browser
        self.skip_verification = skip_verification
        self.client = MorphCloudClient()
        self.instance = None

    def __enter__(self):
        # Initialize or get the instance
        if self.instance_id:
            # Get existing instance
            self.instance = self.client.instances.get(self.instance_id)
            print(f"Using existing instance: {self.instance_id}")
            
            # Check if instance is running
            if self.instance.status != "running":
                print(f"Starting instance {self.instance_id}...")
                self.instance = self.client.instances.start(self.instance_id)
        # If a specific snapshot_id was provided, use it to create the instance
        elif self.snapshot_id:
            if self.skip_verification:
                print(f"Skip verification flag is set. Starting instance from snapshot {self.snapshot_id} without validation...")
                try:
                    self.instance = self.client.instances.start(self.snapshot_id)
                    self.instance_id = self.instance.id
                    print(f"Successfully started instance {self.instance_id} from snapshot {self.snapshot_id}")
                except Exception as e:
                    print(f"Error starting instance from snapshot {self.snapshot_id} even with skip_verification: {e}")
                    print(f"Falling back to standard initialization...")
                    self.snapshot_id = None
            else:
                print(f"Validating provided snapshot: {self.snapshot_id}...")
                try:
                    # Check if the snapshot exists and is in a usable state
                    snapshot = self.client.snapshots.get(self.snapshot_id)
                    if snapshot.status != "ready":
                        print(f"Warning: Snapshot {self.snapshot_id} is not in 'ready' state (current: {snapshot.status})")
                        print("This may cause issues when starting an instance from it.")
                        # Ask for confirmation before proceeding
                        consent = input(f"Continue with snapshot {self.snapshot_id} in '{snapshot.status}' state? (y/n): ")
                        if consent.lower() != 'y':
                            print("Aborting use of non-ready snapshot. Falling back to standard initialization...")
                            self.snapshot_id = None
                    
                    if self.snapshot_id:  # If still using the snapshot after validation
                        print(f"Starting instance from provided snapshot: {self.snapshot_id}...")
                        self.instance = self.client.instances.start(self.snapshot_id)
                        self.instance_id = self.instance.id
                        print(f"Successfully started instance {self.instance_id} from snapshot {self.snapshot_id}")
                except Exception as e:
                    print(f"Error with snapshot {self.snapshot_id}: {e}")
                    print(f"Falling back to standard initialization...")
                    # Fall back to standard init if the provided snapshot ID fails
                    self.snapshot_id = None
        
        # If no instance_id or valid snapshot_id was provided, use the standard initialization
        if not self.instance_id and not self.snapshot_id:
            # First try to find snapshots with remote-desktop-use metadata (fully setup)
            snapshots = self.client.snapshots.list(metadata={"type": "remote-desktop-use"})
            
            if snapshots:
                # Use the most recent remote-desktop-use snapshot
                snapshot = snapshots[0]
                print(f"Found remote-desktop-use snapshot: {snapshot.id}")
                print(f"Starting instance from ready-to-use snapshot: {snapshot.id}...")
                self.instance = self.client.instances.start(snapshot.id)
                print(f"Instance: {self.instance.id}")
            else:
                # If not found, try with regular remote-desktop metadata (needs tools)
                snapshots = self.client.snapshots.list(metadata={"type": "remote-desktop"})
                
                if snapshots:
                    # Use the most recent remote-desktop snapshot
                    snapshot = snapshots[0]
                    print(f"Found remote-desktop snapshot: {snapshot.id}")
                    print(f"Starting instance from remote-desktop snapshot: {snapshot.id}...")
                    self.instance = self.client.instances.start(snapshot.id)
                    print(f"Instance: {self.instance.id}")
                    
                    # Ensure required tools are installed
                    self._ensure_tools_installed()
                    print("Creating ready-to-use desktop snapshot...")
                    use_snapshot = self.instance.snapshot()
                    print(f"Created use snapshot with ID: {use_snapshot.id}")
                    
                    metadata = {
                        "type": "remote-desktop-use",
                        "description": "Ready-to-use remote desktop environment with xdotool and imagemagick"
                    }
                    print(f"Setting metadata on use snapshot {use_snapshot.id}: {metadata}")
                    use_snapshot.set_metadata(metadata)
                    print(f"Successfully set metadata on ready-to-use snapshot: {use_snapshot.id}")
                
                else:
                    # Create a new instance from scratch
                    print("No suitable snapshot found. Creating new instance...")
                    snapshot = self._get_or_create_snapshot(self.vcpus, self.memory, self.disk_size)
                    self.instance = self.client.instances.start(snapshot.id)
                    
                    # Set up full remote desktop environment if needed
                    if self.setup_if_needed:
                        print("Setting up remote desktop environment from scratch...")
                        self._setup_remote_desktop()
        
        # Update instance_id
        self.instance_id = self.instance.id
                
        # Get actual display geometry
        try:
            geometry = self._exec(f"DISPLAY={self.display} xdotool getdisplaygeometry").strip()
            if geometry:
                w, h = geometry.split()
                self.dimensions = (int(w), int(h))
                print(f"Screen dimensions: {self.dimensions[0]}x{self.dimensions[1]}")
        except Exception as e:
            print(f"Could not get display geometry: {e}")
        
        desktop_url = f"https://desktop-{self.instance_id.replace('_', '-')}.http.cloud.morph.so/vnc_lite.html"
        print(f"watch here!")
        print(desktop_url)
        
        if self.auto_open_browser:
            import webbrowser
            webbrowser.open(desktop_url)
            
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Keep the instance running when exiting the context
        pass

    def _get_or_create_snapshot(self, vcpus, memory, disk_size):
        """Get an existing snapshot with matching metadata or create a new one"""
        # Define the snapshot configuration metadata
        snapshot_metadata = {
            "type": "base",
            "vcpus": str(vcpus),
            "memory": str(memory),
            "disk_size": str(disk_size)
        }
        
        # Try to find an existing snapshot with matching metadata
        print("Looking for existing snapshot with matching configuration...")
        existing_snapshots = self.client.snapshots.list(metadata={"type": "base"})
        
        for snapshot in existing_snapshots:
            if (snapshot.status == "ready" and
                snapshot.metadata.get("vcpus") == snapshot_metadata["vcpus"] and
                snapshot.metadata.get("memory") == snapshot_metadata["memory"] and
                snapshot.metadata.get("disk_size") == snapshot_metadata["disk_size"]):
                print(f"Found existing snapshot {snapshot.id}")
                return snapshot
        
        # No matching snapshot found, create a new one
        print("Creating new snapshot...")
        snapshot = self.client.snapshots.create(
            vcpus=vcpus,
            memory=memory,
            disk_size=disk_size,
        )
        
        # Add metadata to the snapshot
        snapshot.set_metadata(snapshot_metadata)
        
        return snapshot

    def _setup_remote_desktop(self):
        """Set up a remote desktop environment on the instance"""
        # Abbreviated setup - using key parts from your original script
        
        # Install required packages
        print("Installing required packages...")
        packages = [
            "xfce4", "xfce4-goodies", "tigervnc-standalone-server", "tigervnc-common",
            "python3", "python3-pip", "python3-websockify", "git", "net-tools", 
            "nginx", "dbus", "dbus-x11", "xfonts-base", "xdotool", "imagemagick"
        ]
        self._exec(
            "DEBIAN_FRONTEND=noninteractive apt-get update -q && "
            "DEBIAN_FRONTEND=noninteractive apt-get install -y -q "
            f"{' '.join(packages)}"
        )
        
        # Clone noVNC repository
        self._exec("git clone https://github.com/novnc/noVNC.git /opt/noVNC")
        
        # Kill any existing VNC processes
        self._exec("pkill Xvnc || true; rm -f /tmp/.X1-lock /tmp/.X11-unix/X1 || true")
        
        # Create necessary directories
        for directory in ["xfce4", "xfce4-session", "autostart", "systemd"]:
            self._exec(f"mkdir -p /root/.config/{directory}")
        
        # Create VNC server service
        vncserver_service = """
[Unit]
Description=VNC Server for X11
After=syslog.target network.target

[Service]
Type=simple
User=root
Environment=HOME=/root
Environment=DISPLAY=:1
ExecStartPre=-/bin/rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
ExecStart=/usr/bin/Xvnc :1 -geometry 1280x800 -depth 24 -SecurityTypes None -localhost no
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
        self._exec(f"cat > /etc/systemd/system/vncserver.service << 'EOF'\n{vncserver_service}\nEOF")
        
        # Create and configure other services (abbreviated)
        session_script = """#!/bin/bash
export DISPLAY=:1
export HOME=/root
export XDG_CONFIG_HOME=/root/.config
export XDG_CACHE_HOME=/root/.cache
export XDG_DATA_HOME=/root/.local/share
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/dbus/system_bus_socket

# Start dbus if not running
if [ -z "$DBUS_SESSION_BUS_PID" ]; then
  eval $(dbus-launch --sh-syntax)
fi

# Ensure xfconfd is running
/usr/lib/x86_64-linux-gnu/xfce4/xfconf/xfconfd &

# Wait for xfconfd to start
sleep 2

# Start XFCE session
exec startxfce4
"""
        self._exec(f"cat > /usr/local/bin/start-xfce-session << 'EOF'\n{session_script}\nEOF")
        self._exec("chmod +x /usr/local/bin/start-xfce-session")
        
        # Create and start services
        services = ["vncserver", "xfce-session", "novnc", "nginx"]
        self._exec("systemctl daemon-reload")
        for service in services:
            self._exec(f"systemctl enable {service} && systemctl restart {service}")
        
        # Expose HTTP service
        self.instance.expose_http_service("desktop", 80)
        
        # Allow time for services to start
        print("Waiting for services to fully start...")
        time.sleep(10)
        
        # Create a snapshot of the base remote desktop (without tools)
        try:
            print("Creating remote-desktop snapshot...")
            remote_desktop_snapshot = self.instance.snapshot()
            print(f"Created snapshot with ID: {remote_desktop_snapshot.id}")
            
            metadata = {
                "type": "remote-desktop",
                "description": "Remote desktop environment with XFCE and noVNC"
            }
            print(f"Setting metadata on snapshot {remote_desktop_snapshot.id}: {metadata}")
            remote_desktop_snapshot.set_metadata(metadata)
            print(f"Successfully set metadata on remote-desktop snapshot: {remote_desktop_snapshot.id}")
        except Exception as e:
            print(f"Error creating or setting metadata on remote-desktop snapshot: {e}")
            print(f"Error details: {traceback.format_exc()}")
            # Continue setup even if snapshot creation fails
        
        # Now install the additional tools needed for remote-desktop-use
        tools = {
            "xdotool": "xdotool",
            "imagemagick": "imagemagick"
        }
        
        for tool, package in tools.items():
            print(f"Installing {tool}...")
            self._exec(f"apt-get update && apt-get install -y {package}")
        
        # Create the fully setup use snapshot
        try:
            print("Creating ready-to-use desktop snapshot...")
            use_snapshot = self.instance.snapshot()
            print(f"Created use snapshot with ID: {use_snapshot.id}")
            
            metadata = {
                "type": "remote-desktop-use",
                "description": "Ready-to-use remote desktop environment with xdotool and imagemagick"
            }
            print(f"Setting metadata on use snapshot {use_snapshot.id}: {metadata}")
            use_snapshot.set_metadata(metadata)
            print(f"Successfully set metadata on ready-to-use snapshot: {use_snapshot.id}")
        except Exception as e:
            print(f"Error creating or setting metadata on ready-to-use snapshot: {e}")
            print(f"Error details: {traceback.format_exc()}")
            # Continue even if snapshot creation fails

    def _ensure_tools_installed(self):
        """Make sure necessary tools are installed"""
        # Skip if using a ready-to-use snapshot
        try:
            snapshot_info = self.client.snapshots.get(self.instance.snapshot_id)
            if snapshot_info.metadata.get("type") == "remote-desktop-use":
                print("Using ready-to-use desktop snapshot, all tools already installed")
                return
        except:
            # If we can't determine the snapshot type, proceed with checking tools
            pass
        
        # Check if we're starting from a remote-desktop snapshot (needs tools only)
        is_remote_desktop = False
        try:
            snapshot_info = self.client.snapshots.get(self.instance.snapshot_id)
            if snapshot_info.metadata.get("type") == "remote-desktop":
                is_remote_desktop = True
                print("Using remote-desktop snapshot, installing required tools...")
        except:
            # If we can't determine the snapshot type, proceed normally
            pass
        
        # Required tools for use
        tools = {
            "xdotool": "xdotool",
            "imagemagick": "imagemagick"
        }
        
        # Install missing tools
        tools_installed = False
        for tool, package in tools.items():
            try:
                self._exec(f"which {tool}")
                print(f"{tool} is already installed")
            except:
                print(f"Installing {tool}...")
                self._exec(f"apt-get update && apt-get install -y {package}")
                tools_installed = True
        
        # Create a use snapshot if we upgraded from remote-desktop to remote-desktop-use
        if is_remote_desktop and tools_installed and self.setup_if_needed:
            try:
                print("Creating remote-desktop-use snapshot for future use...")
                use_snapshot = self.instance.snapshot()
                print(f"Created upgrade snapshot with ID: {use_snapshot.id}")
                
                metadata = {
                    "type": "remote-desktop-use",
                    "description": "Ready-to-use remote desktop environment with xdotool and imagemagick"
                }
                print(f"Setting metadata on upgrade snapshot {use_snapshot.id}: {metadata}")
                use_snapshot.set_metadata(metadata)
                print(f"Successfully set metadata on upgrade snapshot: {use_snapshot.id}")
            except Exception as e:
                print(f"Error creating or setting metadata on upgrade snapshot: {e}")
                print(f"Error details: {traceback.format_exc()}")
                # Continue even if snapshot creation fails
    
    def _exec(self, command, sudo=False, max_retries=3):
        """Run a command on the instance via morphcloud API"""
        if sudo:
            if '|' in command or '>' in command or '<' in command or ';' in command:
                # For commands with shell operators, use sh -c
                command = f"sudo sh -c '{command}'"
            else:
                # Simple prepend for basic commands
                command = f"sudo {command}"
        
        # Implement silent retry with exponential backoff for 500 errors
        retry_count = 0
        backoff_time = 0.1  # Start with 0.1 second
        
        while True:
            try:
                result = self.instance.exec(command)
                
                # If successful or non-500 error, proceed normally
                if result.exit_code != 0:
                    raise RuntimeError(f"Command failed: {command}\nError: {result.stderr}")
                
                return result.stdout
                
            except Exception as e:
                # Check if it's a 500 error
                error_str = str(e)
                is_500_error = "500" in error_str
                
                # If it's not a 500 error or we've exceeded retries, raise the error
                if not is_500_error or retry_count >= max_retries:
                    raise
                
                # Otherwise, silently retry with backoff
                retry_count += 1
                time.sleep(backoff_time)
                backoff_time = min(backoff_time * 2, 1.0)  # Double backoff time, max 1 second

    def screenshot(self):
        """Takes a screenshot, returning base64-encoded PNG"""
        cmd = (
            f"export DISPLAY={self.display} && "
            "import -window root png:- | base64 -w 0"
        )
        return self._exec(cmd)

    def click(self, x, y, button="left"):
        """Click at specified coordinates"""
        button_map = {"left": 1, "middle": 2, "right": 3}
        b = button_map.get(button, 1)
        self._exec(f"DISPLAY={self.display} xdotool mousemove {x} {y} click {b}")

    def double_click(self, x, y):
        """Double-click at specified coordinates"""
        self._exec(f"DISPLAY={self.display} xdotool mousemove {x} {y} click --repeat 2 1")

    def scroll(self, x, y, scroll_x, scroll_y):
        """Scroll at specified coordinates"""
        self._exec(f"DISPLAY={self.display} xdotool mousemove {x} {y}")
        clicks = abs(scroll_y)
        button = 4 if scroll_y < 0 else 5
        for _ in range(clicks):
            self._exec(f"DISPLAY={self.display} xdotool click {button}")

    def type(self, text):
        """Type the given text"""
        # Escape single quotes in the user text: ' -> '\'\''
        safe_text = text.replace("'", "'\\''")
        # Then wrap everything in single quotes for xdotool
        cmd = f"DISPLAY={self.display} xdotool type -- '{safe_text}'"
        self._exec(cmd)

    def wait(self, ms=1000):
        """Wait for the specified number of milliseconds"""
        time.sleep(ms / 1000)

    def move(self, x, y):
        """Move mouse to specified coordinates"""
        self._exec(f"DISPLAY={self.display} xdotool mousemove {x} {y}")

    def keypress(self, keys, press_ms=500):
        """Press the specified keys"""
        mapping = {
            "ARROWLEFT": "Left",
            "ARROWRIGHT": "Right",
            "ARROWUP": "Up",
            "ARROWDOWN": "Down",
            "ENTER": "Return",
            "LEFT": "Left",
            "RIGHT": "Right",
            "UP": "Up",
            "DOWN": "Down",
            "ESC": "Escape",
            "SPACE": "space",
            "BACKSPACE": "BackSpace",
            "TAB": "Tab",
        }
        mapped_keys = [mapping.get(key, key) for key in keys]
        combo = "+".join(mapped_keys)
        self._exec(f"DISPLAY={self.display} xdotool key --delay 500 {combo}")

    def drag(self, path):
        """Drag from point to point along a path"""
        if not path:
            return
        start_x = path[0]["x"]
        start_y = path[0]["y"]
        self._exec(f"DISPLAY={self.display} xdotool mousemove {start_x} {start_y} mousedown 1")
        for point in path[1:]:
            self._exec(f"DISPLAY={self.display} xdotool mousemove {point['x']} {point['y']}")
        self._exec(f"DISPLAY={self.display} xdotool mouseup 1")

    def get_desktop_url(self):
        """Get the URL to access the remote desktop"""
        # Refresh instance data
        self.instance = self.client.instances.get(self.instance_id)
        desktop_service = next(
            (svc for svc in self.instance.networking.http_services if svc.name == "desktop"), 
            None
        )
        if desktop_service:
            return f"{desktop_service.url}/vnc_lite.html"
        return f"https://desktop-{self.instance_id.replace('_', '-')}.http.cloud.morph.so/vnc_lite.html"
    
    def create_snapshot(self, description=None, metadata=None):
        """
        Create a snapshot of the current computer state.
        
        Args:
            description (str, optional): Human-readable description of the snapshot
            metadata (dict, optional): Additional metadata to store with the snapshot
            
        Returns:
            The snapshot object, not just the ID
        """
        print(f"Creating snapshot...")
        snapshot = self.instance.snapshot()
        snapshot_id = snapshot.id
        print(f"Created snapshot {snapshot_id}")
        
        # Add metadata if provided
        if metadata:
            print(f"Setting metadata on snapshot {snapshot_id}")
            snapshot.set_metadata(metadata)
        
        return snapshot  # Return the full snapshot object
        
    def cleanup(self):
        """
        Clean up resources used by this computer.
        This is a more intuitive alternative to __exit__.
        """
        try:
            self.__exit__(None, None, None)
            print("[green]Cleaned up computer resources[/]")
            return True
        except Exception as e:
            print(f"[bold red]Error cleaning up computer: {e}[/]")
            return False

    @classmethod
    def from_snapshot(cls, snapshot, auto_open_browser=False, skip_verification=False, **kwargs):
        """
        Create a new MorphComputer instance from a snapshot object or ID.
        
        Args:
            snapshot: A snapshot object or snapshot ID string
            auto_open_browser (bool): Whether to open browser automatically
            skip_verification (bool): Whether to skip snapshot verification
            **kwargs: Additional arguments for MorphComputer
            
        Returns:
            A new MorphComputer instance
        """
        # Handle either snapshot object or snapshot ID
        snapshot_id = snapshot.id if hasattr(snapshot, 'id') else snapshot
        
        return cls(snapshot_id=snapshot_id, 
                   auto_open_browser=auto_open_browser,
                   skip_verification=skip_verification,
                   **kwargs)
