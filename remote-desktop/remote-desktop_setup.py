# /// script
# dependencies = [
#   "morphcloud",
# ]
# ///

#!/usr/bin/env python3
"""
Setup script for creating a Morph Cloud VM with a remote desktop.
This version directly runs commands via SSH instead of using Ansible.
"""

import sys
import time

from morphcloud.api import MorphCloudClient


def run_ssh_command(instance, command, sudo=False, print_output=True):
    """Run a command on the instance via SSH and return the result"""
    if sudo and not command.startswith("sudo "):
        command = f"sudo {command}"

    print(f"Running on VM: {command}")
    result = instance.exec(command)

    if print_output:
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(f"ERR: {result.stderr}", file=sys.stderr)

    if result.exit_code != 0:
        print(f"Command failed with exit code {result.exit_code}")

    return result


def run_ssh_script(instance, script_content, sudo=True):
    """Run a multi-line script on the instance via SSH"""
    # Create a temporary script file
    result = run_ssh_command(
        instance, "cat > /tmp/setup_script.sh << 'EOF'\n" f"{script_content}\n" "EOF"
    )

    # Make the script executable
    run_ssh_command(instance, "chmod +x /tmp/setup_script.sh")

    # Run the script
    if sudo:
        return run_ssh_command(instance, "sudo bash /tmp/setup_script.sh")
    else:
        return run_ssh_command(instance, "bash /tmp/setup_script.sh")


def get_or_create_snapshot(client, vcpus, memory, disk_size):
    """Get an existing snapshot with matching metadata or create a new one"""
    # Define the snapshot configuration metadata
    snapshot_metadata = {
        "type": "base",
        "vcpus": str(vcpus),
        "memory": str(memory),
        "disk_size": str(disk_size),
    }

    # Try to find an existing snapshot with matching metadata
    print("Looking for existing snapshot with matching configuration...")
    existing_snapshots = client.snapshots.list(metadata={"type": "base"})

    for snapshot in existing_snapshots:
        if (
            snapshot.status == "ready"
            and snapshot.metadata.get("vcpus") == snapshot_metadata["vcpus"]
            and snapshot.metadata.get("memory") == snapshot_metadata["memory"]
            and snapshot.metadata.get("disk_size") == snapshot_metadata["disk_size"]
        ):
            print(f"Found existing snapshot {snapshot.id} with matching configuration")
            return snapshot

    # No matching snapshot found, create a new one
    print("No matching snapshot found. Creating new snapshot...")
    snapshot = client.snapshots.create(
        vcpus=vcpus,
        memory=memory,
        disk_size=disk_size,
    )

    # Add metadata to the snapshot
    print("Adding metadata to snapshot...")
    snapshot.set_metadata(snapshot_metadata)

    return snapshot


