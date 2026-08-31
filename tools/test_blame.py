"""
Which side of a failing test is actually broken (Phase 23, §4.30).

When a generated test fails, the pipeline repairs something — and it repairs in
two directions at once, without consulting any evidence about which side failed:

  * `Tester._test_file` rewrites the TEST (up to MAX_TEST_FIXES times). Right
    when the test is wrong. When the SOURCE is wrong it is worse than wasted: a
    test rewritten to match buggy behaviour removes the only signal the bug
    exists. `accept_test_reply` stops a repair deleting failing tests, but an
    assertion edited to expect the wrong value passes that guard cleanly.
  * `Pipeline._diagnose` hands `TestResult.file_path` — the SOURCE — to the
    debugger. Right when the source is wrong, wasted when the test is.

The discriminator is the *deepest frame of the traceback*: where the exception
was finally raised. It has to be the frame rather than the file being imported,
because the two disagree in exactly the cases that matter —
`ai_report_generator` fails with `NameError: name 'List' is not defined` while
importing a test, but it is raised inside the source, and that is a real defect.
Row 2's `conn.close()` on the `None` returned by `init_db()` is raised in the
fixture, and that is a test defect.

Measured across every saved build before this was wired to anything: 61 of 104
failures were raised in source files, 43 in test files, and 6 of 19 failing
builds had every failure on the test side.

**Assertions are deliberately not decisive.** 22 of those 43 test-side failures
were `AssertionError`, and an assertion always executes in the test file — but
the expectation can be right and the code wrong. Calling those "test defects"
would license exactly the mistake this module exists to prevent, so they are
AMBIGUOUS and both repairs stay allowed.

Anything unparseable is AMBIGUOUS too, and an unreadable report leaves both
flags False so every caller falls through to the behaviour it had before. That
rule is not decoration: the first version of the study behind this module
returned an empty list both for "the suite passed" and for "it failed and I
could not read why", and scored ten broken suites as passing.

Pure, deterministic, zero-token. Never raises.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "Blame", "FailureBlame", "BlameReport", "classify_pytest_output",
    "is_test_path",
]


class Blame(str, Enum):
    TEST_DEFECT = "test_defect"
    SOURCE_DEFECT = "source_defect"
    AMBIGUOUS = "ambiguous"


#: Exceptions that mean "the assertion did not hold", not "the test is broken".
#: pytest rewrites asserts, so a plain `assert` surfaces as AssertionError.
_ASSERTION_EXCEPTIONS = {"AssertionError", "Failed", "XFailed"}

# Two traceback formats reach this module, and only one of them was obvious.
#
#   --tb=long / --tb=auto (what `Tester._run_pytest_single` actually uses):
#       tests/test_api.py:27: in reset_db          <- intermediate frame
#       tests/test_api.py:6: AttributeError        <- deepest frame + exception
#
#   --tb=native (what a plain traceback looks like):
#       File "tests/test_api.py", line 6, in reset_db
#
# The first version of this module parsed only the second, so against the
# pipeline's real output it attributed nothing and silently changed no
# behaviour. It failed safe, but it also did nothing — which is why it was run
# against the corpus before it was wired to anything.
_FRAME_NATIVE = re.compile(r'^\s*File "([^"]+)", line (\d+)', re.M)
_FRAME_LONG = re.compile(
    r"^(?P<path>[^\s:][^:]*\.py):(?P<line>\d+):\s*(?P<tail>.*)$", re.M
)

#: The block separators pytest prints between failures/errors.
_BLOCK = re.compile(r"\n(?=_{5,} |={5,} |E?_{3,}\s)")

#: `SomeError: message` at the start of a line, or pytest's `E   SomeError:`.
_EXC_LINE = re.compile(
    r"^(?:E\s+)?([A-Za-z_][\w.]*(?:Error|Exception|Failed|Warning))\b"
)


def is_test_path(path: str) -> bool:
    """True when this file is part of the test suite rather than the product."""
    if not path:
        return False
    low = path.replace("\\", "/").lower()
    name = low.rsplit("/", 1)[-1]
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
        or "/tests/" in low
        or "/test/" in low
    )


@dataclass
class FailureBlame:
    """One failing test, and which side of it the exception came from."""
    verdict: Blame
    exception: str = ""
    frame: str = ""
    test_id: str = ""

    def __str__(self) -> str:
        where = self.frame or "unknown"
        return f"{self.verdict.value}: {self.exception or '?'} at {where}"


@dataclass
class BlameReport:
    """Every failure in one pytest run, classified."""
    failures: list = field(default_factory=list)

    @property
    def has_source_defect(self) -> bool:
        """
        At least one failure is a genuine defect in the code under test.

        The gate on rewriting the test: doing so would adapt the suite to a real
        bug. False for an empty or unreadable report, which is what keeps a
        parse failure from changing behaviour.
        """
        return any(f.verdict is Blame.SOURCE_DEFECT for f in self.failures)

    @property
    def all_test_defects(self) -> bool:
        """
        Every failure is decisively a defect in the test itself.

        The gate on repairing the source: there is nothing there to repair.
        Requires at least one failure, and no ambiguity anywhere — one
        unreadable failure is enough to fall back to repairing both sides.
        """
        return bool(self.failures) and all(
            f.verdict is Blame.TEST_DEFECT for f in self.failures
        )

    def counts(self) -> dict:
        out = {b: 0 for b in Blame}
        for f in self.failures:
            out[f.verdict] += 1
        return {b.value: n for b, n in out.items()}

    def summary(self) -> str:
        if not self.failures:
            return "no failures could be attributed"
        c = self.counts()
        return (
            f"{len(self.failures)} failure(s): "
            f"{c['source_defect']} in the code under test, "
            f"{c['test_defect']} in the test itself, "
            f"{c['ambiguous']} could go either way"
        )


def _frames_of(block: str) -> list:
    """
    Every frame in this failure, in call order, as (path, trailing-text).

    Handles both traceback styles. `trailing` is what pytest printed after the
    line number: "in some_function" for an intermediate frame, or the exception
    type for the deepest one under --tb=long.
    """
    frames = [(m.group(1), "") for m in _FRAME_NATIVE.finditer(block)]
    for m in _FRAME_LONG.finditer(block):
        frames.append((m.group("path"), m.group("tail").strip()))
    return frames


def _exception_of(block: str, frames: list) -> str:
    """The exception type this failure ended with, or ""."""
    # Under --tb=long the deepest frame names it directly:
    #     tests/test_api.py:6: AttributeError
    if frames:
        tail = frames[-1][1]
        if tail and not tail.startswith("in "):
            m = _EXC_LINE.match(tail)
            if m:
                return m.group(1)
    for line in reversed(block.strip().splitlines()):
        m = _EXC_LINE.match(line.strip())
        if m:
            return m.group(1)
    return ""


def _test_id_of(block: str) -> str:
    """The `path::test_name` pytest names in the block header, or ""."""
    for line in block.splitlines():
        stripped = line.strip("_ =").strip()
        if "::" in stripped and ".py" in stripped:
            return stripped[:120]
        if stripped.startswith("ERROR at setup of "):
            return stripped[len("ERROR at setup of "):][:120]
    return ""


def classify_pytest_output(output: str, project_root: str = "") -> BlameReport:
    """
    Classify every failure in a pytest run. Never raises.

    `output` is pytest's stdout, produced with a traceback style that prints
    frames: `--tb=long` (what the tester uses), `--tb=auto`, or `--tb=native`.
    `--tb=line` and `--tb=no` carry no frames, so everything comes back
    AMBIGUOUS — the safe direction, not a silent pass.
    """
    report = BlameReport()
    if not output:
        return report

    try:
        for block in _BLOCK.split(output):
            frames = _frames_of(block)
            if not frames:
                continue

            exception = _exception_of(block, frames)
            deepest = frames[-1][0]

            if exception in _ASSERTION_EXCEPTIONS:
                # The test ran, reached its assertion, and disagreed. Which side
                # is wrong is exactly what a traceback cannot say.
                verdict = Blame.AMBIGUOUS
            elif not exception:
                verdict = Blame.AMBIGUOUS
            elif is_test_path(deepest):
                verdict = Blame.TEST_DEFECT
            else:
                verdict = Blame.SOURCE_DEFECT

            report.failures.append(FailureBlame(
                verdict=verdict,
                exception=exception,
                frame=deepest,
                test_id=_test_id_of(block),
            ))
    except Exception:
        # A classifier that raises must not take a build down, and must not be
        # mistaken for one that found nothing wrong. An empty report leaves both
        # flags False, so every caller keeps the behaviour it had.
        return BlameReport()

    return report
