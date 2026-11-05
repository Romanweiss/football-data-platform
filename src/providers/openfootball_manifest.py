"""Declarative PET-1 source candidate. No acquisition, file access or transport."""
from dataclasses import dataclass
from datetime import datetime
import re

from src.providers.identity_registry import checked_id, guard
from src.providers.models import Availability, Capability, SourceCapability
from src.providers.observed_versions import checked_digest, utc_observation


@dataclass(frozen=True)
class OpenFootballManifest:
    dataset_id: str
    repository: str
    commit: str
    path: str
    license_id: str
    license_reference: str
    attribution: str
    source_format: str
    schema_version: int
    competition_key: str
    competition_name: str
    season_key: str
    season_label: str
    content_sha256: str | None = None
    acquired_at: datetime | None = None
    coverage: str = "UNKNOWN"
    capabilities: tuple[SourceCapability, ...] = ()

    def validate(self):
        for value in (self.dataset_id, self.competition_key, self.season_key):
            checked_id(value)
        guard(self.repository == "https://github.com/openfootball/football.json", "SCOPE")
        guard(type(self.commit) is str and re.fullmatch(r"[0-9a-f]{40}", self.commit), "IDENTITY")
        # This adapter deliberately accepts only this reviewed candidate, not arbitrary paths.
        guard(self.path == "2024-25/uefa.cl.json" and
              self.competition_key == "uefa-champions-league" and self.season_key == "2024-25", "SCOPE")
        guard(self.season_label == "2024/25" and self.competition_name == "UEFA Champions League", "SCOPE")
        guard(self.license_id == "CC0-1.0" and self.license_reference ==
              self.repository + "/blob/" + self.commit + "/LICENSE.md", "UNCONFIRMED")
        guard(self.attribution == "openfootball contributors; credit is project provenance policy, not a CC0 condition")
        guard(self.source_format == "openfootball-json-matches" and
              type(self.schema_version) is int and self.schema_version == 1, "UNSUPPORTED")
        guard(self.coverage == "UNKNOWN", "SCOPE")  # PET-1 cannot certify whole-file coverage.
        guard((self.content_sha256 is None) == (self.acquired_at is None), "UNCONFIRMED")
        if self.content_sha256 is not None:
            checked_digest(self.content_sha256)
            utc_observation(self.acquired_at)
        guard(type(self.capabilities) is tuple and
              all(type(c) is SourceCapability for c in self.capabilities), "MALFORMED")
        expected = tuple(SourceCapability(c, Availability.DECLARED if c in
            (Capability.FIXTURES, Capability.RESULTS) else Availability.UNAVAILABLE) for c in Capability)
        guard(self.capabilities == expected, "UNSUPPORTED")


UCL_2024_25 = OpenFootballManifest(
    dataset_id="openfootball-ucl-2024-25-json-v1",
    repository="https://github.com/openfootball/football.json",
    commit="e6744429ee395bc86f247348c6184bb08d4eb361",
    path="2024-25/uefa.cl.json",
    license_id="CC0-1.0",
    license_reference="https://github.com/openfootball/football.json/blob/"
                      "e6744429ee395bc86f247348c6184bb08d4eb361/LICENSE.md",
    attribution="openfootball contributors; credit is project provenance policy, not a CC0 condition",
    source_format="openfootball-json-matches",
    schema_version=1,
    competition_key="uefa-champions-league",
    competition_name="UEFA Champions League",
    season_key="2024-25",
    season_label="2024/25",
    capabilities=tuple(SourceCapability(c, Availability.DECLARED if c in
        (Capability.FIXTURES, Capability.RESULTS) else Availability.UNAVAILABLE) for c in Capability),
)
