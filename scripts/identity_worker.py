"""Worker contínuo para entrega da outbox de e-mails de identidade."""

import asyncio
import logging

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.services.identity_token_service import dispatch_pending_emails, get_email_provider

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def run() -> None:
    settings = get_settings()
    provider = get_email_provider()
    while True:
        try:
            async with async_session_factory() as db:
                delivered = await dispatch_pending_emails(db, provider)
                if delivered:
                    logger.info("identity outbox delivered count=%s", delivered)
        except Exception:  # noqa: BLE001
            logger.exception("identity outbox cycle failed")
        await asyncio.sleep(settings.identity_worker_poll_seconds)


if __name__ == "__main__":
    asyncio.run(run())
