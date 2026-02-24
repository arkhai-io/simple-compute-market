"""Tests for worker.py entry point."""
from unittest.mock import patch


class TestMain:
    def test_main_calls_asyncio_run(self):
        """main() should call asyncio.run with process_jobs coroutine."""
        with patch("async_provisioning_service.worker.asyncio.run") as mock_run:
            from async_provisioning_service.worker import main
            main()
        mock_run.assert_called_once()

    def test_main_passes_process_jobs(self):
        """asyncio.run receives the coroutine returned by process_jobs()."""
        import asyncio as _asyncio

        with patch("async_provisioning_service.worker.asyncio.run") as mock_run:
            with patch("async_provisioning_service.worker.process_jobs") as mock_pj:
                from async_provisioning_service.worker import main
                main()
        # asyncio.run was called once with whatever process_jobs() returned
        mock_run.assert_called_once()
        args, _ = mock_run.call_args
        # process_jobs is an async function; its call returns a coroutine
        assert _asyncio.iscoroutine(args[0])
        args[0].close()  # avoid ResourceWarning for unawaited coroutine
