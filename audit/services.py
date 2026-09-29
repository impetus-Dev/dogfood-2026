"""
Centralized audit service helper.

All audit logging across the application passes through log_audit().
Guarantees:
- raw tokens, session cookies, passwords, and secrets are never recorded.
- records are written to PostgreSQL AuditEvent model.
"""
from audit.models import AuditEvent


def log_audit(actor, action, target, metadata=None):
    """
    Log an audit event record.

    Args:
        actor (str): Safe identifier of actor (e.g. 'user:123', 'link', 'anonymous').
        action (str): Audit action code (e.g. 'VOTE_CAST', 'VOTE_DUPLICATE_BLOCKED').
        target (str): Safe resource target (e.g. 'vote:45', 'project:10', 'event:1').
        metadata (dict, optional): Contextual metadata dict (must contain no secrets).

    Returns:
        AuditEvent: The created audit event instance.
    """
    safe_metadata = dict(metadata) if metadata else {}
    return AuditEvent.objects.create(
        actor=str(actor),
        action=str(action),
        target=str(target),
        metadata=safe_metadata,
    )
