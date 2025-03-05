# Instructions

## bash/CLI
```bash
chmod +x remote-desktop_setup.sh
./remote-desktop_setup.sh
```

## python
```python
uv run remote-desktop_setup.py
```

## info
- sets up XFCE4 desktop environment
- runs TigerVNC server with noVNC web client
- uses a 4 vcpu 4GB ram and 8GB disk instance
- accessible through web browser - no VNC client needed


## notes
- make sure to export your MORPH_API_KEY into your environment
- note that uv will automatically pick up the dependencies for you
- but you might want to use uv venv to set up a real venv so you can use morphcloud

## image
<img width="1792" alt="image" src="https://github.com/user-attachments/assets/dbde6cf7-b619-4e5e-a573-4acf79c73c0a" />
