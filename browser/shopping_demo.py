# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "browser-use",
#     "langchain-anthropic",
#     "morphcloud",
#     "aiohttp",
#     "rich"
# ]
# ///

import asyncio
import csv
import json
import os
import pathlib
import webbrowser
from datetime import datetime
from typing import List

from pydantic import BaseModel
from rich.console import Console

# Disable browser-use telemetry
os.environ["ANONYMIZED_TELEMETRY"] = "false"

from browser_use import Agent, Browser, BrowserConfig, Controller
from langchain_anthropic import ChatAnthropic
from morph_browser import MorphBrowser  # Import the MorphBrowser
from morphcloud.api import \
    MorphCloudClient  # Import MorphCloudClient - needed for user setup function

client = MorphCloudClient()
console = Console()


class BookOutput(BaseModel):
    book_title: str
    book_url: str


def write_results_to_csv(
    book_title: str, result_data: dict, csv_file: str = "amazon_books_results.csv"
):
    """Write book processing results to CSV file"""
    file_exists = pathlib.Path(csv_file).exists()

    with open(csv_file, "a", newline="", encoding="utf-8") as f:
        fieldnames = ["book_title", "timestamp", "book_url", "success"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)

        if not file_exists:
            writer.writeheader()

        writer.writerow(
            {
                "book_title": book_title,
                "timestamp": result_data["timestamp"],
                "book_url": result_data.get("book_url", ""),
                "success": result_data.get("success", False),
            }
        )


async def process_books_distributed(
    books: list[str], max_parallel: int = 3, logged_in_snapshot_id="amazon-logged-in"
):  # Pass snapshot ID
    """Process books using one VM per book, up to max_parallel VMs at once, using MorphBrowser"""

    total_books = len(books)
    books_processed = 0

    # Create async queue
    work_queue = asyncio.Queue()
    for book in books:
        work_queue.put_nowait(book)

    model = ChatAnthropic(model="claude-3-5-sonnet-20240620")
    controller = Controller()

    # Dictionary to store results for each book
    results_log = {}

    # Initialize CSV file with header
    with open("amazon_books_results.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["book_title", "timestamp", "book_url", "success"]
        )
        writer.writeheader()

    async def process_book(worker_id: int):
        """Process books one at a time until queue is empty, using MorphBrowser instance"""
        nonlocal books_processed

        while not work_queue.empty():
            book = await work_queue.get()
            history = None  # Initialize history to None for error case
            try:
                console.print(
                    f"[blue]Worker {worker_id}: Starting work on book {books_processed + 1}/{total_books}: '{book}'[/blue]"
                )

                # Use MorphBrowser.create with the logged-in snapshot
                async with await MorphBrowser.create(
                    snapshot_id=logged_in_snapshot_id
                ) as browser_instance:
                    browser = Browser(
                        config=BrowserConfig(
                            cdp_url=browser_instance.cdp_url  # Get CDP URL from MorphBrowser
                        )
                    )

                    console.print(
                        f"[yellow]Worker {worker_id}: Processing '{book}'[/yellow]"
                    )
                    agent = Agent(
                        browser=browser,
                        task=f"Find '{book}' on Amazon. Avoid audiobooks, movies, and series. Go straight to the product page, select either hardcover or paperback, then click on 'add to list', and done.",
                        llm=model,
                        controller=controller,
                        use_vision=False,
                    )

                    history = (
                        await agent.run()
                    )  # history is now assigned if agent.run() is successful
                    urls = history.urls()
                    last_url = (
                        urls[-1] if len(urls) >= 1 else (urls[0] if urls else None)
                    )
                    book_result = {
                        "timestamp": datetime.now().isoformat(),
                        "book_url": last_url,
                        "success": True,
                    }
                    results_log[book] = book_result

                    # Write to CSV immediately
                    write_results_to_csv(book, book_result)

                    books_processed += 1
                    console.print(
                        f"[green]Worker {worker_id}: Processed '{book}' ({books_processed}/{total_books} completed)[/green]"
                    )
                    console.print(
                        f"[green]Worker {worker_id}: Results for '{book}' saved to CSV[/green]"
                    )

            except Exception as e:
                # Log errors in the results dictionary, including more details if history is available
                error_details = {"error": str(e), "success": False}
                if history:  # Check if history is defined before accessing it
                    error_details.update(
                        {
                            "urls": history.urls(),
                            "screenshots": history.screenshots(),
                            "action_names": history.action_names(),
                            "model_actions": history.model_actions(),
                            "action_results": [
                                result.model_dump()
                                for result in history.action_results()
                            ],
                            "extracted_content": history.extracted_content(),
                            "final_result": history.final_result(),
                            "is_done": history.is_done(),
                            "is_successful": history.is_successful(),
                            "has_errors": history.has_errors(),
                            "errors": history.errors(),
                            "number_of_steps": history.number_of_steps(),
                            "total_duration_seconds": history.total_duration_seconds(),
                            "total_input_tokens": history.total_input_tokens(),
                            "model_thoughts": [
                                thought.model_dump()
                                for thought in history.model_thoughts()
                            ],
                        }
                    )
                book_error_result = {
                    "timestamp": datetime.now().isoformat(),
                    **error_details,
                }
                results_log[book] = book_error_result

                # Write error to CSV as well
                write_results_to_csv(book, book_error_result)

                console.print(f"[red]Error processing {book}: {e}[/red]")
                console.print(f"[red]Error for '{book}' saved to CSV[/red]")
            finally:
                work_queue.task_done()
                console.print(
                    f"[blue]Worker {worker_id}: Finished with '{book}', {total_books - books_processed} books remaining[/blue]"
                )

                # Save logs after each book to prevent data loss
                with open("amazon_books_results.json", "w") as f:
                    json.dump(results_log, f, indent=2, default=str)

    console.print(
        f"[bold]Starting processing of {total_books} books using {max_parallel} workers[/bold]"
    )

    # Launch workers up to max_parallel
    workers = [process_book(i) for i in range(max_parallel)]
    await asyncio.gather(*workers)

    # Final save of the results
    with open("amazon_books_results.json", "w") as f:
        json.dump(results_log, f, indent=2, default=str)

    console.print(
        f"[bold green]Completed processing {books_processed}/{total_books} books[/bold green]"
    )
    console.print(
        f"[bold green]Results saved to amazon_books_results.csv and amazon_books_results.json[/bold green]"
    )


