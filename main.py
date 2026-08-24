"""
main.py — Rich CLI entry point for the AI App Builder.
Usage:
  python main.py "Build a weather dashboard"
  python main.py "Build a todo app" --dry-run
  python main.py --last
"""
import argparse
import logging
import os
import re
import sys
import time
from pathlib import Path

# Force UTF-8 stdout encoding to avoid UnicodeEncodeErrors on some terminals
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

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

# Rich handles the UI, so INFO logs are suppressed by default. LOG_LEVEL was
# documented in .env but ignored here, which made it impossible to watch what the
# pipeline was actually doing during a build — set LOG_LEVEL=INFO to see the
# per-step detail (generation, repairs, the runtime smoke test).
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "WARNING").upper(), logging.WARNING)
)


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

# Maps Pipeline's internal step names to the CLI's labels. Keys must match the
# `step_name` values emitted by Pipeline._emit_progress().
_STEP_DISPLAY = {
    "intent_analyzer":    ("Analyzing intent",       "🔍"),
    "planner":            ("Planning build steps",   "📋"),
    "architect":          ("Designing architecture", "🏗️ "),
    "backend_developer":  ("Generating backend",     "⚙️ "),
    "frontend_generator": ("Generating frontend",    "🎨"),
    "frontend_debugger":  ("Checking frontend",      "🩹"),
    "debugger":           ("Debugging code",         "🐛"),
    "reviewer":           ("Reviewing quality",      "🔍"),
    "tester":             ("Running tests",          "🧪"),
    "remediation":        ("Repairing and verifying","🔧"),
    "documenter":         ("Writing documentation",  "📝"),
    "session_context":    ("Writing handoff notes",  "📋"),
}


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

    # Summary panel. Phase 21 gave the pipeline a four-state vocabulary; a
    # binary SUCCESS/FAILED banner reported a quota-paused build that generated
    # zero files as a clean success.
    if getattr(result, "quota_paused", False):
        status_color, status_text = "yellow", "⏸  QUOTA PAUSED"
    elif getattr(result, "degraded", False):
        status_color, status_text = "yellow", "⚠️  DONE (WITH CONTEXT)"
    elif result.success:
        status_color, status_text = "green", "✅ SUCCESS"
    else:
        status_color, status_text = "red", "❌ FAILED"

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
        "[dim]none run[/dim]" if tests_total == 0
        else f"[green]{tests_passed}/{tests_total}[/green]" if tests_passed == tests_total
        else f"[yellow]{tests_passed}/{tests_total}[/yellow]")
    summary.add_row("Docs:", f"[green]{doc_status}[/green]" if "✅" in doc_status else f"[red]{doc_status}[/red]")

    # Phase 22: whether the generated app actually responds.
    smoke = getattr(result, "smoke_summary", "")
    if smoke:
        # Green only when every probed route answered; "1/4 routes responded"
        # is a failing app, not a passing one.
        match = re.match(r"(\d+)/(\d+)", smoke)
        all_ok = bool(match) and match.group(1) == match.group(2)
        summary.add_row(
            "Runtime:",
            f"[green]{smoke}[/green]" if all_ok else f"[yellow]{smoke}[/yellow]",
        )

    reason = getattr(result, "completion_reason", "")
    if reason:
        summary.add_row("Reason:", f"[yellow]{reason}[/yellow]")

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

    start = time.time()

    # The CLI used to re-implement the 9 steps as a flat loop of direct agent
    # calls. That quietly bypassed everything Pipeline.run() adds around those
    # calls — the frontend_debugger step, the forbidden-file purge, the Phase 21
    # self-healing remediation and static audit, the Phase 22 runtime smoke test,
    # and the quota interception that writes SESSION_CONTEXT.md instead of
    # crashing. A CLI build and an API build were running different pipelines.
    #
    # It now drives the real pipeline and renders its progress callbacks.
    _seen_steps: set = set()

    def on_progress(event: dict) -> None:
        name   = event.get("step_name", "")
        status = event.get("status", "")
        num    = event.get("step", 0)

        label, emoji = _STEP_DISPLAY.get(name, (name.replace("_", " ").title(), "•"))

        if status == "running" and (num, name) not in _seen_steps:
            _seen_steps.add((num, name))
            print_step(num, label, emoji, "running")
        elif status == "done":
            print_step(num, label, emoji, "done")
        elif status == "failed":
            print_step(num, label, emoji, "done")

    pipeline = Pipeline(progress_callback=on_progress)
    result   = pipeline.run(user_prompt)

    if result.debug_results:
        print_debug_results(result.debug_results)
    if result.review_results:
        print_review_results(result.review_results)
    if result.test_results:
        print_test_results(result.test_results)

    if result.error:
        console.print(f"\n[bold red]💥 Pipeline failed:[/bold red] {result.error}")
    if getattr(result, "smoke_summary", ""):
        console.print(f"[dim]Runtime check:[/dim] {result.smoke_summary}")
    if getattr(result, "session_context_path", ""):
        console.print(
            f"[yellow]Handoff document written:[/yellow] {result.session_context_path}"
        )
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
