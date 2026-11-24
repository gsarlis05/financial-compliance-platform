"""Settings for version 1 on the owner's own computer (V1-3, ADR-0057).

Production-like: debug off, gunicorn, migrations by the schema-owner role only, scheduled jobs, the
documents in the local S3-compatible store and scanned by ClamAV. Served through the web container
at http://localhost:8088; browsers treat ``localhost`` as a secure origin, so the ``__Host-``
cookies work without TLS. Nothing listens on another interface and nothing leaves the computer.
"""

from .base import *  # noqa: F403
from .base import env

DEBUG = False
ALLOWED_HOSTS = [
    h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,api").split(",")
]
BANKING_PROCESS_INLINE = False  # the worker container parses imports, as when deployed
LOCAL_INSTALL = True  # the documents bucket is created on install (documents_dev_bucket)
