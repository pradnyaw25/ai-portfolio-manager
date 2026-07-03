"""Observability: optional Langfuse tracing for the daily cycle.

All tracing is a no-op unless Langfuse credentials are configured, and every
Langfuse call is defensive — tracing must never break a run.
"""
