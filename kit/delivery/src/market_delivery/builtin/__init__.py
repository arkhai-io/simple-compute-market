"""Built-in sinks: a local file, a local program, an HTTP endpoint, and mail.

Each is protocol-thin on purpose. None interprets a contact key or the
advertised channel, and none pulls in a third-party dependency. Anything
richer belongs in an installed sink package, which is why the four register
through the same entry-point group a third-party sink uses.
"""

from .command_sink import build_command_sink
from .file_sink import build_file_sink
from .smtp_sink import build_smtp_sink
from .webhook_sink import build_webhook_sink

__all__ = [
    "build_command_sink",
    "build_file_sink",
    "build_smtp_sink",
    "build_webhook_sink",
]