def setup_remote_desktop(instance):
    """Set up a remote desktop environment on the instance"""
    print("Setting up remote desktop environment...")

    # Step 1: Ensure Python3 is installed with non-interactive mode
    print("\n--- 1. Installing Python3 ---")
    run_ssh_command(
        instance,
        "DEBIAN_FRONTEND=noninteractive apt-get update -q && "
        "DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3",
        sudo=True,
    )

    # Step 2: Install required packages with non-interactive mode
    print("\n--- 2. Installing required packages ---")
    packages = [
        "xfce4",
        "xfce4-goodies",
        "tigervnc-standalone-server",
        "tigervnc-common",
        "python3",
        "python3-pip",
        "python3-websockify",
        "git",
        "net-tools",
        "nginx",
        "dbus",
        "dbus-x11",
        "xfonts-base",
    ]
    run_ssh_command(
        instance,
        "DEBIAN_FRONTEND=noninteractive apt-get update -q && "
        "DEBIAN_FRONTEND=noninteractive apt-get install -y -q "
        '-o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" '
        f"{' '.join(packages)}",
        sudo=True,
    )

    # Step 3: Clone noVNC repository
    print("\n--- 3. Cloning noVNC repository ---")
    run_ssh_command(
        instance, "git clone https://github.com/novnc/noVNC.git /opt/noVNC", sudo=True
    )

    # Step 4: Kill any existing VNC processes
    print("\n--- 4. Killing existing VNC processes ---")
    run_ssh_command(
        instance,
        "pkill Xvnc || true; rm -f /tmp/.X1-lock /tmp/.X11-unix/X1 || true",
        sudo=True,
    )

    # Step 5: Create XFCE config directories
    print("\n--- 5. Creating XFCE config directories ---")
    directories = ["xfce4", "xfce4-session", "autostart", "systemd"]
    for directory in directories:
        run_ssh_command(instance, f"mkdir -p /root/.config/{directory}", sudo=True)

    # Step 6: Create systemd service for Xvnc
    print("\n--- 6. Creating VNC server service ---")
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
    run_ssh_command(
        instance,
        f"cat > /etc/systemd/system/vncserver.service << 'EOF'\n{vncserver_service}\nEOF",
        sudo=True,
    )

    # Step 7: Create session startup script
    print("\n--- 7. Creating XFCE session startup script ---")
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
    run_ssh_command(
        instance,
        f"cat > /usr/local/bin/start-xfce-session << 'EOF'\n{session_script}\nEOF",
        sudo=True,
    )
    run_ssh_command(instance, "chmod +x /usr/local/bin/start-xfce-session", sudo=True)

    # Step 8: Create systemd service for XFCE session
    print("\n--- 8. Creating XFCE session service ---")
    xfce_service = """
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
"""
    run_ssh_command(
        instance,
        f"cat > /etc/systemd/system/xfce-session.service << 'EOF'\n{xfce_service}\nEOF",
        sudo=True,
    )

    # Step 9: Create systemd service for noVNC
    print("\n--- 9. Creating noVNC service ---")
    novnc_service = """
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
"""
    run_ssh_command(
        instance,
        f"cat > /etc/systemd/system/novnc.service << 'EOF'\n{novnc_service}\nEOF",
        sudo=True,
    )

    # Step 10: Configure nginx as reverse proxy
    print("\n--- 10. Configuring nginx as reverse proxy ---")
    nginx_config = """
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://localhost:6080/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
"""
    run_ssh_command(
        instance,
        f"cat > /etc/nginx/sites-available/novnc << 'EOF'\n{nginx_config}\nEOF",
        sudo=True,
    )

    # Step 11: Enable nginx site and disable default
    print("\n--- 11. Enabling nginx site and disabling default ---")
    run_ssh_command(
        instance,
        "ln -sf /etc/nginx/sites-available/novnc /etc/nginx/sites-enabled/novnc",
        sudo=True,
    )
    run_ssh_command(instance, "rm -f /etc/nginx/sites-enabled/default", sudo=True)

    # Step 12: Start and enable services
    print("\n--- 12. Starting and enabling services ---")
    services = ["vncserver", "xfce-session", "novnc", "nginx"]
    for service in services:
        run_ssh_command(
            instance,
            f"systemctl daemon-reload && systemctl enable {service} && systemctl restart {service}",
            sudo=True,
        )

    # Step 13: Check service status and retry if needed
    print("\n--- 13. Verifying services are running ---")
    for service in services:
        # Create a temporary script to check and restart the service if needed
        check_script = f"""#!/bin/bash
    for i in {{1..3}}; do
      if systemctl is-active {service} > /dev/null; then
        echo '{service} is running'
        break
      fi
      echo 'Waiting for {service} to start...'
      systemctl restart {service}
      sleep 3
    done
    """
    # Write the script to a temporary file
    run_ssh_command(
        instance,
        f"cat > /tmp/check_{service}.sh << 'EOF'\n{check_script}\nEOF",
        sudo=False,
    )

    # Make it executable and run it
    run_ssh_command(instance, f"chmod +x /tmp/check_{service}.sh", sudo=False)
    run_ssh_command(instance, f"sudo /tmp/check_{service}.sh", sudo=False)

    # Step 14: Expose HTTP service
    print("\n--- 14. Exposing HTTP service ---")
    instance.expose_http_service("desktop", 80)

    # Allow time for services to fully start
    print("\nWaiting for services to fully start...")
    time.sleep(10)

    print("\nRemote desktop setup complete!")


def main():
    # Initialize Morph Cloud client
    client = MorphCloudClient()

    # VM configuration
    VCPUS = 4
    MEMORY = 4096  # 4GB
    DISK_SIZE = 8192  # 8GB

    # 1. Get or create a snapshot with the desired configuration
    snapshot = get_or_create_snapshot(client, VCPUS, MEMORY, DISK_SIZE)
    print(f"Using snapshot {snapshot.id}")

    # 2. Start an instance from the snapshot
    print(f"Starting instance from snapshot {snapshot.id}...")
    instance = client.instances.start(snapshot.id)

    # 3. Set up remote desktop directly via SSH
    try:
        setup_remote_desktop(instance)

        # Get updated instance info to show HTTP services
        instance = client.instances.get(instance.id)

        print("\nSetup successful!")
        print(f"Instance ID: {instance.id}")

        # Find desktop service URL
        desktop_service = next(
            (svc for svc in instance.networking.http_services if svc.name == "desktop"),
            None,
        )

        print(f"\nAccess your remote desktop at: {desktop_service.url}/vnc_lite.html")
        print(
            f"https://desktop-{instance.id.replace('_', '-')}.http.cloud.morph.so/vnc_lite.html"
        )

        # Create a final snapshot
        print("\nCreating a final snapshot for future use...")
        final_snapshot = instance.snapshot()
        final_snapshot.set_metadata(
            {
                "type": "remote-desktop",
                "description": "Remote desktop environment with XFCE and noVNC",
            }
        )
        print(f"Final snapshot created: {final_snapshot.id}")
        print(
            f"To start a new instance from this snapshot, run: morphcloud instance start {final_snapshot.id}"
        )

    except Exception as e:
        print(f"\nSetup failed: {e}")
        print("\nFor troubleshooting, try SSHing into the instance directly:")
        print(f"morphcloud instance ssh {instance.id}")

        print("\nYour instance is still running. To stop it, run:")
        print(f"morphcloud instance stop {instance.id}")

        raise


if __name__ == "__main__":
    main()
