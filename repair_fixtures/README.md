# repair_fixtures — known-good projects for `tools/verify_repairs.py`

Every project in `generated_projects/` is single-router (`from routes import
router`). That is *why* the router defect of 2026-09-01 was invisible: the
corpus contains no example of the shape the rule mishandled, so replaying the
repairs over the corpus could not have caught it either.

These are the shapes the corpus does not have, hand-written to be **correct and
importable as they stand**. A repair pass that changes one of them at all is
suspicious; one that stops it importing is a defect.

Rules:

- **Every fixture must import cleanly before any repair touches it.** That is
  what makes it usable evidence — `verify_repairs.py` can only assert "do no
  harm" on files that were unharmed to begin with.
- Keep them minimal and dependency-light. They exist to exercise a repair rule,
  not to be applications.
- When a repair rule is fixed, add the shape that broke it here, so the next
  change to that rule has to survive it.
