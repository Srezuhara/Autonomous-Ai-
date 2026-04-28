"""
main.py — Rich CLI entry point for the AI App Builder.
Usage:
  python main.py "Build a weather dashboard"
  python main.py "Build a todo app" --dry-run
  python main.py --last
"""
import argparse
import logging
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.text import Text
from rich.rule import Rule
from rich.columns import Columns
from rich import box
from rich.live import Live
from rich.align import Align

console = Console()

# Suppress INFO logs — Rich handles the UI
logging.basicConfig(level=logging.WARNING)


# ── Step definitions ───────────────────────────────────────────────────────────

STEPS = [
    (1, "Analyzing intent",      "🔍"),
    (2, "Planning build steps",  "📋"),
    (3, "Designing architecture","🏗️ "),
    (4, "Generating backend",    "⚙️ "),
    (5, "Generating frontend",   "🎨"),
    (6, "Debugging code",        "🐛"),
    (7, "Reviewing quality",     "🔍"),
    (8, "Running tests",         "🧪"),
    (9, "Writing documentation", "📝"),
]


# ── Display helpers ────────────────────────────────────────────────────────────

def print_header():
    console.print()
    console.print(Panel.fit(
        "[bold blue]AI App Builder[/bold blue]\n[dim]Autonomous full-stack app generation[/dim]",
        border_style="blue",
        padding=(1, 4),
    ))
    console.print()


def print_step(step_num: int, label: str, emoji: str, status: str = "running"):
    total = len(STEPS)
    if status == "running":
        console.print(f"  {emoji} [bold cyan][{step_num}/{total}][/bold cyan] {label}...", end="\r")
    elif status == "done":
        console.print(f"  {emoji} [bold cyan][{step_num}/{total}][/bold cyan] {label} [green]✓[/green]     ")
    elif status == "failed":
        console.print(f"  {emoji} [bold cyan][{step_num}/{total}][/bold cyan] {label} [red]✗[/red]     ")


def print_debug_results(debug_results):
    if not debug_results:
        return
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan",
                  title="[bold]Debug Results[/bold]", title_style="cyan")
    table.add_column("File", style="dim", no_wrap=True)
    table.add_column("Status", justify="center")
    table.add_column("Attempts", justify="center")
    table.add_column("Fixes", justify="center")

    for r in debug_results:
        fname = Path(r.file_path).name
        status = "[green]✅ Pass[/green]" if r.success else "[red]❌ Fail[/red]"
        table.add_row(fname, status, str(r.attempts), str(len(r.fixes_applied)))

    console.print(table)


def print_review_results(review_results):
    if not review_results:
        return
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan",
                  title="[bold]Review Results[/bold]", title_style="cyan")
    table.add_column("File", style="dim", no_wrap=True)
    table.add_column("Score", justify="center")
    table.add_column("Summary")

    for r in review_results:
        fname = Path(r.file_path).name
        score = r.score
        color = "green" if score >= 8 else "yellow" if score >= 6 else "red"
        bar = "█" * score + "░" * (10 - score)
        score_text = f"[{color}]{score}/10 {bar}[/{color}]"
        table.add_row(fname, score_text, r.summary[:60] + ("…" if len(r.summary) > 60 else ""))

    console.print(table)


def print_test_results(test_results):
    if not test_results:
        return
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan",
                  title="[bold]Test Results[/bold]", title_style="cyan")
    table.add_column("File", style="dim", no_wrap=True)
    table.add_column("Status", justify="center")
    table.add_column("Passed", justify="center")
    table.add_column("Failed", justify="center")

    for r in test_results:
        fname = Path(r.file_path).name
        if r.skipped:
            status = "[dim]⏭ Skipped[/dim]"
            table.add_row(fname, status, "-", "-")
        else:
            status = "[green]✅ Pass[/green]" if r.failed == 0 and r.tests_generated > 0 else "[red]❌ Fail[/red]"
            table.add_row(fname, status,
                         f"[green]{r.passed}[/green]",
                         f"[red]{r.failed}[/red]" if r.failed else "[dim]0[/dim]")

    console.print(table)


def print_summary(result, elapsed: float):
    debug_passed = sum(1 for r in result.debug_results if r.success)
    debug_total  = len(result.debug_results)
    scores = [r.score for r in result.review_results if r.score]
    avg_score = sum(scores) / len(scores) if scores else 0
    tests_passed = sum(r.passed for r in result.test_results)
    tests_total  = sum(r.tests_generated for r in result.test_results)
    doc_status = "✅ Written" if result.doc_result and not result.doc_result.error else "❌ Failed"

    console.print()
    console.print(Rule("[bold blue]Build Complete[/bold blue]", style="blue"))
    console.print()

    # Summary panel
    status_color = "green" if result.success else "red"
    status_text  = "✅ SUCCESS" if result.success else "❌ FAILED"

    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="bold dim", justify="right")
    summary.add_column()

    summary.add_row("App:", f"[bold]{result.intent.get('app_name', '?')}[/bold]")
    summary.add_row("Type:", result.intent.get("app_type", "?"))
    summary.add_row("Files:", str(len(result.all_files)))
    summary.add_row("Debug:",
        f"[green]{debug_passed}/{debug_total}[/green]" if debug_passed == debug_total
        else f"[yellow]{debug_passed}/{debug_total}[/yellow]")
    summary.add_row("Review:",
        f"[green]{avg_score:.1f}/10[/green]" if avg_score >= 7
        else f"[yellow]{avg_score:.1f}/10[/yellow]")
    summary.add_row("Tests:",
        f"[green]{tests_passed}/{tests_total}[/green]" if tests_passed == tests_total
        else f"[yellow]{tests_passed}/{tests_total}[/yellow]")
    summary.add_row("Docs:", f"[green]{doc_status}[/green]" if "✅" in doc_status else f"[red]{doc_status}[/red]")
    summary.add_row("Time:", f"{elapsed:.1f}s")

    console.print(Panel(
        summary,
        title=f"[bold {status_color}]{status_text}[/bold {status_color}]",
        border_style=status_color,
        padding=(1, 2),
    ))

    # Show generated files
    if result.all_files:
        console.print()
        console.print("[bold dim]Generated files:[/bold dim]")
        for f in result.all_files:
            console.print(f"  [dim]📄[/dim] {f}")

    console.print()


