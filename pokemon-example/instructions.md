export MORPH_API_KEY=
export ANTHROPIC_API_KEY=
uv venv
source .venv/bin/activate
uv pip install dotenv
uv pip install morphcloud
uv pip install pillow
uv pip install mcp
uv run setup_romwatch_server.py
morphcloud instance copy pokemon_red.gb morphvm_a4qc7j04:/root/pokemon/roms/pokemon_red.gb
morphcloud instance ssh morphvm_a4qc7j04 -- systemctl start pokemon-server.service
morphcloud instance snapshot morphvm_a4qc7j04
uv run eva_pokemon2.py --snapshot-id snapshot_ue70az39


