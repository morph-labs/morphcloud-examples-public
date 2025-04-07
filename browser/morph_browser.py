# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "morphcloud",
#     "aiohttp",
#     "rich"
# ]
# ///

import asyncio
import os
import time

import aiohttp
from rich.console import Console

# Import necessary libraries
try:
    from morphcloud.api import MorphCloudClient
except ImportError:
    print(
        "Error: morphcloud package not installed. Install with 'pip install morphcloud'"
    )
    exit(1)

console = Console()


class InvalidBrowserSnapshotError(Exception):
    """Raised when a snapshot does not contain valid browser services."""

    pass


class MorphBrowser:
    """Manages browser instances on MorphCloud with service setup and snapshot capabilities.
    This class focuses on the infrastructure and VM management, providing CDP URLs
    that can be used with any CDP-compatible client (like browser-use's Browser).
    """

    def __init__(self, instance=None):
        """Initialize with an optional instance."""
        self.instance = instance
        self._client = MorphCloudClient()
        self.snapshot_id = None  # Store the snapshot ID when creating snapshots

    @classmethod
    async def create(cls, snapshot_id=None, verify=True, initial_url=None):
        """Factory method to create a browser infrastructure from scratch or snapshot.
        Args:
            snapshot_id: Optional ID of a snapshot to start from
            verify: Whether to verify services are running (can be disabled for trusted snapshots)
        Returns:
            MorphBrowser: An initialized browser instance
        """
        self = cls()

        if snapshot_id:
            # Start from existing snapshot
            console.print(
                f"[yellow]Starting instance from snapshot {snapshot_id}...[/yellow]"
            )
            self.instance = await self._client.instances.astart(snapshot_id)
            self.snapshot_id = snapshot_id

            # Verify and ensure all services are running (if requested)
            if verify:
                try:
                    await self._verify_services()
                except Exception as e:
                    # Stop the instance before raising the error
                    if self.instance:
                        console.print(
                            "[yellow]Stopping instance due to validation failure...[/yellow]"
                        )
                        await self.instance.astop()
                        self.instance = None

                    # Raise a specific error about invalid snapshot
                    raise InvalidBrowserSnapshotError(
                        f"Snapshot {snapshot_id} is not a valid browser snapshot: {str(e)}\n"
                        "Please create a new browser snapshot with MorphBrowser.create_for_user_setup()"
                    ) from e
            else:
                console.print(
                    "[yellow]Skipping service verification (verify=False)[/yellow]"
                )
        else:
            # Create new instance with browser setup
            console.print(
                "[yellow]Creating new browser instance from scratch...[/yellow]"
            )
            self.instance = await cls._create_fresh_instance(
                initial_url=initial_url
            )  # Call as cls._create_fresh_instance

        return self

    @classmethod
    async def _create_fresh_instance(
        cls, initial_url="https://www.google.com"
    ):  # Make initial_url a parameter
        """Create a fresh instance with all necessary setup."""
        client = MorphCloudClient()

        console.print("[yellow]Creating base snapshot...[/yellow]")
        snapshot = client.snapshots.create(
            vcpus=4,
            memory=4096,
            disk_size=8192,
            digest="chromebox-1-1",
        )

        # Install required packages
        console.print("[yellow]Installing required packages...[/yellow]")
        snapshot = snapshot.setup(
            """
            # Add Google Chrome repository key
            wget -qO- https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /etc/apt/trusted.gpg.d/google-chrome.gpg
            # Add Chrome repository
            echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list
            # Update package lists
            apt-get update -q
            # Install packages
            DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
            xfce4 \
            xfce4-goodies \
            tigervnc-standalone-server \
            tigervnc-common \
            python3 \
            python3-pip \
            python3-websockify \
            git \
            net-tools \
            nginx \
            dbus \
            dbus-x11 \
            xfonts-base \
            google-chrome-stable
            # Setup noVNC
            rm -rf /opt/noVNC || true
            git clone https://github.com/novnc/noVNC.git /opt/noVNC
            mkdir -p /root/.config/xfce4
        """
        )

        # Setup services with the provided initial URL
        console.print("[yellow]Setting up browser services...[/yellow]")
        snapshot = snapshot.setup(
            f"""
            # VNC server service
            cat > /etc/systemd/system/vncserver.service << 'EOF'
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
EOF
            # XFCE session service
            cat > /usr/local/bin/start-xfce-session << 'EOF'
#!/bin/bash
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
# Start XFCE session
exec startxfce4
EOF
            chmod +x /usr/local/bin/start-xfce-session
            cat > /etc/systemd/system/xfce-session.service << 'EOF'
[Unit]
Description=XFCE Session
After=vncserver.service dbus.service
Requires=vncserver.service dbus.service
[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/start-xfce-session
Restart=on-failure
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
            # Chrome debug service
            cat > /etc/systemd/system/chrome-debug.service << 'EOF'
[Unit]
Description=Chrome Debug Service
After=xfce-session.service
Requires=xfce-session.service
[Service]
Type=simple
User=root
Environment=DISPLAY=:1
ExecStart=/usr/bin/google-chrome \\
    --remote-debugging-port=9223 \\
    --remote-debugging-address=0.0.0.0 \\
    --no-sandbox \\
    --disable-gpu \\
    --no-first-run \\
    --no-default-browser-check \\
    --disable-dev-shm-usage \\
    --start-fullscreen \\
    {initial_url}
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF
            # noVNC service
            cat > /etc/systemd/system/novnc.service << 'EOF'
[Unit]
Description=noVNC service
After=vncserver.service
Requires=vncserver.service
[Service]
Type=simple
User=root
ExecStart=/usr/bin/websockify --web=/opt/noVNC 6080 localhost:5901
Restart=on-failure
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
            # Nginx configuration with host header rewriting
            cat > /etc/nginx/sites-available/default << 'EOF'
server {{
    listen 80;
    server_name _;
    # VNC proxy
    location /vnc/ {{
        proxy_pass http://localhost:6080/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }}
    # Chrome debugging proxy
    location / {{
        proxy_pass http://localhost:9223;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host localhost;
    }}
    # For /json/ endpoints to handle websocket URLs
    location /json/ {{
        proxy_pass http://localhost:9223;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host localhost;
        proxy_set_header Accept-Encoding "";
        sub_filter_types application/json;
        sub_filter_once off;
        sub_filter "ws://localhost" "wss://$http_host";
    }}
}}
EOF
            # Enable services
            systemctl daemon-reload
            systemctl enable vncserver
            systemctl enable xfce-session
            systemctl enable chrome-debug
            systemctl enable novnc
            systemctl enable nginx
            # Mark this as a browser snapshot
            touch /browser_snapshot_valid
        """
        )

        # Start the instance with this snapshot
        console.print("[yellow]Starting instance from prepared snapshot...[/yellow]")
        instance = await client.instances.astart(snapshot.id, ttl_seconds=3600)

        # Start all services
        console.print("[yellow]Starting browser services...[/yellow]")
        instance.exec("systemctl restart vncserver")
        instance.exec("sleep 2")  # Wait for VNC server
        instance.exec("systemctl restart xfce-session")
        instance.exec("sleep 2")  # Wait for XFCE
        instance.exec("systemctl restart chrome-debug")
        instance.exec("sleep 3")  # Wait for Chrome
        instance.exec("systemctl restart novnc")
        instance.exec("systemctl restart nginx")

        # Expose services immediately after creation
        browser_url = instance.expose_http_service("web", 80)  # Expose web service
        vnc_url = instance.expose_http_service("vnc", 6080)  # Expose vnc service
        console.print(
            f"[green]Services exposed: CDP URL: {browser_url}, VNC URL: {vnc_url}/vnc.html[/green]"
        )

        # Verify services are running correctly
        await cls._verify_instance_services(instance)

        return instance

    @classmethod
    async def _verify_instance_services(cls, instance, max_retries=3):
        """Verify that all required services are running properly on the instance."""
        # First check if this is even a valid browser snapshot
        try:
            response = instance.exec(
                "test -f /browser_snapshot_valid && echo 'valid' || echo 'invalid'"
            )
            browser_valid = response.stdout.strip()
            if browser_valid != "valid":
                console.print(
                    "[red]This snapshot is not a valid browser snapshot[/red]"
                )
                raise InvalidBrowserSnapshotError(
                    "Snapshot does not contain the expected browser services"
                )
        except Exception as e:
            console.print(f"[red]Error validating snapshot: {str(e)}[/red]")
            raise InvalidBrowserSnapshotError(f"Failed to validate snapshot: {str(e)}")

        # Check if required services exist
        required_services = [
            "vncserver",
            "xfce-session",
            "chrome-debug",
            "novnc",
            "nginx",
        ]
        for service in required_services:
            response = instance.exec(
                f"systemctl list-unit-files | grep -q {service} && echo 'exists' || echo 'missing'"
            )
            service_exists = response.stdout.strip()
            if service_exists != "exists":
                console.print(
                    f"[red]Required service {service} is missing from this snapshot[/red]"
                )
                raise InvalidBrowserSnapshotError(
                    f"Required service {service} is missing from this snapshot"
                )

        # Now verify the services are working
        for attempt in range(max_retries):
            console.print(f"Verifying services (attempt {attempt+1}/{max_retries})...")

            # Check VNC server
            response = instance.exec("systemctl is-active vncserver")
            vnc_status = response.stdout.strip()
            if vnc_status != "active":
                console.print("[yellow]VNC server not running, restarting...[/yellow]")
                instance.exec("systemctl restart vncserver")
                instance.exec("sleep 2")

            # Check XFCE session
            response = instance.exec("systemctl is-active xfce-session")
            xfce_status = response.stdout.strip()
            if xfce_status != "active":
                console.print(
                    "[yellow]XFCE session not running, restarting...[/yellow]"
                )
                instance.exec("systemctl restart xfce-session")
                instance.exec("sleep 2")

            # Check Chrome debugger
            response = instance.exec("systemctl is-active chrome-debug")
            chrome_status = response.stdout.strip()
            if chrome_status != "active":
                console.print(
                    "[yellow]Chrome debugger not running, restarting...[/yellow]"
                )
                instance.exec("systemctl restart chrome-debug")
                instance.exec("sleep 3")

            # Check if Chrome is actually responding
            response = instance.exec("netstat -tuln | grep 9223")
            chrome_listening = response.stdout.strip()
            if not chrome_listening:
                console.print(
                    "[yellow]Chrome debugger port not listening, restarting...[/yellow]"
                )
                instance.exec("systemctl restart chrome-debug")
                instance.exec("sleep 3")

            # Check noVNC
            response = instance.exec("systemctl is-active novnc")
            novnc_status = response.stdout.strip()
            if novnc_status != "active":
                console.print("[yellow]noVNC not running, restarting...[/yellow]")
                instance.exec("systemctl restart novnc")
                instance.exec("sleep 1")

            # Check nginx
            response = instance.exec("systemctl is-active nginx")
            nginx_status = response.stdout.strip()
            if nginx_status != "active":
                console.print("[yellow]Nginx not running, restarting...[/yellow]")
                instance.exec("systemctl restart nginx")
                instance.exec("sleep 1")

            # Final verification - all services should be active
            all_active = True
            failed_services = []
            for service in required_services:
                response = instance.exec(f"systemctl is-active {service}")
                status = response.stdout.strip()
                if status != "active":
                    all_active = False
                    failed_services.append(service)
                    console.print(f"[red]Service {service} failed to start[/red]")

            # Verify Chrome is actually responding to CDP
            try:
                response = instance.exec("curl -s http://localhost:9223/json/version")
                chrome_response = response.stdout
                if "webSocketDebuggerUrl" in chrome_response:
                    console.print(
                        "[green]Chrome CDP endpoint is responding correctly[/green]"
                    )
                else:
                    console.print(
                        "[yellow]Chrome CDP endpoint not returning valid data, waiting...[/yellow]"
                    )
                    instance.exec("sleep 5")  # Wait a bit longer
                    all_active = False
                    failed_services.append("chrome-cdp")
            except Exception:
                console.print("[red]Failed to connect to Chrome CDP endpoint[/red]")
                all_active = False
                failed_services.append("chrome-cdp")

            if all_active:
                console.print("[green]All services verified and running[/green]")
                return True

            # If we've reached max retries, raise an error
            if attempt == max_retries - 1:
                failed_list = ", ".join(failed_services)
                console.print(
                    f"[red]Failed to start required services after {max_retries} attempts[/red]"
                )
                raise InvalidBrowserSnapshotError(
                    f"Browser snapshot is invalid or corrupted. Failed services: {failed_list}. "
                    "Please create a new browser snapshot with MorphBrowser.create_for_user_setup()"
                )

            console.print(
                f"[yellow]Retrying service verification in 5 seconds...[/yellow]"
            )
            await asyncio.sleep(5)

    async def _verify_services(self):
        """Verify and restart services if needed when starting from a snapshot."""
        if not self.instance:
            raise ValueError("No instance available to verify services")

        await self._verify_instance_services(self.instance)

    async def snapshot(self, digest=None):
        """Create a snapshot of the current browser state and return a new browser."""
        if not self.instance:
            raise ValueError("Cannot snapshot: No active instance")

        console.print(
            f"[yellow]Creating snapshot{' with digest '+digest if digest else ''}...[/yellow]"
        )
        snapshot = await self.instance.asnapshot(digest=digest)
        console.print(f"[green]Snapshot created with ID: {snapshot.id}[/green]")

        # Create a new browser from this snapshot
        browser = await MorphBrowser.create(snapshot_id=snapshot.id)
        return browser

    async def start_from_snapshot(self, snapshot_id, verify=True):
        """Create a new browser from an existing snapshot ID."""
        return await MorphBrowser.create(snapshot_id=snapshot_id, verify=verify)

    async def stop(self):
        """Stop the underlying instance."""
        if self.instance:
            console.print("[yellow]Stopping instance...[/yellow]")
            await self.instance.astop()
            self.instance = None
            console.print("[green]Instance stopped[/green]")

    @property
    def cdp_url(self):
        """Get the CDP URL for this browser."""
        if not self.instance:
            return None
        return self.instance.expose_http_service("web", 80)

    @property
    def vnc_url(self):
        """Get the VNC URL for this browser."""
        if not self.instance:
            return None
        vnc_base = self.instance.expose_http_service("vnc", 6080)
        return f"{vnc_base}/vnc.html"

    # Context manager support
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
