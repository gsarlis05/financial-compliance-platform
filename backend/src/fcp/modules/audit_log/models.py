"""Append-only, per-tenant hash-chained audit events (doc 03 §4, doc 05 §1, threat T5/T6).

- ``seq`` is gapless per tenant; ``hash = sha256(prev_hash || canonical_json(event))``.
- The runtime role has no UPDATE/DELETE privilege, and a trigger rejects UPDATE, DELETE and
  TRUNCATE for every role (migration 0002). Tampering by someone who bypasses both is still
  detected by chain verification.
"""

from django.db import models

from fcp.core.ids import uuid7


class AuditEvent(models.Model):
    class ActorType(models.TextChoices):
        USER = "USER"
        SYSTEM = "SYSTEM"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    tenant_id = models.UUIDField()
    seq = models.BigIntegerField()
    occurred_at = models.DateTimeField()
    actor_user_id = models.UUIDField(null=True)
    actor_type = models.CharField(max_length=16, choices=ActorType.choices)
    action = models.CharField(max_length=100)
    subject_type = models.CharField(max_length=100)
    subject_id = models.CharField(max_length=100)
    entity_id = models.UUIDField(null=True)
    changes = models.JSONField(default=dict)
    correlation_id = models.CharField(max_length=64, blank=True)
    prev_hash = models.BinaryField(max_length=32)
    hash = models.BinaryField(max_length=32)

    class Meta:
        db_table = "audit_log_event"
        constraints = [
            models.UniqueConstraint(fields=["tenant_id", "seq"], name="audit_log_event_seq_unique")
        ]
        indexes = [models.Index(fields=["tenant_id", "subject_type", "subject_id"])]


class AuditChainHead(models.Model):
    """One row per tenant; locked FOR UPDATE on every append to serialise the chain."""

    tenant_id = models.UUIDField(primary_key=True)
    last_seq = models.BigIntegerField(default=0)
    last_hash = models.BinaryField(max_length=32)

    class Meta:
        db_table = "audit_log_chain_head"
