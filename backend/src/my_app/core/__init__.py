"""Domain model, ports, and services, free of any framework or I/O library.

Imports stay within the core and the deterministic standard-library allowlist,
``ALLOWED_STDLIB`` in ``tests/core/test_imports.py``. That test also rejects bare
I/O and dynamic-execution builtins, recognizable date/datetime clock reads,
and local-time APIs without explicit timezones. Ruff's TID251 is a fast subset
of the import rule. The same services therefore
serve every entry point and every storage adapter. That holds for the
optional LLM layer too: ``ports.LlmPort`` and the values in ``llm`` are plain
Python, and only an adapter speaks HTTP to a provider.
"""
