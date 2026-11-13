"""Optional single-enterprise PostgreSQL worker for durable in-app ticket reminders.

Operator entry point only; product jobs are explicitly opt-in and retain model budgets.
No migrations or external notifications.
"""

import argparse
import logging
import time
from types import SimpleNamespace

from support_agent.config import Settings
from support_agent.db import (
    authorization_gate,
    build_database,
    check_database,
    private_tenant,
    set_tenant,
)
from support_agent.models import Tenant
from support_agent.services.customer_memory import expire
from support_agent.services.desk import notify_overdue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=30, choices=range(10, 3601))
    parser.add_argument(
        "--product-jobs",
        action="store_true",
        help="Process authorized embedding, export and staff-draft jobs",
    )
    args = parser.parse_args()
    settings = Settings()
    engine, sessions = build_database(settings)
    if args.product_jobs:
        from support_agent.demo_provider import DemoProvider
        from support_agent.providers import OpenAICompatibleProvider
        from support_agent.retrieval import PostgresFTSRetriever
        from support_agent.services import customer_exports, drafts, vector_index
        from support_agent.storage import document_storage

        state = SimpleNamespace(
            settings=settings,
            storage=document_storage(settings),
            retriever=PostgresFTSRetriever(),
            provider=OpenAICompatibleProvider(
                settings.model_allowed_hosts,
                enabled=settings.allow_external_models,
                private_hosts=settings.model_private_hosts,
            ),
            demo_provider=DemoProvider(),
        )
    logger = logging.getLogger("support_agent.worker")
    try:
        check_database(engine)
        while True:
            try:
                with sessions.begin() as db:
                    tid = private_tenant(db)
                    authorization_gate(db, tenant_id=tid)
                    set_tenant(db, tid)
                    if db.get(Tenant, tid).status == "active":
                        notify_overdue(db, tid)
                    expire(db, tid)
                if args.product_jobs:
                    for task in (
                        customer_exports.cleanup_one,
                        customer_exports.process_one,
                        drafts.process_one,
                        vector_index.process_one,
                    ):
                        with sessions() as db:
                            set_tenant(db, tid)
                            task(db, tid, state)
            except Exception:
                # No SQL, parameters, credentials or customer data in worker logs.
                logger.error("worker_batch_failed")
                if args.once:
                    raise SystemExit("Worker batch failed") from None
            if args.once:
                return
            time.sleep(args.interval)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
