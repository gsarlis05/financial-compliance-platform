"""The ``cashflow`` module: the 13-week cash forecast (M3-7, doc 10 §3).

A planning module: it never imports the ledger and reads actuals through ``reporting`` only
(ADR-0007). Internal package. Other modules must use ``fcp.modules.cashflow.api``.
"""
