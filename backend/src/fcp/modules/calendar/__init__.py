"""The ``calendar`` module.

One calendar for every planning module (doc 10 P8): fiscal periods, ISO weeks, business days and
bucketing. Pure date logic (no clock, no floats); fiscal years come from the ledger.

Internal package. Other modules must use ``fcp.modules.calendar.api``.
"""
