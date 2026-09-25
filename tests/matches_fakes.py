"""Synthetic matches parent with the public StatsBomb nested-field contract."""

from pathlib import Path
from src.common.checksum import sha256_bytes

RAW = (Path(__file__).parent / "fixtures/statsbomb_matches.json").read_bytes()


def parent(raw=RAW):
    checksum = sha256_bytes(raw)
    return {"source": "statsbomb", "dataset": "world_cup_2022_matches",
            "source_url": "https://raw.githubusercontent.com/hudl/open-data/master/data/matches/43/106.json",
            "s3_bucket": "test-bucket", "object_key": f"football/bronze/statsbomb/matches/sha256={checksum}/matches.json",
            "sha256": checksum, "size_bytes": len(raw)}
