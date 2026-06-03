"""Built-in identity schemes.

Importing this package registers every built-in scheme with the
:mod:`service.identity.registry`. Adding a new scheme means dropping a
module here and importing it from this file.
"""

from service.identity.schemes import eip191  # noqa: F401 — registration side effect
