from django.urls import path
from application import views

urlpatterns = [
    path("api/v1/health", views.health),
    path("api/v1/health/clickhouse", views.clickhouse_health),
    path("api/v1/competitions", views.competitions),
    path("api/v1/competitions/<str:competition_id>/seasons", views.seasons),
    path("api/v1/competitions/<str:competition_id>/seasons/<str:season_id>/matches", views.matches),
    path("api/v1/competitions/<str:competition_id>/seasons/<str:season_id>/matches/<str:match_id>/passes", views.passes),
    *[path(prefix, views.match) for prefix in (
        "api/v1/matches/<str:match_id>",
        "api/v1/competitions/<str:competition_id>/seasons/<str:season_id>/matches/<str:match_id>")],
    *[path(f"{prefix}/{url}", views.match, {"section": section})
      for prefix in ("api/v1/matches/<str:match_id>",
                     "api/v1/competitions/<str:competition_id>/seasons/<str:season_id>/matches/<str:match_id>")
      for url, section in (("teams", "teams"), ("players", "players"), ("shots", "shots"),
                           ("xg-race", "xg_race"), ("shootout", "shootout"), ("analysis", "analysis"))],
]
handler400 = "application.transport.bad_request"
handler404 = "application.transport.not_found"
handler500 = "application.transport.server_error"
