"""Ledger errors: each has a stable problem code and an actionable message (doc 09 AC-C1)."""

from fcp.core.errors import ConflictError, PermissionDeniedError, ValidationFailedError


class UnbalancedEntryError(ValidationFailedError):
    code = "ledger.entry.unbalanced"
    title = "Entry does not balance"


class TooFewLinesError(ValidationFailedError):
    code = "ledger.entry.too_few_lines"
    title = "Entry needs at least two lines"


class InvalidLineError(ValidationFailedError):
    code = "ledger.line.invalid"
    title = "Invalid journal line"


class AccountNotPostableError(ValidationFailedError):
    code = "ledger.account.not_postable"
    title = "Account cannot be posted to"


class NoPeriodError(ValidationFailedError):
    code = "ledger.period.not_found"
    title = "No accounting period for this date"


class PeriodLockedError(ConflictError):
    code = "ledger.period.locked"
    title = "Period is locked"


class PeriodSoftClosedError(PermissionDeniedError):
    code = "ledger.period.soft_closed"
    title = "Period is soft-closed"


class InvalidStateError(ConflictError):
    code = "ledger.entry.invalid_state"
    title = "Not possible in the entry's current state"


class SegregationOfDutiesError(PermissionDeniedError):
    code = "ledger.entry.sod_violation"
    title = "Segregation of duties"


class ApprovalStaleError(ConflictError):
    code = "ledger.entry.approval_stale"
    title = "Entry changed after approval"


class ApprovalRequiredError(ConflictError):
    code = "ledger.entry.approval_required"
    title = "Approval required before posting"


class AlreadyReversedError(ConflictError):
    code = "ledger.entry.already_reversed"
    title = "Entry already reversed"


class IdempotencyConflictError(ConflictError):
    code = "ledger.idempotency.conflict"
    title = "Idempotency key reused with a different request"
