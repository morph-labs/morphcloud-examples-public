# Instructions

## bash/CLI
```bash
chmod +x remote-desktop_setup.sh
./remote-desktop_setup.sh
```

## python
```python
uv run remote-desktop_setup.sh
```

## info
- opens VNC server and GUI
- uses a 4 vcpu 4GB ram and 8GB disk instance

## notes
- make sure to export your MORPH_API_KEY into your environment
- note that uv will automatically pick up the dependencies for you
- but you might want to use uv venv to set up a real venv so you can use morphcloud
