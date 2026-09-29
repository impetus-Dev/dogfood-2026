"""
URL configuration for the voting app.
"""
from django.urls import path
from voting import views

app_name = "voting"

urlpatterns = [
    path("vote/", views.AuthenticatedVoteView.as_view(), name="authenticated_vote"),
    path("vote/link/<str:token>/", views.LinkVoteView.as_view(), name="link_vote"),
    path("vote/ballot/<int:event_id>/", views.BallotView.as_view(), name="ballot"),
    path("results/<int:event_id>/", views.ResultsView.as_view(), name="results"),
    path("projects/<int:project_id>/comments/", views.ProjectCommentListCreateView.as_view(), name="project_comments"),
]
