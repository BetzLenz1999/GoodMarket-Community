import multiprocessing
import os

# ─── Workers & Threads ───────────────────────────────────────────────────────
# Autoscale handles horizontal scaling (multiple instances).
# Per instance: keep workers moderate to ensure fast startup on cold starts.
workers = min(2 * multiprocessing.cpu_count() + 1, 4)
threads = 4
worker_class = "gthread"

# ─── Binding ─────────────────────────────────────────────────────────────────
# Always read PORT from environment — required for Autoscale / Cloud Run.
port = os.environ.get("PORT", "5000")
bind = f"0.0.0.0:{port}"
reuse_port = True

# ─── Timeouts ────────────────────────────────────────────────────────────────
timeout = 120         # Kill worker if silent for 120 s
graceful_timeout = 30 # Grace period on SIGTERM before SIGKILL
keepalive = 5         # Keep idle HTTP connections open 5 s (reuse TCP)

# ─── Connection queue ────────────────────────────────────────────────────────
backlog = 512

# ─── Memory protection ───────────────────────────────────────────────────────
max_requests = 500
max_requests_jitter = 50

# ─── Logging ─────────────────────────────────────────────────────────────────
accesslog = "-"
errorlog  = "-"
loglevel  = "warning"
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(D)sµs'

# ─── Preload ─────────────────────────────────────────────────────────────────
# Disabled so each worker initialises independently — safer for cold starts
# in autoscale environments where init failures must not block all workers.
preload_app = False