# ── Instrumented pipeline ──────────────────────────────────────────────────────

def run_with_ui(user_prompt: str) -> None:
    """Run the full pipeline with Rich UI feedback."""
    from agents.pipeline import Pipeline

    print_header()
    console.print(Panel(
        f"[italic]\"{user_prompt}\"[/italic]",
        title="[bold]Prompt[/bold]",
        border_style="dim",
        padding=(0, 2),
    ))
    console.print()

    pipeline = Pipeline()
    start = time.time()

    # Monkey-patch pipeline.run to show step progress
    original_run = pipeline.run

    def run_with_steps(prompt):
        from agents import (
            IntentAnalyzer, Planner, Architect,
            BackendDeveloper, FrontendGenerator,
            Debugger, Reviewer, Tester, Documenter,
        )
        from agents.pipeline import BuildResult
        from dataclasses import field

        result = BuildResult(user_prompt=prompt)

        step_agents = [
            (1, "Analyzing intent",       "🔍", lambda: pipeline.intent_analyzer.run(prompt)),
            (2, "Planning build steps",   "📋", lambda: pipeline.planner.run(result.intent)),
            (3, "Designing architecture", "🏗️ ", lambda: pipeline.architect.run(result.intent, result.steps)),
            (4, "Generating backend",     "⚙️ ", lambda: pipeline.backend_developer.run(result.intent, result.architecture)),
            (5, "Generating frontend",    "🎨", lambda: pipeline.frontend_generator.run(result.intent, result.architecture)),
            (6, "Debugging code",         "🐛", lambda: pipeline.debugger.run(result.backend_files)),
            (7, "Reviewing quality",      "🔍", lambda: pipeline.reviewer.run(result.backend_files)),
            (8, "Running tests",          "🧪", lambda: pipeline.tester.run(result.backend_files, result.architecture, result.debug_results)),
            (9, "Writing documentation",  "📝", lambda: pipeline.documenter.run(result.intent, result.architecture, result.backend_files, result.review_results)),
        ]

        attr_map = [
            "intent", "steps", "architecture",
            "backend_files", "frontend_files",
            "debug_results", "review_results", "test_results", "doc_result",
        ]

        try:
            for i, (num, label, emoji, fn) in enumerate(step_agents):
                print_step(num, label, emoji, "running")
                val = fn()
                setattr(result, attr_map[i], val)
                print_step(num, label, emoji, "done")

                # Print sub-results after key steps
                if num == 6:
                    print_debug_results(result.debug_results)
                elif num == 7:
                    print_review_results(result.review_results)
                elif num == 8:
                    print_test_results(result.test_results)

            result.success = True

        except Exception as e:
            result.error = str(e)
            console.print(f"\n[bold red]💥 Pipeline failed:[/bold red] {e}")

        return result

    result = run_with_steps(user_prompt)
    elapsed = time.time() - start
    print_summary(result, elapsed)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="AI App Builder — generate full-stack apps from a prompt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py "Build a weather dashboard"
  python main.py "Build a todo app with user auth"
  python main.py "Build a REST API for a blog"
        """,
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        help="What app to build (in quotes)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be built without generating files",
    )
    parser.add_argument(
        "--last",
        action="store_true",
        help="Show info about the last generated project",
    )

    args = parser.parse_args()

    if args.last:
        _show_last_build()
        return

    if not args.prompt:
        parser.print_help()
        console.print("\n[yellow]Tip:[/yellow] Try: python main.py \"Build a weather dashboard\"\n")
        sys.exit(0)

    if args.dry_run:
        console.print(Panel(
            f"[bold]Dry run:[/bold] would build — [italic]\"{args.prompt}\"[/italic]\n\n"
            f"Steps that would run:\n"
            + "\n".join(f"  {e} [{n}/9] {l}" for n, l, e in STEPS),
            title="[bold yellow]Dry Run[/bold yellow]",
            border_style="yellow",
        ))
        return

    run_with_ui(args.prompt)


def _show_last_build():
    """Show the last generated project directory."""
    import config
    output_dir = Path(config.OUTPUT_DIR)
    if not output_dir.exists():
        console.print("[yellow]No generated projects found.[/yellow]")
        return

    projects = [d for d in output_dir.iterdir() if d.is_dir()]
    if not projects:
        console.print("[yellow]No generated projects found.[/yellow]")
        return

    latest = max(projects, key=lambda d: d.stat().st_mtime)
    console.print(Panel(
        f"[bold]Last project:[/bold] {latest.name}\n"
        f"[dim]Path:[/dim] {latest}\n\n"
        f"[dim]Files:[/dim]\n"
        + "\n".join(f"  📄 {f.relative_to(output_dir)}"
                    for f in latest.rglob("*") if f.is_file() and "__pycache__" not in str(f)),
        title="[bold]Last Build[/bold]",
        border_style="blue",
    ))


if __name__ == "__main__":
    main()
