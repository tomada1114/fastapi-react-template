"""Domain model, ports, and services, free of any framework or I/O library.

Imports stay within the core and the deterministic standard-library allowlist,
``ALLOWED_STDLIB`` in ``tests/core/test_imports.py``. That test also rejects bare
I/O and dynamic-execution builtins, recognizable date/datetime clock reads,
local-time APIs without explicit timezones, and the ``uuid`` generators that
read a clock, randomness, or the host: the core may use the ``UUID`` type, and
new ids arrive through the ``IdFactory`` port. Ruff's TID251 is a fast subset
of the import rule. The same services therefore
serve every entry point and every storage adapter.
"""
