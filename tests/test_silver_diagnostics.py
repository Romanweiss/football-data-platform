"""Safe quality error formatting without importing Spark or reading environment."""

import unittest

from src.silver.diagnostics import PublishDiagnostics
from src.silver.manifest import SilverIntegrityError


# Match the class metadata without requiring PySpark in the Python tools image.
LineupQualityError = type("LineupQualityError", (ValueError,), {
    "__module__": "src.silver.statsbomb.lineups",
})


class QualityDiagnosticsTests(unittest.TestCase):
    def test_known_quality_messages_are_included(self):
        messages = (
            "Conflicting player_id identity attributes: 12.",
            "Conflicting team_id identity attributes: 1.",
            "DQ requires distinct positive selected match ids.",
            "match_squads DQ failed; see aggregate diagnostics.",
            "Lineup referential DQ failed; see aggregate diagnostics.",
            "team_id dimension DQ failed; see aggregate diagnostics.",
            "player_id dimension DQ failed; see aggregate diagnostics.",
        )
        for message in messages:
            with self.subTest(message=message):
                result = PublishDiagnostics().failure(LineupQualityError(message))
                self.assertIn(f'detail="{message}"', result)
                self.assertIn("exception=LineupQualityError category=integrity", result)

    def test_arbitrary_error_text_is_hidden_even_for_project_errors(self):
        secret = "synthetic-access-secret synthetic-s3-secret"
        for kind in (RuntimeError, SilverIntegrityError, LineupQualityError):
            for message in (secret, "Conflicting player_id identity attributes: 1.\n" + secret):
                with self.subTest(kind=kind, message=message):
                    result = PublishDiagnostics().failure(kind(message), integrity=True)
                    self.assertNotIn(secret, result)
                    self.assertNotIn("detail=", result)

    def test_same_message_from_untrusted_class_stays_hidden(self):
        error = RuntimeError("Conflicting player_id identity attributes: 1.")
        result = PublishDiagnostics().failure(error)
        self.assertNotIn("detail=", result)
        self.assertIn("category=runtime", result)


if __name__ == "__main__":
    unittest.main()
