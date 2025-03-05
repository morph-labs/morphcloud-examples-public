# Instructions

## bash/CLI

```bash
chmod +x openvscode-server_setup.py
./openvscode-server_setup.py
```

```python
uv run openvscode-server_setup.py
```

## info
- sets up OpenVSCode Server in a Docker container
- uses a 4 vcpu 4GB ram and 8GB disk instance
- creates persistent workspace at /home/workspace
- accessible through web browser

## notes
- make sure to export your MORPH_API_KEY into your environment
- uv will automatically pick up the dependencies for you
- alternatively, use uv venv to set up a proper venv for morphcloud

## image
<img width="1792" alt="image" src="https://github.com/user-attachments/assets/40d9286c-74dc-4f37-9aaa-d4a386ef028e" />
