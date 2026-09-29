from events.models import Event


def dogfood_context(request):
    """Provide real active event context to the DOGFOOD application shell."""
    active_event = Event.objects.first()
    return {
        "active_event": active_event,
        "active_event_id": active_event.id if active_event else 1,
    }
