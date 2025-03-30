export MORPH_API_KEY=
export ANTHROPIC_API_KEY=
uv venv
source .venv/bin/activate
uv pip install dotenv
uv pip install morphcloud
uv pip install pillow
uv pip install mcp

# if you do not have a snapshot
uv run setup_romwatch_server.py 
morphcloud instance copy pokemon_red.gb morphvm_a4qc7j04:/root/pokemon/roms/pokemon_red.gb
morphcloud instance ssh morphvm_a4qc7j04 -- systemctl start pokemon-server.service
morphcloud instance snapshot morphvm_a4qc7j04

# if you have a snapshot
# server/ui version: 
uv run pokemon_agent_trajectory.py --snapshot-id snapshot_4zixppki --port 9999
uv run trajectory_driver.py --api-port 9999 --ui-port 8080

# no ui
uv run pokemon_agent_trajectory.py --snapshot-id snapshot_4zixppki --no-api
