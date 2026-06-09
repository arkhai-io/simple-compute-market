"""Compatibility entry point for the VM buyer CLI.

The concrete executable lives under ``domains.vms.buyer``. This module keeps
the historical ``market_buyer.cli:app`` console-script target working while
the package migration is in progress.
"""

from domains.vms.buyer.cli import app


if __name__ == "__main__":
    app()
