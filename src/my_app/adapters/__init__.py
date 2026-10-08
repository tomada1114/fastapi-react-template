"""Implementations of the core's ports against concrete storage and services.

Each repository here satisfies ``my_app.core.ports.TodoRepository`` and passes
the one contract suite every implementation shares. The LLM adapters satisfy
``my_app.core.ports.LlmPort``: ``FakeLlm`` and ``OpenRouterLlm`` pass its
contract suite, and ``ClosedLlm`` is what an app without a key gets.
``openrouter`` is the only module that needs the optional ``ai`` extra.
"""
