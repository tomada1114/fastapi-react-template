"""The HTTP entry point: a FastAPI app over the core services.

``my_app.api.app.create_app`` builds it; routers translate HTTP to service
calls and domain errors back to status codes, and hold no rules of their own.
"""
