"""Local development settings. Never used in any deployed environment."""

from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

BANKING_PROCESS_INLINE = True  # no separate worker needed locally
