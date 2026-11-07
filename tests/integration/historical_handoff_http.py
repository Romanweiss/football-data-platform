"""Real Django + ClickHouse checks, only inside the labelled ephemeral rehearsal."""
import json
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "application.settings")
import django
django.setup()
from django.test import Client
from django.urls import resolve
from application.historical_repository import open_historical_repository
from src.openfootball_etl.serving_contract import PINNED


def main():
    assert os.environ.get("PET3D_ISOLATED_HTTP") == "true"
    base = "/api/v1/competitions/historical/uefa-champions-league/2024"
    http = Client(HTTP_HOST="localhost", raise_request_exception=False)
    assert resolve(base).func.__name__ == "historical"
    if sys.argv[1] == "missing":
        response = http.get(base)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "historical_not_ready"
        print(json.dumps({"missing_serving_http": 503}))
        return
    response = http.get(base)
    assert response.status_code == 200, response.status_code
    summary = response.json()["summary"]
    assert summary == {"fixture_records": 189, "participant_records": 36, "source_stages": 3,
                       "coverage_records": 14, "non_fatal_limitations": 394, "source_reported_ft": 188,
                       "unknown_results": 1, "ambiguous_components": 2}
    fixtures = []
    for offset in (0, 50, 100, 150):
        page = http.get(base + f"/fixtures?limit=50&offset={offset}")
        assert page.status_code == 200
        fixtures += page.json()["fixtures"]
    assert len(fixtures) == len({row["id"] for row in fixtures}) == 189
    assert all(row["canonical_regulation_score"]["value"] is None for row in fixtures)
    for section in ("participants", "coverage", "quality"):
        assert http.get(base + "/" + section).status_code == 200
    with open_historical_repository() as repository:
        assert repository.contract == PINNED
        assert sum(map(len, repository.load().values())) == 633
    # The factory remains fail-closed even in the rebuilt image.
    for variable, bad in (("HISTORICAL_EXPECTED_SERVER_UUID", "12345678-abcd-abcd-abcd-123456789abc"),
                          ("HISTORICAL_PRODUCTION_AUTHORIZATION", ""), ("HISTORICAL_PINNED_BATCH", "bad")):
        original = os.environ[variable]
        try:
            os.environ[variable] = bad
            assert http.get(base).status_code == 503
        finally:
            os.environ[variable] = original
    assert http.get(base).status_code == 200
    print(json.dumps({"http": "PASS", "summary": summary, "unique_fixture_ids": len(fixtures),
                      "rows": 633, "authorization_target_batch_negative_tests": "PASS"}))


if __name__ == "__main__":
    main()
