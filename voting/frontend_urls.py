"""
Frontend URL configuration for voting and results pages.
"""
from django.urls import path
from voting import frontend_views

urlpatterns = [
    path("vote/<int:event_id>/", frontend_views.ballot_view, name="ballot_page"),
    path("vote/link/<str:token>/", frontend_views.link_ballot_view, name="link_ballot_page"),
    path("results/<int:event_id>/", frontend_views.results_view, name="results_page"),
    path("events/<int:event_id>/vote/", frontend_views.ballot_view, name="event_ballot_page"),
    path("events/<int:event_id>/results/", frontend_views.results_view, name="event_results_page"),
]
