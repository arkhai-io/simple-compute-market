import asyncio
import logging

from async_provisioning_service.config import settings
from async_provisioning_service.services.worker import worker_loop


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def main() -> None:
    asyncio.run(worker_loop())


if __name__ == "__main__":
    main()
