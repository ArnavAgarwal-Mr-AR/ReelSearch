#!/usr/bin/env python
"""
Worker process launcher for ReelSearch context generation.
Continuously processes background enrichment jobs from PostgreSQL outbox.
"""
import sys
import logging
from app.worker.context_worker import ContextWorker
from app.core.database import init_db_pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] ContextWorker: %(message)s"
)

if __name__ == "__main__":
    init_db_pool()
    worker = ContextWorker()
    try:
        worker.start_loop(poll_interval=1.0)
    except KeyboardInterrupt:
        worker.stop()
        sys.exit(0)
