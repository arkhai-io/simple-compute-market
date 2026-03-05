# DEPRECATED — kept for backward compat. Import from service.clients.market directly.
from service.clients.market import (  # noqa: F401
    MarketProvider,
    StaticMarketProvider,
    RedisMarketProvider,
    create_market_provider,
)
