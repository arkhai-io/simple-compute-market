"""Unit tests for registry startup helpers."""

from unittest.mock import AsyncMock

import pytest

import src.main as main_module


@pytest.mark.asyncio
async def test_start_event_sync_with_retries_recovers_from_transient_failure():
    service = AsyncMock()
    service.start = AsyncMock(side_effect=[ConnectionError("rpc not ready"), None])

    original_attempts = main_module.settings.event_sync_startup_attempts
    original_delay = main_module.settings.event_sync_startup_delay_secs
    try:
        main_module.settings.event_sync_startup_attempts = 3
        main_module.settings.event_sync_startup_delay_secs = 0
        await main_module.start_event_sync_with_retries(service, 1234)
    finally:
        main_module.settings.event_sync_startup_attempts = original_attempts
        main_module.settings.event_sync_startup_delay_secs = original_delay

    assert service.start.await_count == 2
    service.start.assert_any_await(1234)


@pytest.mark.asyncio
async def test_start_event_sync_with_retries_raises_after_final_attempt():
    service = AsyncMock()
    service.start = AsyncMock(side_effect=ConnectionError("still unavailable"))

    original_attempts = main_module.settings.event_sync_startup_attempts
    original_delay = main_module.settings.event_sync_startup_delay_secs
    try:
        main_module.settings.event_sync_startup_attempts = 2
        main_module.settings.event_sync_startup_delay_secs = 0
        with pytest.raises(ConnectionError, match="still unavailable"):
            await main_module.start_event_sync_with_retries(service, 1234)
    finally:
        main_module.settings.event_sync_startup_attempts = original_attempts
        main_module.settings.event_sync_startup_delay_secs = original_delay

    assert service.start.await_count == 2
