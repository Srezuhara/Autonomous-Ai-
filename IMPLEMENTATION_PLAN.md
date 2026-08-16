# Implementation Plan — Resilient Build Refinement & Quota Context Generation

## Problem & Objectives

1. **Self-Healing Code Refinement vs. Hard Aborts**:
   - Currently, `_assert_deployable()` in `agents/pipeline.py` throws `PipelineVerificationError` if debug or test scores are suboptimal, marking the entire build as failed and blocking downloads.
   - **Goal**: Rather than cancelling or failing the project upon low scores, the system should invoke iterative refinement/self-repair mechanisms to restructure and polish the code. If minor issues remain after refinement passes, the build completes with detailed diagnostics and documentation rather than aborting.

2. **API Key / Quota Exhaustion Detection & Context Handoff**:
   - When LLM keys hit daily limits or quota is exhausted mid-build, the process currently aborts with an uncaught runtime error.
   - **Goal**: Gracefully intercept quota limits across all pipeline stages, determine exact completion percentage (steps completed, files created, tests evaluated), and automatically synthesize a comprehensive `BUILD_CONTEXT.md` / `SESSION_CONTEXT.md` in the project directory detailing:
     - Exact state of the project and files generated so far.
     - Completed vs. remaining architectural requirements.
     - Step-by-step instructions to resume or finalize the build manually or upon key renewal.

---

## User Review Required

> [!IMPORTANT]
> **No More Destructive Aborts**: Low test or debug scores will trigger active code remediation passes instead of failing the pipeline. The documenter and packaging will always execute to ensure usable output.
>
> **Quota Safeguard**: If keys run out mid-build, the pipeline will package the work-in-progress files alongside an auto-generated `BUILD_CONTEXT.md` so work is never lost.

---

## Proposed Changes

### Component 1: Pipeline & Self-Repair Orchestration (`agents/pipeline.py`)

#### [MODIFY] [pipeline.py](file:///c:/programes/comppython/Aiautonomous/agents/pipeline.py)
- **Replace Hard Assertion with Self-Healing Passes**:
  - Replace `_assert_deployable()` with `_refine_and_remediate(result)`.
  - If backend debugger detects remaining import issues, invoke a targeted structural repair pass.
  - If reviewer gives low scores, run a focused code enhancement pass before testing.
- **Quota Interception & Graceful Handoff**:
  - Wrap pipeline step execution to catch `GroqDailyQuotaError` and key exhaustion exceptions.
  - On quota detection:
    - Compute exact progress percentage and completed steps.
    - Invoke `Documenter.generate_session_context()` to write `SESSION_CONTEXT.md` with step-by-step next actions.
    - Mark build status as `quota_paused` or `done_with_context` so the project files and context can be downloaded and inspected.

---

### Component 2: Quota & Key Exhaustion Detection (`llm_client.py`)

#### [MODIFY] [llm_client.py](file:///c:/programes/comppython/Aiautonomous/llm_client.py)
- Enhance `is_quota_exhausted()` helper to allow the pipeline to proactively check key availability before launching heavy steps.
- Ensure `GroqDailyQuotaError` provides rich metadata (model, keys attempted, remaining available keys).

---

### Component 3: Session Context & Handoff Generator (`agents/documenter.py`)

#### [MODIFY] [documenter.py](file:///c:/programes/comppython/Aiautonomous/agents/documenter.py)
- Add `generate_session_context(intent, architecture, backend_files, frontend_files, completed_steps, pending_steps, error_or_reason)`:
  - Generates a standalone markdown file (`SESSION_CONTEXT.md` / `BUILD_CONTEXT.md`) inside the project root directory.
  - Lists:
    - 📊 Progress summary & percent completed.
    - 📁 Generated files and their current health/verification status.
    - 🛠️ Step-by-step guide on what code to add/fix next.
    - 🚀 How to run, test, and complete the project.

---

### Component 4: API Platform & Downloads Route (`api_platform/runner.py` & `api_platform/routes/downloads.py`)

#### [MODIFY] [runner.py](file:///c:/programes/comppython/Aiautonomous/api_platform/runner.py)
- Support graceful completion states and ensure project scores and progress logs are saved.

#### [MODIFY] [downloads.py](file:///c:/programes/comppython/Aiautonomous/api_platform/routes/downloads.py)
- Allow downloading projects that completed with context or partial status, ensuring users never lose access to their generated code and instructions.

---

## Verification Plan

### Automated Tests
- Run `python test_phase17.py` to confirm API regression test suite passes.
- Unit test quota interruption simulation to verify `SESSION_CONTEXT.md` is properly generated.
- Unit test low-score scenario to ensure pipeline applies remediation rather than raising fatal errors.

### Manual Verification
- Trigger a build simulation with mock rate limit to verify `SESSION_CONTEXT.md` creation and file packaging.
