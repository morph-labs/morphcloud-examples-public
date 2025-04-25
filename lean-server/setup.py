from morphcloud.api import MorphCloudClient, console
mc = MorphCloudClient()

snap = mc.snapshots.create(vcpus=2, memory=4096, disk_size=20480, digest="pantograph-1-1")

# OS deps + uv
snap = snap.exec(
    "apt-get update && "
    "apt-get install -y git curl python3.11 python3.11-venv build-essential pipx"
)
snap = snap.exec("pipx install uv && pipx ensurepath")

# Python venv + FastAPI
snap = snap.exec("uv venv /opt/venv")
snap = snap.exec(
    "source /opt/venv/bin/activate && "
    "uv pip install fastapi 'uvicorn[standard]'"
)

# Lean toolchain
snap = snap.exec(
    "curl https://elan.lean-lang.org/elan-init.sh -sSf | "
    "sh -s -- -y --default-toolchain leanprover/lean4:v4.18.0"
)

# --- Mathlib project setup ---
# create a Lean project that depends on Mathlib4
snap = snap.exec(
    'export PATH="$HOME/.elan/bin:$PATH" && '
    'lake +leanprover/lean4:v4.18.0 new mathlib_project math.toml'
)
# fetch all dependencies, including Mathlib
snap = snap.exec(
    """
    export PATH="$HOME/.elan/bin:$PATH"
    cd mathlib_project
    echo "leanprover/lean4:v4.18.0" > lean-toolchain
    cat > lakefile.toml << 'EOF'
name = "mathlib_project"
version = "0.1.0"
keywords = ["math"]
defaultTargets = ["MathlibProject"]

[leanOptions]
pp.unicode.fun = true # pretty-prints `fun a ↦ b`
autoImplicit = false

[[require]]
name = "mathlib"
scope = "leanprover-community"
version = "git#v4.18.0"

[[lean_lib]]
name = "MathlibProject"

EOF
    lake exe cache get 
    lake update 
    lake build
    """
)

# PyPantograph from source
snap = snap.exec(
    "git clone --recurse-submodules "
    "https://github.com/stanford-centaur/PyPantograph.git /src/PyPantograph"
)

snap = snap.exec(
    'export PATH="$HOME/.elan/bin:$PATH" && '
    'source /opt/venv/bin/activate && '
    'uv pip install /src/PyPantograph'
)

# Gateway code & start script
snap = snap.upload("daemon.py", "/opt/pantograph/daemon.py")
snap = snap.exec(
    '''cat > /etc/systemd/system/pantograph.service << 'EOF'
[Unit]
Description=Pantograph Lean Server
After=network.target

[Service]
ExecStart=/opt/venv/bin/python -u /opt/pantograph/daemon.py
WorkingDirectory=/root/mathlib_project
User=root
Group=root
Restart=always
RestartSec=5
Environment="PATH=/root/.elan/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
'''
)

console.print(f"[green bold]Snapshot ready:[/green bold] {snap.id}")

instance = mc.instances.start(snap.id)
instance.exec(
    "systemctl daemon-reload && "
    "systemctl enable pantograph.service && "
    "systemctl start pantograph.service"
)
pantograph_url = instance.expose_http_service("pantograph", 5326)

console.print(f"[green bold]Pantograph server ready at:[/green bold] {pantograph_url}")