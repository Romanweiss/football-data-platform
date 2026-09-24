"""Tiny Silver-shaped fixtures: two matches, two teams, unused squad players."""

from pyspark.sql import functions as F


def silver_frames(spark):
    squads = [(match, team, "Red" if team == 10 else "Blue", player,
               ("Phil Foden" if match == 7 else "Philip Foden") if player == 100 else f"Player {player}")
              for match in (7, 8) for team in (10, 20) for player in ((100, 101) if team == 10 else (200, 201))]
    events = [
        (7, 10, 100, "1", True, None), (7, 10, 100, "2", None, True),
        (7, 10, 100, "3", True, False), (7, 10, 100, "4", None, None),
        (7, 20, 200, "5", None, None), (7, 20, 200, "6", None, True),
        (7, 10, None, "7", True, None), (8, 10, 100, "8", None, None),
    ]
    # Event 8 represents an own-goal event, deliberately NOT a shot row.
    passes = [(7, 10, 100, "1"), (7, 10, 100, "2"), (7, 20, 200, "5")]
    shots = [(7, 10, 100, "3", 0.1, 97), (7, 10, 100, "4", 0.2, 100)]
    frames = {
        "match_squads": spark.createDataFrame(squads, "match_id long, team_id long, team_name string, player_id long, player_name string"),
        "event_core": spark.createDataFrame(events, "match_id long, team_id long, player_id long, event_id string, under_pressure boolean, counterpress boolean"),
        "pass_events": spark.createDataFrame(passes, "match_id long, team_id long, player_id long, event_id string"),
        "shot_events": spark.createDataFrame(shots, "match_id long, team_id long, player_id long, event_id string, statsbomb_xg double, outcome_id long"),
    }
    return {name: frame.withColumn("competition_id", F.lit(43).cast("long"))
            .withColumn("season_id", F.lit(106).cast("long")) for name, frame in frames.items()}
