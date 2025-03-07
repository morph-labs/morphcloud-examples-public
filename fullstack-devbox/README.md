# Instructions

## TypeScript/Node.js
```bash
# Download and install Bun (if you don't have it)
curl -fsSL https://bun.sh/install | bash
# Update to latest stable release
bun upgrade

# Run the setup script
bun run setup.ts  # Sets up a Bun development environment with Todo app
```

## info
- sets up a Bun development environment on a Morph Cloud VM
- includes Docker and PostgreSQL for backend development
- provides a Todo app with React and HMR
- uses a 1 vcpu 1GB ram and 4GB disk instance
- accessible through web browser with exposed HTTP services

## notes
- make sure to export your MORPH_API_KEY into your environment
- automatically creates and copies over the right files for you
- takes advantage of snapshot caching for faster setup
- connects to PostgreSQL with URL: postgres://postgres:postgres@localhost:5432/postgres
- supports Claude Code integration for AI-assisted development
- environment includes Bun's hot module reloading for fast frontend iteration

## image
<img width="1792" alt="bunbox demo" src="[URL TO SCREENSHOT]" />