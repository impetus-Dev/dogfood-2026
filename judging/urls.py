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
    path("api/export.csv", ExportCSVView.as_view(), name="csv_export"),
    # Additional paths for compatibility when included under an 'api/' prefix
    path("judge/scores/", JudgeScoresView.as_view(), name="judge_scores_alt"),
    path("export.csv", ExportCSVView.as_view(), name="csv_export_alt"),
]
