"""
tools/verification.py — "not checked" is not "checked and clean"
================================================================

Every verifier in this pipeline used to answer with a plain `list[str]` of
findings, and an empty list meant four different things:

  * the check ran and the artifact is good;
  * the check does not apply to this build shape;
  * the check could not run (no entry point, a crashed step, a timeout);
  * the check ran and found nothing because there was nothing to look at —
    an app that boots and declares **zero routes** returned `[]` and was
    reported as a clean run.

`Pipeline._smoke_test_runtime` returned `[]` for all four. Downstream,
`report.unresolved` could not tell them apart, so a build nobody had verified
and a build that passed verification were the same value. That is the mechanism
behind every "empty build" that shipped with a healthy status: matrix row 4
finished `done_with_context` with a valid ZIP, and its primary artifact — a CLI
tool — was never executed by anything.

A `VerificationOutcome` makes the distinction explicit and un-loseable. A
verifier returns one; nothing returns a bare list. `NOT_RUN` is not silence, and
it is never counted as a pass.

Deterministic and free — no LLM, no tokens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


#: Checks that RUN the artifact, as opposed to reading it.
#:
#: Membership is the difference between "the code looks right" and "the thing
#: works", and only the second is evidence. Adding a check here is a claim that
#: it executes something — a static analyser must never be listed.
EXECUTING_CHECKS = frozenset({
    "runtime_smoke",     # HTTP-probes every declared route
    "cli_smoke",         # runs each entry point's --help and subcommands
    "package_smoke",     # imports the package as a user would
    "generated_tests",   # runs the suite the build ships
})


class Status(str, Enum):
    """
    Why NOT_APPLICABLE and NOT_RUN are different.

    NOT_APPLICABLE is a *decision*: this build has no frontend, so the frontend
    check has nothing to say, and that is a complete and correct answer.

    NOT_RUN is an *absence*: the check should have had something to say and did
    not get to speak. A missing entry point, a crashed tester step, a timeout.
    It is the state the old empty list was hiding, and it must never be read as
    success — the whole point of separating them is that NOT_RUN is a hole in
    the evidence, and a hole is not a pass.
    """

    VERIFIED       = "verified"
    NOT_APPLICABLE = "not_applicable"
    NOT_RUN        = "not_run"
    FAILED         = "failed"


@dataclass
class VerificationOutcome:
    """
    What one verifier did, and what it found.

    `check`    — which verifier ("runtime_smoke", "cli_smoke", …)
    `shape`    — the build shape it was verifying ("web_api", "cli", …)
    `detail`   — what was actually executed, in the operator's words. This is
                 the field that answers "how do you know?", and it is what the
                 old `[]` could never carry.
    `findings` — the problems, in the form the pipeline already reports them.
    `evidence` — structured facts a later step can act on (route counts, exit
                 codes, the entry point used).
    """

    check:     str
    status:    Status
    shape:     str = ""
    detail:    str = ""
    findings:  list[str] = field(default_factory=list)
    evidence:  dict = field(default_factory=dict)

    # ── Constructors, so call sites read as statements of fact ───────────────

    @classmethod
    def verified(cls, check: str, detail: str = "", **kw) -> "VerificationOutcome":
        return cls(check=check, status=Status.VERIFIED, detail=detail, **kw)

    @classmethod
    def not_applicable(cls, check: str, detail: str = "", **kw) -> "VerificationOutcome":
        return cls(check=check, status=Status.NOT_APPLICABLE, detail=detail, **kw)

    @classmethod
    def not_run(cls, check: str, detail: str = "", **kw) -> "VerificationOutcome":
        return cls(check=check, status=Status.NOT_RUN, detail=detail, **kw)

    @classmethod
    def failed(cls, check: str, findings: list[str], detail: str = "", **kw
               ) -> "VerificationOutcome":
        return cls(check=check, status=Status.FAILED, detail=detail,
                   findings=list(findings), **kw)

    # ── Reading ──────────────────────────────────────────────────────────────

    @property
    def ok(self) -> bool:
        """
        True only for a check that ran and passed, or one that genuinely does
        not apply.

        NOT_RUN is deliberately excluded. A build whose verification never ran
        has not been shown to work, and treating the two alike is the bug this
        module exists to remove.
        """
        return self.status in (Status.VERIFIED, Status.NOT_APPLICABLE)

    @property
    def is_evidence_of_working(self) -> bool:
        """
        Stricter than `ok`: did this check actually execute the artifact and
        find it sound?

        `ok` answers "is there anything to report"; this answers "do we have
        positive evidence". NOT_APPLICABLE passes the first and fails the
        second, which is what the terminal-status decision needs — a build with
        no evidence at all should not be called verified.

        **VERIFIED is not enough on its own.** Half the checks never run the
        thing they inspect: `feature_coverage`, `web_assets`, `schema_attr` and
        `sql_schema` read the source and nothing else. A green static check says
        the code looks right, which is exactly the claim this property must not
        make — 27 of the 41 saved builds have a verified static check and no
        verified executing one, and two of them (`project`, `todo_app`) passed
        the row criterion on `sql_schema` alone, with nothing having run.

        That is the defect this whole phase exists to remove, one level up: not
        an empty list meaning four things, but a verdict meaning "inspected"
        while it is read as "executed".
        """
        return self.status is Status.VERIFIED and self.check in EXECUTING_CHECKS

    @property
    def is_fatal(self) -> bool:
        """
        Did this check find that the artifact does not run at all?

        The `unusable` verdict used to be decided by substring-matching finding
        text — "declares no routes", "fails on `--help`". Reword a finding and
        the verdict silently stops firing, which is the same class of defect as
        an empty list meaning four things: the signal lives in prose that
        nothing guarantees. A verifier that knows the artifact is dead says so
        here, in a field.
        """
        return bool(self.evidence.get("fatal"))

    def mark_fatal(self, reason: str) -> "VerificationOutcome":
        """Record that this finding means the artifact does not run."""
        self.evidence["fatal"] = True
        self.evidence.setdefault("fatal_reasons", []).append(reason)
        return self

    def summary(self) -> str:
        head = f"{self.check}: {self.status.value}"
        if self.shape:
            head += f" [{self.shape}]"
        if self.detail:
            head += f" — {self.detail}"
        return head

    def to_dict(self) -> dict:
        return {
            "check":    self.check,
            "status":   self.status.value,
            "shape":    self.shape,
            "detail":   self.detail,
            "findings": list(self.findings),
            "evidence": dict(self.evidence),
        }


def collect_findings(outcomes: list[VerificationOutcome]) -> list[str]:
    """
    Every finding across a set of outcomes, plus an explicit line for each check
    that never ran.

    The NOT_RUN line is the point: it puts "we do not know" into the same list
    the pipeline already reports, so an unverified build reads as unverified
    instead of disappearing.
    """
    out: list[str] = []
    for o in outcomes:
        out.extend(o.findings)
        if o.status is Status.NOT_RUN:
            reason = o.detail or "no reason recorded"
            out.append(f"{o.check} did not run, so this build is unverified: {reason}")
    return out


def worst_status(outcomes: list[VerificationOutcome]) -> Status:
    """FAILED beats NOT_RUN beats VERIFIED beats NOT_APPLICABLE."""
    order = [Status.FAILED, Status.NOT_RUN, Status.VERIFIED, Status.NOT_APPLICABLE]
    for status in order:
        if any(o.status is status for o in outcomes):
            return status
    return Status.NOT_APPLICABLE
