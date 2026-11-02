"""The `frp-grant-admission` command: `serve` the plugin, or `check` a configuration.

`check` loads a file exactly as startup and reload do, without touching a running
plugin, and prints each issuer's range and its keys' thumbprints, so an operator can
match a key a signer sent to that signer's `kid` and to the plugin's log lines.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Sequence, TextIO

from frp_grant_admission.config import Config, ConfigError, load_config
from frp_grant_admission.decision_log import DecisionLog
from frp_grant_admission.server import Plugin, PluginServer, install_reload_on_sighup


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="frp-grant-admission",
        description="An frps server plugin admitting a proxy only for the port a signed grant names.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="serve frps's NewProxy requests")
    serve.add_argument("--config", required=True, help="the configuration file")
    check = commands.add_parser("check", help="validate a configuration file and list its keys")
    check.add_argument("config", help="the configuration file")
    arguments = parser.parse_args(argv)

    if arguments.command == "check":
        return run_check(arguments.config, sys.stdout, sys.stderr)
    return run_serve(arguments.config)


def run_check(path: str, out: TextIO, err: TextIO) -> int:
    try:
        config = load_config(path)
    except ConfigError as error:
        print(f"{path} does not load:", file=err)
        for problem in error.problems:
            print(f"  {problem}", file=err)
        return 1
    print(describe(config), file=out)
    return 0


def describe(config: Config) -> str:
    lines = [f"listen {config.listen}"]
    for issuer in config.issuers:
        lines.append(
            f"issuer {issuer.name}: audience {issuer.audience}, "
            f"ports {issuer.port_start}-{issuer.port_end}"
        )
        lines.extend(f"  key {kid}" for kid in issuer.kids)
    return "\n".join(lines)


def run_serve(path: str, log: DecisionLog | None = None) -> int:
    server = start(path, log if log is not None else DecisionLog())
    if server is None:
        return 1
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def start(path: str, log: DecisionLog) -> PluginServer | None:
    """Load the file, bind its listen address, and reload on SIGHUP; None if it cannot.

    The handler is installed last, once startup has written its lines, so a reload
    never lands before the plugin is listening. A SIGHUP before then takes the
    default action and ends the process, which frps meets as a plugin that does not
    answer, refusing proxies until a supervisor starts it again.
    """
    try:
        config = load_config(path)
    except ConfigError as error:
        log.config_refused(error.problems, "startup", int(time.time()))
        return None
    plugin = Plugin(config, path, log)
    try:
        server = PluginServer((config.listen.host, config.listen.port), plugin)
    except OSError as error:
        problem = f"cannot listen on {config.listen}: {error.strerror or error}"
        log.config_refused((problem,), "startup", plugin.now())
        return None
    log.config_loaded(config, "startup", plugin.now())
    install_reload_on_sighup(plugin)
    return server


if __name__ == "__main__":
    sys.exit(main())
