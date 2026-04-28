"""
agents/pipeline.py — Full 9-step build pipeline.
Enhanced with build IDs and progress callbacks for Stage 2.
"""
import logging
from uuid import uuid4
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict

from agents.intent_analyzer import IntentAnalyzer
from agents.planner import Planner
from agents.architect import Architect
from agents.backend_developer import BackendDeveloper
from agents.frontend_generator import FrontendGenerator
from agents.debugger import Debugger, FileDebugResult
from agents.reviewer import Reviewer, ReviewResult
from agents.tester import Tester, TestResult
from agents.documenter import Documenter, DocResult

logger = logging.getLogger(__name__)


@dataclass
class BuildResult:
    user_prompt:    str
    build_id:       str   = field(default_factory=lambda: str(uuid4())[:8])
    intent:         dict  = field(default_factory=dict)
    steps:          list  = field(default_factory=list)
    architecture:   dict  = field(default_factory=dict)
    backend_files:  list  = field(default_factory=list)
    frontend_files: list  = field(default_factory=list)
    debug_results:  list  = field(default_factory=list)
    review_results: list  = field(default_factory=list)
    test_results:   list  = field(default_factory=list)
    doc_result:     Optional[DocResult] = None
    success:        bool  = False
    error:          str   = ""
    started_at:     datetime = field(default_factory=datetime.now)
    completed_at:   Optional[datetime] = None
    current_step:   int   = 0  # Track current step (1-9)

    @property
    def all_files(self):
        return self.backend_files + self.frontend_files
    
    @property
    def duration_seconds(self) -> float:
        """Calculate build duration in seconds."""
        if not self.completed_at:
            return (datetime.now() - self.started_at).total_seconds()
        return (self.completed_at - self.started_at).total_seconds()
    
    def complete(self, success: bool):
        """Mark build as complete."""
        self.success = success
        self.completed_at = datetime.now()

    def summary(self) -> str:
        debug_passed = sum(1 for r in self.debug_results if r.success)
        scores = [r.score for r in self.review_results if r.score]
        avg_score = sum(scores) / len(scores) if scores else 0
        total_tests  = sum(r.tests_generated for r in self.test_results)
        tests_passed = sum(r.passed for r in self.test_results)
        doc_status = str(self.doc_result) if self.doc_result else "not run"

        lines = [
            f"\n{'='*50}",
            f"  BUILD RESULT: {'✅ SUCCESS' if self.success else '❌ FAILED'}",
            f"{'='*50}",
            f"  Build ID:   {self.build_id}",
            f"  App:        {self.intent.get('app_name', '?')}",
            f"  Type:       {self.intent.get('app_type', '?')}",
            f"  Complexity: {self.intent.get('complexity', '?')}",
            f"  Files:      {len(self.all_files)}",
            f"  Debug:      {debug_passed}/{len(self.debug_results)} passing",
            f"  Review:     {avg_score:.1f}/10 avg score",
            f"  Tests:      {tests_passed}/{total_tests} passing",
            f"  Docs:       {doc_status}",
            f"  Duration:   {self.duration_seconds:.1f}s",
            f"{'='*50}",
        ]
        if self.all_files:
            lines.append("  Generated files:")
            for f in self.all_files:
                lines.append(f"    📄 {f}")
        if self.debug_results:
            lines.append("\n  Debug results:")
            for r in self.debug_results:
                lines.append(f"    {r}")
        if self.review_results:
            lines.append("\n  Review results:")
            for r in self.review_results:
                lines.append(f"    {r}")
        if self.test_results:
            lines.append("\n  Test results:")
            for r in self.test_results:
                lines.append(f"    {r}")
        if self.error:
            lines.append(f"\n  ❌ Error: {self.error}")
        lines.append(f"{'='*50}\n")
        return "\n".join(lines)


