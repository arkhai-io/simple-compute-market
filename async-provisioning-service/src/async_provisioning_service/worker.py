import asyncio
import logging

from async_provisioning_service.config import settings
from async_provisioning_service.services.job_processor import process_jobs


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def main() -> None:
    asyncio.run(process_jobs())


if __name__ == "__main__":
    main()
