"""Gunicorn settings for deployed environments (values overridable by environment variables)."""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("GUNICORN_WORKERS", "3"))
threads = int(os.environ.get("GUNICORN_THREADS", "2"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))
graceful_timeout = 30
keepalive = 75  # longer than the load balancer's idle timeout (60 s) to avoid 502s
max_requests = 2000  # recycle workers to bound memory growth
max_requests_jitter = 200
# Only the load balancer inside the VPC may set X-Forwarded-* headers.
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
accesslog = None  # requests are logged by the app's redacting middleware (JSON on stdout)
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "warning")
worker_tmp_dir = "/dev/shm"  # noqa: S108 - in-memory heartbeat files; the root filesystem is read-only
