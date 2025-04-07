# /// script
# dependencies = [
#   "morphcloud",
# ]
# ///

#!/usr/bin/env python3
import os
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


def setup_vscode_server(instance):
    """Set up Docker and OpenVSCode Server on the instance"""
    print("Setting up OpenVSCode Server environment...")

    # Step 1: Ensure Python3 is installed - use non-interactive mode
    print("\n--- 1. Installing Python3 ---")
    run_ssh_command(
        instance,
        "DEBIAN_FRONTEND=noninteractive apt-get update -q && "
        "DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3",
        sudo=True,
    )

    # Step 2: Install Docker and dependencies - use non-interactive mode
    print("\n--- 2. Installing Docker and dependencies ---")
    run_ssh_command(
        instance,
        "DEBIAN_FRONTEND=noninteractive apt-get update -q && "
        "DEBIAN_FRONTEND=noninteractive apt-get install -y -q "
        '-o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" '
        "docker.io python3-docker python3-requests",
        sudo=True,
    )

    # Step 3: Start and enable Docker service
    print("\n--- 3. Starting and enabling Docker service ---")
    run_ssh_command(
        instance, "systemctl start docker && systemctl enable docker", sudo=True
    )

    # Step 4: Create workspace directory
    print("\n--- 4. Creating workspace directory ---")
    run_ssh_command(
        instance,
        "mkdir -p /opt/vscode-workspace && chmod 755 /opt/vscode-workspace",
        sudo=True,
    )

    # Step 5: Run OpenVSCode Server container
    print("\n--- 5. Running OpenVSCode Server container ---")
    # Check if Docker is running before proceeding
    run_ssh_command(
        instance,
        "docker ps > /dev/null || (systemctl restart docker && sleep 3)",
        sudo=True,
    )

    run_ssh_command(
        instance,
        "docker run -d --init --name openvscode-server "
        "-p 3000:3000 "
        '-v "/opt/vscode-workspace:/home/workspace:cached" '
        "--restart unless-stopped "
        "gitpod/openvscode-server",
        sudo=True,
    )

    # Step 6: Expose HTTP service
    print("\n--- 6. Exposing HTTP service ---")
    instance.expose_http_service("vscode", 3000)

    # Step 7: Wait for container to be fully running
    print("\nWaiting for VSCode Server to start...")
    check_script = """#!/bin/bash
    for i in {1..12}; do
      if docker ps | grep -q openvscode-server; then
        echo 'Container is running'
        break
      fi
      echo "Waiting for container to start... (attempt $i/12)"
      sleep 5
    done
    """
    # Write the script to a temporary file
    run_ssh_command(
        instance,
        f"cat > /tmp/check_container.sh << 'EOF'\n{check_script}\nEOF",
        sudo=False,
    )

    # Make it executable and run it
    run_ssh_command(instance, "chmod +x /tmp/check_container.sh", sudo=False)
    run_ssh_command(instance, "sudo /tmp/check_container.sh", sudo=False)

    print("\nOpenVSCode Server setup complete!")


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

    # 3. Set up VSCode server directly via SSH
    try:
        setup_vscode_server(instance)

        # Get updated instance info to show HTTP services
        instance = client.instances.get(instance.id)

        print("\nSetup successful!")
        print(f"Instance ID: {instance.id}")

        # Find VSCode service URL
        vscode_service = next(
            (svc for svc in instance.networking.http_services if svc.name == "vscode"),
            None,
        )

        if vscode_service:
            print(f"\nAccess your VSCode Server at: {vscode_service.url}")
            print("Your workspace is mounted at: /home/workspace")
        else:
            print(
                "\nCould not find VSCode HTTP service URL. You can manually access it at:"
            )
            print(f"https://vscode-{instance.id.replace('_', '-')}.http.cloud.morph.so")

        # Create a final snapshot
        print("\nCreating a final snapshot for future use...")
        final_snapshot = instance.snapshot()
        final_snapshot.set_metadata(
            {
                "type": "openvscode-server",
                "description": "OpenVSCode Server environment",
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
