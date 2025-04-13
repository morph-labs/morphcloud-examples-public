# Instructions

## bash/CLI
```bash
chmod +x docker-buildkit_setup.py
./docker-buildkit_setup.py
```

## python
```python
uv run docker-buildkit_setup.py
```

## info
- sets up Docker with BuildKit optimization in a Morph Cloud VM
- creates a multi-stage build demo with health check and web server
- uses a 2 vcpu 2GB ram and 4GB disk instance
- accessible through web browser with exposed HTTP services

## notes
- make sure to export your MORPH_API_KEY into your environment
- uv will automatically pick up the dependencies for you
- alternatively, use uv venv to set up a proper venv for morphcloud
- BuildKit enables parallel, multi-stage builds for improved performance
