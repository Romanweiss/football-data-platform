"""Validated event-domain membership, using event_core as the period authority."""

from functools import reduce
from pyspark.sql import functions as F
from src.gold.manifest import GoldIntegrityError

MATCH_KEY = ["competition_id", "season_id", "match_id"]
EVENT_KEY = [*MATCH_KEY, "event_id"]


def validate_events(events):
    bad = [F.col(name).isNull() for name in (*EVENT_KEY, "team_id", "period", "type_id")]
    bad.append(~F.col("period").between(1, 5))
    if (events.filter(reduce(lambda a, b: a | b, bad)).limit(1).count()
            or events.groupBy(*EVENT_KEY).count().filter("count > 1").limit(1).count()):
        raise GoldIntegrityError("Invalid/duplicate event_core identity or period.")


def join_domain(events, domain, *, type_id):
    if (domain.filter(reduce(lambda a, b: a | b, [F.col(name).isNull() for name in EVENT_KEY])).limit(1).count()
            or domain.groupBy(*EVENT_KEY).count().filter("count > 1").limit(1).count()):
        raise GoldIntegrityError("Invalid/duplicate event domain identity.")
    expected = events.filter(F.col("type_id") == type_id)
    if (domain.join(expected.select(*EVENT_KEY), EVENT_KEY, "left_anti").limit(1).count()
            or expected.join(domain.select(*EVENT_KEY), EVENT_KEY, "left_anti").limit(1).count()):
        raise GoldIntegrityError("Event domain differs from exact typed event_core membership.")
    joined = domain.alias("d").join(expected.alias("e"), EVENT_KEY, "inner")
    if joined.filter(~F.col("d.team_id").eqNullSafe(F.col("e.team_id"))
            | ~F.col("d.player_id").eqNullSafe(F.col("e.player_id"))
            | ~F.col("d.period").eqNullSafe(F.col("e.period"))).limit(1).count():
        raise GoldIntegrityError("Event domain/core team, player or period mismatch.")
    return joined.select("d.*", F.col("e.period").alias("core_period"))


def performance_frames(frames):
    events = frames["event_core"]
    validate_events(events)
    result = dict(frames)
    result["event_core"] = events.filter(F.col("period") != 5)
    for name, type_id in (("shot_events", 16), ("pass_events", 30)):
        result[name] = join_domain(events, frames[name], type_id=type_id).filter("core_period != 5").drop("core_period")
    return result
