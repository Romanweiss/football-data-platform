"""Small publication context: never format exception messages or request details."""

import json
from dataclasses import dataclass


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
        """Only explicit context and the exception class enter application diagnostics."""
        return (
            f"Silver publish failed: stage={json.dumps(self.stage)} "
            f"operation={json.dumps(self.operation)} "
            f"match_id={self.match_id if self.match_id is not None else 'n/a'} "
            f"key={json.dumps(self.key) if self.key is not None else 'n/a'} "
            f"exception={type(error).__name__} category={'integrity' if integrity else 'runtime'}. "
            "No application S3 cleanup was attempted."
        )
