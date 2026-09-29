from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_exempt

from events.models import Event, Track
from projects.models import Project


def get_event_or_404(event_id):
    """
    Safely resolves an event by numeric primary key or external_id string.
    Raises Http404 if not found.
    """
    if str(event_id).isdigit():
        try:
            return Event.objects.get(pk=int(event_id))
        except Event.DoesNotExist:
            pass
    try:
        return Event.objects.get(external_id=str(event_id))
    except Event.DoesNotExist:
        raise Http404(f"Event '{event_id}' not found")


@xframe_options_exempt
def embed_gallery_view(request, event_id):
    """
    Public embeddable gallery widget for a hackathon event.
    Renders a lightweight, responsive gallery view designed for iframe embedding.

    PUBLIC-SAFE DATA ONLY:
      - Project: title, summary, track name, team name, repo_url, status.
      - Event: id, name, external_id.
    STRICTLY EXCLUDES:
      - Judge scores, judge assignments, rubric criteria.
      - Team invite codes, secret tokens, private team notes.
      - Voting tokens, vote tallies (before close), session cookies.
      - Ed25519 signing keys, credentials, user emails.

    Framing is explicitly relaxed via @xframe_options_exempt and frame-ancestors *
    for this route ONLY, preserving clickjacking defense on all other endpoints.
    """
    event = get_event_or_404(event_id)

    track_param = request.GET.get("track", "").strip()
    q = request.GET.get("q", "").strip()

    projects_qs = (
        Project.objects.filter(Q(track__event=event) | Q(team__event=event))
        .select_related("track", "team")
        .order_by("title")
    )

    if q:
        projects_qs = projects_qs.filter(
            Q(title__icontains=q) | Q(summary__icontains=q)
        )

    selected_track_id = None
    if track_param:
        try:
            selected_track_id = int(track_param)
            projects_qs = projects_qs.filter(track_id=selected_track_id)
        except (ValueError, TypeError):
            selected_track_id = None

    # Construct strictly sanitized public data dictionary list
    # Guaranteed to NEVER expose scores, invite_code, tokens, or credentials
    safe_projects = []
    for p in projects_qs:
        safe_projects.append({
            "id": p.id,
            "title": p.title,
            "summary": p.summary,
            "track_name": p.track.name if p.track else "",
            "team_name": p.team.name if p.team else "",
            "repo_url": p.repo_url or "",
            "status": p.status,
            "is_submitted": p.status == "submitted",
        })

    tracks = Track.objects.filter(event=event).order_by("name")

    response = render(
        request,
        "t4/embed_gallery.html",
        {
            "event": {
                "id": event.id,
                "name": event.name,
                "external_id": event.external_id,
            },
            "projects": safe_projects,
            "tracks": tracks,
            "q": q,
            "selected_track_id": selected_track_id,
            "total_count": len(safe_projects),
        },
    )
    # Explicitly relax framing for this embed view only
    response.xframe_options_exempt = True
    response.headers["Content-Security-Policy"] = "frame-ancestors *"
    return response


@xframe_options_exempt
def embed_script_view(request):
    """
    Lightweight JavaScript helper for embedding the gallery widget.
    Clients can include:
      <script src="/embed/gallery.js" data-event="1" data-height="600"></script>
    which automatically generates and inserts the responsive iframe.
    """
    js_content = """(function() {
    function initWidgets() {
        var scripts = document.querySelectorAll('script[data-event]');
        scripts.forEach(function(script) {
            if (script.getAttribute('data-widget-loaded')) return;
            script.setAttribute('data-widget-loaded', 'true');
            var eventId = script.getAttribute('data-event');
            var height = script.getAttribute('data-height') || '600';
            var width = script.getAttribute('data-width') || '100%';
            var host = script.src.split('/embed/')[0];
            var iframe = document.createElement('iframe');
            iframe.src = host + '/embed/gallery/' + encodeURIComponent(eventId) + '/';
            iframe.style.width = width;
            iframe.style.height = height + (height.indexOf('px') > -1 || height.indexOf('%') > -1 ? '' : 'px');
            iframe.style.border = '1px solid #e2e8f0';
            iframe.style.borderRadius = '8px';
            iframe.style.boxShadow = '0 2px 8px rgba(0,0,0,0.08)';
            iframe.setAttribute('title', 'Hackathon Project Gallery');
            iframe.setAttribute('loading', 'lazy');
            iframe.setAttribute('allowfullscreen', 'true');
            script.parentNode.insertBefore(iframe, script.nextSibling);
        });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initWidgets);
    } else {
        initWidgets();
    }
})();"""
    response = HttpResponse(js_content, content_type="application/javascript")
    response.xframe_options_exempt = True
    response.headers["Content-Security-Policy"] = "frame-ancestors *"
    return response
