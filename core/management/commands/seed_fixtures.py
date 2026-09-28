import json
import os
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connection, transaction
from django.utils.dateparse import parse_datetime

from events.models import Event, Track
from projects.models import Project
from teams.models import Team, TeamMembership


class Command(BaseCommand):
    help = "Seed initial fixtures for the DOGFOOD 2026 hackathon platform."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fixtures",
            "--file",
            dest="fixture_file",
            default=None,
            help="Path to fixtures.json (default: searches BASE_DIR / fixtures.json)",
        )

    def find_fixtures_file(self, explicit_path=None):
        if explicit_path and os.path.exists(explicit_path):
            return explicit_path

        candidates = [
            settings.BASE_DIR / "fixtures.json",
            Path(settings.BASE_DIR).parent / "fixtures.json",
            Path("fixtures.json"),
            Path("/app/fixtures.json"),
        ]
        for c in candidates:
            if os.path.exists(c):
                return str(c)
        return None

    def handle(self, *args, **options):
        fixture_path = self.find_fixtures_file(options.get("fixture_file"))
        if not fixture_path:
            raise CommandError("fixtures.json not found.")

        self.stdout.write(f"Loading fixtures from {fixture_path}...")
        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        event_data = data.get("event")
        tracks_data = data.get("tracks", [])
        teams_data = data.get("teams", [])
        projects_data = data.get("projects", [])
        judges_data = data.get("judges", [])
        scores_data = data.get("scores", [])

        if not event_data:
            raise CommandError("No event found in fixture data.")

        # Requirement 6: Explicitly and gracefully skip judges and scores sections
        if judges_data or scores_data:
            self.stdout.write(
                self.style.NOTICE(
                    f"Notice: Found {len(judges_data)} judges and {len(scores_data)} scores in fixture. "
                    "Skipping judges and scores sections gracefully (judging/scoring models belong to later phases)."
                )
            )

        with transaction.atomic():
            # 1. Event
            close_dt = parse_datetime(event_data["submissions_close"])
            event, event_created = Event.objects.get_or_create(
                external_id=event_data["id"],
                defaults={
                    "name": event_data["name"],
                    "submissions_close": close_dt,
                    "voting_mode": "authenticated",
                },
            )
            if not event_created:
                event.name = event_data["name"]
                event.submissions_close = close_dt
                event.save()

            # 2. Tracks
            track_map = {}
            tracks_created_count = 0
            for trk in tracks_data:
                track, trk_created = Track.objects.get_or_create(
                    external_id=trk["id"],
                    defaults={
                        "event": event,
                        "name": trk["name"],
                    },
                )
                if not trk_created:
                    track.name = trk["name"]
                    track.event = event
                    track.save()
                else:
                    tracks_created_count += 1
                track_map[trk["id"]] = track

            # 3. Teams
            team_map = {}
            teams_created_count = 0
            for tm in teams_data:
                team, tm_created = Team.objects.get_or_create(
                    external_id=tm["id"],
                    defaults={
                        "event": event,
                        "name": tm["name"],
                        "invite_code": tm["id"],
                    },
                )
                if not tm_created:
                    team.name = tm["name"]
                    team.event = event
                    team.invite_code = tm["id"]
                    team.save()
                else:
                    teams_created_count += 1
                team_map[tm["id"]] = team

                # Create user accounts and team memberships for team members
                for member_email in tm.get("members", []):
                    member_user, _ = User.objects.get_or_create(
                        username=member_email,
                        defaults={"email": member_email},
                    )
                    TeamMembership.objects.get_or_create(
                        team=team,
                        user=member_user,
                    )

            # 4. Projects
            projects_created_count = 0
            for prj in projects_data:
                team = team_map.get(prj["team"])
                track = track_map.get(prj["track"])
                if not team:
                    raise CommandError(f"Team {prj['team']} not found for project {prj['id']}")
                if not track:
                    raise CommandError(f"Track {prj['track']} not found for project {prj['id']}")

                # Requirement 5/7: Explicitly confirm same-event consistency
                if team.event_id != track.event_id:
                    raise CommandError(
                        f"Fixture inconsistency: Project {prj['id']} team event ({team.event_id}) "
                        f"!= track event ({track.event_id})"
                    )

                # Requirement 3: Use explicit project status if present, otherwise infer from submitted_at
                status = prj.get("status")
                if not status:
                    status = "submitted" if prj.get("submitted_at") else "draft"

                sub_dt = parse_datetime(prj["submitted_at"]) if prj.get("submitted_at") else None

                project, prj_created = Project.objects.get_or_create(
                    external_id=prj["id"],
                    defaults={
                        "team": team,
                        "track": track,
                        "title": prj["title"],
                        "summary": prj.get("summary", ""),
                        "repo_url": prj.get("repo_url", ""),
                        "status": status,
                        "submitted_at": sub_dt,
                    },
                )
                if not prj_created:
                    project.team = team
                    project.track = track
                    project.title = prj["title"]
                    project.summary = prj.get("summary", "")
                    project.repo_url = prj.get("repo_url", "")
                    project.status = status
                    project.submitted_at = sub_dt
                    project.save()
                else:
                    projects_created_count += 1

            # Reset database sequences so future inserts don't collide
            try:
                sequence_sql = connection.ops.sequence_reset_sql(
                    no_style(), [Event, Track, Team, Project]
                )
                with connection.cursor() as cursor:
                    for sql in sequence_sql:
                        cursor.execute(sql)
            except Exception:
                pass

        self.stdout.write(
            self.style.SUCCESS(
                f"seed_fixtures: Successfully seeded fixtures:\n"
                f"  - Event: {event.name} (id={event.id}, close={event.submissions_close})\n"
                f"  - Tracks: {len(tracks_data)} loaded\n"
                f"  - Teams: {len(teams_data)} loaded\n"
                f"  - Projects: {len(projects_data)} loaded\n"
                f"  - Judges skipped: {len(judges_data)}\n"
                f"  - Scores skipped: {len(scores_data)}"
            )
        )
