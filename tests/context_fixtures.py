"""Explicit golden context for legacy regression fixtures, never runtime defaults."""
from functools import partial

CONTEXT = {"competition_id": 43, "season_id": 106}
CONTEXT_ARGS = ["--competition-id", "43", "--season-id", "106"]
BRONZE_ARGS = CONTEXT_ARGS + ["--parent-sha256", "a" * 64, "--bronze-max-id", "1000"]


def in_context(function):
    return partial(function, **CONTEXT)
