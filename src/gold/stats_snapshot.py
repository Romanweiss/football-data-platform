"""Reviewed Stage 4B/4C WC2022 stats snapshot. No latest selection for v2."""
from types import MappingProxyType

PINNED_STATS_INPUTS = MappingProxyType({
    "event_core": "f62c4943ef505dc56ce02b4c1724fedd69cfc773b23a8f3a1b6cf575bf2f526d",
    "match_squads": "e00cc4605530a68a791981771b75c26f283bba55070014c33db27f4bed0443bd",
    "pass_events": "635dc7e21a3e07793c3d7129c2263dccebfa3fea13956225a574b2a94d45553a",
    "shot_events": "a67da8f5404c02ce557f6f2a5c8a95e052ecaeb5e8e8b5ac271c9bb5c4992584",
})


def validate_stats_snapshot(inputs):
    """Check canonical manifest inputs, not CLI-provided table names or latest builds."""
    from src.gold.manifest import GoldIntegrityError
    selected = {item["dataset"]: item["build_id"] for item in inputs}
    if len(inputs) != len(selected) or selected != PINNED_STATS_INPUTS:
        raise GoldIntegrityError("Stats v2 must use the exact reviewed Stage 4B Silver snapshot.")
