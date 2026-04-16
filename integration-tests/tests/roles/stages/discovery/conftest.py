"""Discovery stage fixtures.

Discovery's output fixture (``discovery_output``) and the
``seller_publishes`` trigger are defined in the parent stages/conftest.py
because they're consumed by every later stage as well. This file exists
only to allow stage-specific overrides if a discovery test needs a
variant (e.g. multiple sellers, no matching offers).
"""
