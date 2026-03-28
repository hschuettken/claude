# nats_consumer.py — top-level shim
# Uses importlib to avoid self-reference (this file IS named nats_consumer.py)
import os
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "app_nats_consumer",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "app", "nats_consumer.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
MarketingNATSConsumer = _mod.MarketingNATSConsumer

__all__ = ["MarketingNATSConsumer"]
