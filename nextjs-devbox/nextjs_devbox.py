#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "morphcloud",
#     "rich",
# ]
# ///
"""
Demo script for using the Morph Computer with Rich console output
"""

from morphcloud.computer import Computer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt
from rich.text import Text

console = Console()

if __name__ == "__main__":
    console.print(
        Panel.fit(
            "[bold blue]Morph Computer Demo[/bold blue]",
            border_style="green",
            subtitle="Running interactive session",
        )
    )

    # Create a spinner for the Computer initialization
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold green]Starting a new Morph Computer...[/bold green]"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Starting...", total=None)
        computer = Computer.new()

    # Use the Computer in a context manager to ensure proper shutdown
    with computer:
        # Display desktop URL
        desktop_url = computer.desktop_url()
        console.print("[bold cyan]🖥️ Remote Desktop URL:[/bold cyan]")
        url_text = Text(f"  {desktop_url}")
        url_text.stylize("bold blue underline")
        console.print(url_text)
        console.print("\n[dim]You can access the desktop UI at this URL[/dim]\n")

        # Wait for user input before continuing
        Prompt.ask("[yellow]Press Enter to continue to the next step[/yellow]")

        # Navigate to a website
        with console.status(
            "[bold green]Navigating to the hackathon website...[/bold green]",
            spinner="dots",
        ):
            computer.browser.goto("https://next-hackathon-2025.vercel.app")
            console.print("[green]✓[/green] Successfully navigated to the website")

        # Start the MCP server
        with console.status(
            "[bold green]Starting MCP server...[/bold green]", spinner="dots"
        ):
            server_url = computer.start_mcp_server(port=8888)
            console.print("[green]✓[/green] MCP server started")

        # Display server information
        console.print("[bold cyan]🔌 MCP Server:[/bold cyan]")
        server_text = Text(f"  {server_url}")
        server_text.stylize("bold blue underline")
        console.print(server_text)
        console.print("\n[dim]Connect your MCP client to this URL[/dim]\n")

        # Wait for user to terminate
        console.print(
            Panel(
                "[bold yellow]Computer is running[/bold yellow]\nPress Ctrl+C to shutdown",
                border_style="yellow",
            )
        )

        try:
            # Keep the script running until user interrupts
            console.input("[dim]Press Enter to shutdown...[/dim]")
        except KeyboardInterrupt:
            pass

        # Shutdown message
        console.print("\n[bold red]Shutting down Computer...[/bold red]")

    console.print(
        "[green]✓[/green] [bold green]Computer successfully shut down[/bold green]"
    )
