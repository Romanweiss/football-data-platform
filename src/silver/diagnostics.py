"""Publication context with allowlisted quality details; no raw service errors."""

import json
import re
from dataclasses import dataclass


def _safe_quality_detail(error: Exception) -> str | None:
    # Avoid importing PySpark into the offline CLI. Only this project's exact
    # quality class and fixed messages (field names/counts, never input data) qualify.
    kind = type(error)
    if (kind.__module__, kind.__name__) != ("src.silver.statsbomb.lineups", "LineupQualityError"):
        return None
    message = str(error)
    if message in (
        "DQ requires distinct positive selected match ids.",
        "match_squads DQ failed; see aggregate diagnostics.",
        "Lineup referential DQ failed; see aggregate diagnostics.",
        "team_id dimension DQ failed; see aggregate diagnostics.",
        "player_id dimension DQ failed; see aggregate diagnostics.",
    ) or re.fullmatch(r"Conflicting (?:player_id|team_id) identity attributes: [0-9]+\.", message):
        return message
    return None


@dataclass
class PublishDiagnostics:
    stage: str = "parent catalog"
    operation: str = "initialize"
    match_id: int | None = None
    key: str | None = None

    def set(self, stage: str, operation: str, *, match_id: int | None = None, key: str | None = None) -> None:
        # Reset object context on every operation; never attribute a batch failure to the last child.
        self.stage, self.operation, self.match_id, self.key = stage, operation, match_id, key

    def failure(self, error: Exception, *, integrity: bool = False) -> str:
        """Never expose arbitrary exception text, even from integrity exceptions."""
        detail = _safe_quality_detail(error)
        integrity = integrity or detail is not None
        detail_text = f"detail={json.dumps(detail)} " if detail is not None else ""
        return (
            f"Silver publish failed: stage={json.dumps(self.stage)} "
            f"operation={json.dumps(self.operation)} "
            f"match_id={self.match_id if self.match_id is not None else 'n/a'} "
            f"key={json.dumps(self.key) if self.key is not None else 'n/a'} "
            f"exception={type(error).__name__} category={'integrity' if integrity else 'runtime'}. "
            f"{detail_text}"
            "No application S3 cleanup was attempted."
        )
