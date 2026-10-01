"""Read-only result serving validation, including catalog lineage; no S3 calls."""
import argparse
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.analytics.gold_model import current_gold_builds
from src.analytics.gold_specs import RESULTS
from src.analytics.model import current_builds
from src.analytics.specs import SPECS
from src.analytics.validation import ClickHouseIntegrityError
from src.common.clickhouse import create_clickhouse_client
from src.common.postgres import create_postgres_connection, find_silver_build
from src.gold.build_identity import RESULT_INPUTS, input_fingerprint


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bi', action='store_true', help='Also validate views after migration 008')
    args = parser.parse_args(argv)
    try:
        with closing(create_clickhouse_client()) as client, closing(create_postgres_connection()) as connection:
            specs = {name:SPECS[name] for name in RESULT_INPUTS}
            gold = current_gold_builds(client,connection,specs={'match_results':RESULTS})
            silver = current_builds(client,connection,specs=specs)
            upstream = [find_silver_build(connection,dataset=name,competition_id=43,season_id=106,build_id=build_id)
                        for name,build_id in silver.items()]
            if any(row is None for row in upstream) or input_fingerprint(upstream)!=gold['match_results']['input_fingerprint']:
                raise ClickHouseIntegrityError('Result lineage differs from currently served Silver builds')
            for sql in (ROOT/'scripts/check_clickhouse_match_results.sql').read_text().split(';'):
                if sql.strip():
                    print(client.query(sql,settings={'readonly':1}).result_rows)
            if args.bi:
                for dataset,keys in (('team_match_stats','match_id,team_id'),('player_match_stats','match_id,team_id,player_id')):
                    row = client.query(f"SELECT count(),uniqExact(tuple({keys})) FROM football.bi_{dataset} WHERE competition_id=43 AND season_id=106",
                                       settings={'readonly':1}).result_rows[0]
                    expected = client.query(f"SELECT count() FROM football.{dataset} WHERE competition_id=43 AND season_id=106",settings={'readonly':1}).result_rows[0][0]
                    if row!=(expected,expected) or not expected:
                        raise ClickHouseIntegrityError('Enriched BI view changed its grain/coverage')
                    fields=('went_to_extra_time','went_to_penalties','home_shootout_goals','away_shootout_goals','winner_team_id','winner_team_name','result_method','display_score')
                    predicates=' OR '.join(f"isNull(v.{f})!=isNull(r.{f}) OR ifNull(toString(v.{f}),'')!=ifNull(toString(r.{f}),'')" for f in fields)
                    if dataset=='team_match_stats':
                        predicates+=" OR v.match_result!=multiIf(isNull(r.winner_team_id),'D',v.team_id=r.winner_team_id,'W','L')"
                    invalid=client.query(f"SELECT countIf({predicates}) FROM football.bi_{dataset} v INNER JOIN football.match_results r USING (competition_id,season_id,match_id) WHERE v.competition_id=43 AND v.season_id=106",settings={'readonly':1}).result_rows[0][0]
                    if invalid:
                        raise ClickHouseIntegrityError('BI view differs from authoritative match_results')
            if gold!=current_gold_builds(client,connection,specs={'match_results':RESULTS}) or silver!=current_builds(client,connection,specs=specs):
                raise ClickHouseIntegrityError('Serving builds changed during validation')
        print('MATCH RESULTS CHECK PASSED')
        return 0
    except Exception as error:
        print(f'Match results check failed: exception={type(error).__name__}',file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
