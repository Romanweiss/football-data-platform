"""PET-1 discovery/completeness and offline boundaries, no publication required."""
import ast
from datetime import date, datetime
import json
from pathlib import Path
import re
import unittest

from src.providers.identity_registry import IdentityEvidence
from src.providers.models import StageType
from src.providers.openfootball import OpenFootballMapping, RoundBinding, TeamBinding, prepare_openfootball
from src.providers.openfootball_manifest import UCL_2024_25

from ci.check_repository import secret_findings

ROOT = Path(__file__).resolve().parents[2]
FILES = ("src/providers/openfootball.py", "src/providers/openfootball_manifest.py",
         "tests/test_openfootball.py", "tests/ci/test_openfootball.py", "docs/pet1-openfootball-adapter.md",
         "tests/test_openfootball_score_edges.py", "tests/test_openfootball_remediation.py",
         "docs/pet2-openfootball-dataset-validation.md", "docs/pet2r-score-semantics.md")


class OpenFootballContracts(unittest.TestCase):
    def test_complete_source_set_and_no_secret_signatures(self):
        for name in FILES:
            with self.subTest(name=name):
                text = (ROOT / name).read_text(encoding="utf-8")
                self.assertFalse(secret_findings(text))

    def test_no_direct_io_or_network_imports(self):
        allowed = {"dataclasses", "datetime", "hashlib", "json", "re",
            "src.providers.identity_registry", "src.providers.models", "src.providers.observed_versions",
            "src.providers.openfootball_manifest", "src.providers.validation"}
        for name in FILES[:2]:
            tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertTrue({a.name for a in node.names} <= allowed)
                if isinstance(node, ast.ImportFrom):
                    self.assertIn(node.module, allowed)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, {"open", "eval", "exec", "compile", "__import__"})

    def test_existing_ci_discovers_tests_on_both_pinned_pythons(self):
        workflow = (ROOT / ".github/workflows/ci-fast.yml").read_text(encoding="utf-8")
        for required in ("'3.10.12'", "'3.12.14'", "discover -s tests -p 'test_*.py'",
                         "discover -s tests/ci -p 'test_*.py'"):
            self.assertIn(required, workflow)
        dockerfile = (ROOT / "ci/Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY src/ src/", dockerfile)
        self.assertIn("COPY tests/ tests/", dockerfile)

    def test_runbook_preserves_open_questions(self):
        text = (ROOT / "docs/pet1-openfootball-adapter.md").read_text(encoding="utf-8")
        for fact in ("NOT ACQUIRED", "UNKNOWN", "PET-2", "Stage 8C: PARTIAL",
                     "football-data.org", "source_ft", "IDENTITY_REVIEW_REQUIRED"):
            self.assertIn(fact, text)

    def test_remediation_does_not_claim_complete_results_or_standings(self):
        text = (ROOT / "docs/pet2r-score-semantics.md").read_text(encoding="utf-8")
        for fact in ("ACCEPTED_WITH_LIMITATIONS", "394", "INCOMPLETE", "source_et", "source_p",
                     "regulation_score=None", "standings_eligible=False", "NOT_ATOMIC", "Stage 8C: PARTIAL"):
            self.assertIn(fact, text)

    def test_published_reproduction_recipe_is_self_contained_and_typed(self):
        text = (ROOT / "docs/pet2r-score-semantics.md").read_text(encoding="utf-8")
        match = re.search(r'<!-- pet2s-mapping-recipe -->\s*```json\s*(.*?)\s*```', text, re.S)
        self.assertIsNotNone(match)
        recipe = json.loads(match[1])  # Metadata only, never executable code or a raw source payload.
        self.assertEqual(UCL_2024_25.repository, recipe["repository"])
        self.assertEqual(UCL_2024_25.commit, recipe["commit"])
        self.assertEqual(UCL_2024_25.path, recipe["path"])
        self.assertRegex(recipe["content_sha256"], r'^[0-9a-f]{64}$')
        self.assertRegex(recipe["expected_semantic_digest"], r'^[0-9a-f]{64}$')
        self.assertEqual(189, recipe["expected_rows"])
        self.assertEqual(36, recipe["expected_teams"])
        self.assertEqual("name-v1-", recipe["team_key_prefix"])
        self.assertEqual(["source_round", "stage_key", "stage_name", "kind", "round_key", "order"],
                         recipe["round_columns"])
        rounds = tuple(RoundBinding(*row[:3], StageType(row[3]), *row[4:]) for row in recipe["rounds"])
        self.assertEqual(14, len(rounds))
        self.assertEqual(14, len({r.source_round for r in rounds}))
        # Exercise all published round bindings on artificial team data, never acquire/use the real file.
        context = OpenFootballMapping(recipe["source_name"], (
            TeamBinding("Artificial Amber", "synthetic-amber", "Artificial Amber"),
            TeamBinding("Artificial Blue", "synthetic-blue", "Artificial Blue")), rounds,
            date.fromisoformat(recipe["date_start"]), date.fromisoformat(recipe["date_end"]),
            IdentityEvidence(True, recipe["evidence_reference"]), expected_rows=14)
        rows = [{"round": r.source_round, "date": recipe["date_start"],
                 "team1": "Artificial Amber", "team2": "Artificial Blue"} for r in rounds]
        proposal = prepare_openfootball({"name": recipe["source_name"], "matches": rows}, mapping=context,
            observed_at=datetime.fromisoformat(recipe["observed_at"]))
        self.assertEqual(14, len(proposal.fixtures))
        self.assertEqual(14, proposal.dq.counts["RESULT_MISSING"])
        self.assertLessEqual(datetime.fromisoformat(recipe["acquired_at"]), proposal.observed_at)