class Pipeline:
    def __init__(self, build_id: str = None, progress_callback: Callable = None):
        """
        Initialize pipeline with optional build ID and progress callback.
        
        Args:
            build_id: Unique build identifier (auto-generated if not provided)
            progress_callback: Function to call with progress updates
                              callback(progress: Dict) where progress contains:
                              {
                                  "build_id": str,
                                  "step": int,
                                  "step_name": str,
                                  "status": "running" | "done" | "failed",
                                  "timestamp": str (ISO format),
                                  "data": dict (optional step-specific data)
                              }
        """
        self.build_id = build_id or str(uuid4())[:8]
        self.progress_callback = progress_callback
        
        self.intent_analyzer    = IntentAnalyzer()
        self.planner            = Planner()
        self.architect          = Architect()
        self.backend_developer  = BackendDeveloper()
        self.frontend_generator = FrontendGenerator()
        self.debugger           = Debugger()
        self.reviewer           = Reviewer()
        self.tester             = Tester()
        self.documenter         = Documenter()

    def _emit_progress(self, step: int, step_name: str, status: str, data: Dict = None):
        """Emit progress event to callback if registered."""
        if self.progress_callback:
            self.progress_callback({
                "build_id": self.build_id,
                "step": step,
                "step_name": step_name,
                "status": status,  # "running" | "done" | "failed"
                "timestamp": datetime.now().isoformat(),
                "data": data or {},
            })

    def run(self, user_prompt: str) -> BuildResult:
        result = BuildResult(user_prompt=user_prompt, build_id=self.build_id)
        
        try:
            # Step 1: Intent Analysis
            result.current_step = 1
            self._emit_progress(1, "intent_analyzer", "running")
            logger.info("🔍 [1/9] Analyzing intent...")
            result.intent = self.intent_analyzer.run(user_prompt)
            self._emit_progress(1, "intent_analyzer", "done", {"intent": result.intent})

            # Step 2: Planning
            result.current_step = 2
            self._emit_progress(2, "planner", "running")
            logger.info("📋 [2/9] Planning build steps...")
            result.steps = self.planner.run(result.intent)
            self._emit_progress(2, "planner", "done", {"steps_count": len(result.steps)})

            # Step 3: Architecture
            result.current_step = 3
            self._emit_progress(3, "architect", "running")
            logger.info("🏗️  [3/9] Designing architecture...")
            result.architecture = self.architect.run(result.intent, result.steps)
            self._emit_progress(3, "architect", "done", {
                "files_count": len(result.architecture.get("files", []))
            })

            # Step 4: Backend Development
            result.current_step = 4
            self._emit_progress(4, "backend_developer", "running")
            logger.info("⚙️  [4/9] Generating backend code...")
            result.backend_files = self.backend_developer.run(result.intent, result.architecture)
            self._emit_progress(4, "backend_developer", "done", {
                "files_generated": len(result.backend_files)
            })

            # Step 5: Frontend Development
            result.current_step = 5
            self._emit_progress(5, "frontend_generator", "running")
            logger.info("🎨 [5/9] Generating frontend code...")
            result.frontend_files = self.frontend_generator.run(result.intent, result.architecture)
            self._emit_progress(5, "frontend_generator", "done", {
                "files_generated": len(result.frontend_files)
            })

            # Step 6: Debugging
            result.current_step = 6
            self._emit_progress(6, "debugger", "running")
            logger.info("🐛 [6/9] Running autonomous debugger...")
            result.debug_results = self.debugger.run(result.backend_files)
            passed = sum(1 for r in result.debug_results if r.success)
            self._emit_progress(6, "debugger", "done", {
                "passed": passed,
                "total": len(result.debug_results)
            })

            # Step 7: Code Review
            result.current_step = 7
            self._emit_progress(7, "reviewer", "running")
            logger.info("🔍 [7/9] Reviewing code quality...")
            result.review_results = self.reviewer.run(result.backend_files)
            scores = [r.score for r in result.review_results if r.score]
            avg_score = sum(scores) / len(scores) if scores else 0
            self._emit_progress(7, "reviewer", "done", {
                "avg_score": avg_score,
                "files_reviewed": len(result.review_results)
            })

            # Step 8: Testing
            result.current_step = 8
            self._emit_progress(8, "tester", "running")
            logger.info("🧪 [8/9] Generating and running tests...")
            result.test_results = self.tester.run(
                result.backend_files,
                result.architecture,
                debug_results=result.debug_results,
            )
            tests_passed = sum(r.passed for r in result.test_results)
            tests_total = sum(r.tests_generated for r in result.test_results)
            self._emit_progress(8, "tester", "done", {
                "passed": tests_passed,
                "total": tests_total
            })

            # Step 9: Documentation
            result.current_step = 9
            self._emit_progress(9, "documenter", "running")
            logger.info("📝 [9/9] Generating documentation...")
            result.doc_result = self.documenter.run(
                result.intent,
                result.architecture,
                result.backend_files,
                review_results=result.review_results,
            )
            self._emit_progress(9, "documenter", "done", {
                "readme_path": result.doc_result.readme_path if result.doc_result else None
            })

            result.complete(success=True)

        except Exception as e:
            result.error = str(e)
            result.complete(success=False)
            self._emit_progress(result.current_step, "error", "failed", {"error": str(e)})
            logger.error(f"💥 Pipeline failed: {e}", exc_info=True)

        return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Example with progress callback
    def on_progress(progress):
        print(f"[{progress['step']}/9] {progress['step_name']}: {progress['status']}")
    
    pipeline = Pipeline(progress_callback=on_progress)
    result = pipeline.run(
        "Build a weather dashboard that shows temperature, humidity and a 5-day forecast"
    )
    print(result.summary())
