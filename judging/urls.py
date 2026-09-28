"""
URL configuration for judging app.

Routes matching .dogfood.toml:
  - path("api/judge/scores/", JudgeScoresView.as_view(), name="judge_scores")
  - path("api/export.csv", ExportCSVView.as_view(), name="csv_export")
"""

from django.urls import path
from judging.views import ExportCSVView, JudgeScoresView

urlpatterns = [
    # Primary routes matching .dogfood.toml specification
    path("api/judge/scores/", JudgeScoresView.as_view(), name="judge_scores"),
    path("api/judge/scores", JudgeScoresView.as_view(), name="judge_scores_noslash"),
    path("api/export.csv", ExportCSVView.as_view(), name="csv_export"),
    path("api/export", ExportCSVView.as_view(), name="api_export_noslash"),
    # Routes matching legacy or alternative .dogfood.toml routes
    path("judging/scores/", JudgeScoresView.as_view(), name="judging_scores"),
    path("judging/scores", JudgeScoresView.as_view(), name="judging_scores_noslash"),
    path("judging/export/", ExportCSVView.as_view(), name="judging_export"),
    path("judging/export", ExportCSVView.as_view(), name="judging_export_noslash"),
    path("judging/export.csv", ExportCSVView.as_view(), name="judging_export_csv"),
    # Additional paths for compatibility
    path("judge/scores/", JudgeScoresView.as_view(), name="judge_scores_alt"),
    path("judge/scores", JudgeScoresView.as_view(), name="judge_scores_alt_noslash"),
    path("export.csv", ExportCSVView.as_view(), name="csv_export_alt"),
]