async def setup_browser_for_amazon_login():
    """Creates a fresh browser instance for user login to Amazon and snapshotting."""
    initial_url = "https://www.amazon.com/gp/sign-in.html"  # Amazon login URL
    prompt = "Please log in to Amazon.com in the browser window."
    completion_prompt = (
        "close the tab after you have logged in and the Amazon homepage is loaded..."
    )

    console.print(f"[bold yellow]{prompt}[/bold yellow]")
    console.print(
        f"[bold green]Browser with VNC access will open. {completion_prompt}[/bold green]"
    )

    async with await MorphBrowser.create(initial_url=initial_url) as browser_instance:
        vnc_url = browser_instance.vnc_url
        browser_url = browser_instance.cdp_url
        vnc_viewer_url = f"{vnc_url}/vnc_lite.html"

        console.print(f"\nInstance ID: {browser_instance.instance.id}")
        console.print(f"Browser URL (CDP): {browser_url}")
        console.print(f"VNC desktop access: {vnc_url}")

        # Try to automatically open the browser
        try:
            if webbrowser.open(vnc_viewer_url):
                console.print(
                    "[green]VNC viewer opened in your default browser[/green]"
                )
            else:
                raise Exception("Failed to open browser automatically")
        except Exception as e:
            console.print("[yellow]Couldn't automatically open the browser.[/yellow]")
            console.print(
                f"[white]Please copy and paste this URL into your browser to complete setup:[/white]"
            )
            console.print(f"[blue]{vnc_viewer_url}[/blue]")

        # Wait for user confirmation
        input("\nPress Enter once you've completed the login process...")

        console.print(
            "[yellow]Creating snapshot of logged-in browser state...[/yellow]"
        )
        snapshotted_browser = await browser_instance.snapshot(digest="amazon-logged-in")
        console.print(
            f"[green]Snapshot 'amazon-logged-in' created with ID: {snapshotted_browser.snapshot_id}[/green]"
        )
        return snapshotted_browser.snapshot_id


async def main():

    books = []
    with open("books.csv", newline="", encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            if row:
                books.append(", ".join(row).strip())

    console.print(f"[bold]Loaded {len(books)} books to process[/bold]")

    # --- User Setup Section ---
    perform_user_setup = True  # Set to True to perform user login setup, False to skip and use existing snapshot
    logged_in_snapshot_id = "amazon-logged-in"  # Default snapshot ID

    if perform_user_setup:
        console.print(
            "[bold yellow]Starting user setup for Amazon login...[/bold yellow]"
        )
        logged_in_snapshot_id = await setup_browser_for_amazon_login()  # Run user setup
        console.print(
            f"[bold green]User setup complete. Snapshot ID for logged-in state: {logged_in_snapshot_id}[/bold green]"
        )
    else:
        console.print(
            f"[bold blue]Using existing snapshot ID for logged-in state: {logged_in_snapshot_id}[/bold blue]"
        )
        # Ensure snapshot exists or handle case where it might not

    console.print(f"[bold]Using up to 3 parallel instances for book processing[/bold]")

    await process_books_distributed(
        books,
        max_parallel=3,  # Adjust as needed
        logged_in_snapshot_id=logged_in_snapshot_id,  # Pass the snapshot ID to book processing
    )


if __name__ == "__main__":
    asyncio.run(main())
