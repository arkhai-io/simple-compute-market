"""Preserve proxy blocks while maintaining one root-only client baseline."""

import json
import os
from pathlib import Path
import re
import secrets
import sys


def prepare(path, values):
    original = path.read_text() if path.exists() else ""
    password = re.search(r'^webServer.password = "([a-f0-9]+)"$', original, re.M)
    fields = {
        **values,
        "auth.method": "token",
        "transport.tls.enable": True,
        "webServer.addr": "127.0.0.1",
        "webServer.user": "admin",
        "webServer.password": password.group(1) if password else secrets.token_hex(32),
        "log.to": "/var/log/frp/frpc-buyers.log",
        "log.level": "info",
        "log.maxDays": 30,
    }
    # TOML dotted keys must stay above array tables, or they become proxy fields.
    boundary = original.find("[[proxies]]")
    if boundary < 0:
        baseline, proxies = original, ""
    else:
        # Keep the marker with its proxy, rather than inserting inside its block.
        marker = original.rfind("# BEGIN ", 0, boundary)
        boundary = marker if marker >= 0 else boundary
        baseline, proxies = original[:boundary], original[boundary:]
    for key, value in fields.items():
        line = key + " = " + json.dumps(value, ensure_ascii=False)
        pattern = r"^" + re.escape(key) + r"\s*=.*$"
        if re.search(pattern, baseline, re.M):
            baseline = re.sub(pattern, lambda match: line, baseline, flags=re.M)
        else:
            baseline += line + "\n"
    updated = baseline + proxies
    # Open with a restrictive mode before writing any credential bytes.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        if updated != original:
            with os.fdopen(descriptor, "w") as stream:
                descriptor = None
                stream.write(updated)
                stream.truncate()
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return updated != original


def credentials(path):
    text = path.read_text()
    result = {}
    for key in ("webServer.password", "webServer.port"):
        match = re.search(r"^" + re.escape(key) + r"\s*=\s*(.+)$", text, re.M)
        if match is None:
            raise ValueError("Client admin configuration is incomplete")
        result[key] = json.loads(match.group(1))
    if not re.fullmatch(r"[a-f0-9]{64}", result["webServer.password"]):
        raise ValueError("Client admin password is invalid")
    if not 0 < result["webServer.port"] < 1024:
        raise ValueError("Client admin port is not privileged")
    return result


if __name__ == "__main__":
    action, filename = sys.argv[1:]
    config = Path(filename)
    if action == "prepare":
        print("changed" if prepare(config, json.load(sys.stdin)) else "unchanged")
    elif action == "credentials":
        print(json.dumps(credentials(config)))
    else:
        raise ValueError("Unknown client configuration action")
