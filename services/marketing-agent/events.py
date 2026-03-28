# events.py — top-level shim for MarketingNATSClient
# Uses importlib to avoid naming conflict (this file IS named events.py)
import os
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "app_events_nats_client",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "app", "events", "nats_client.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
NATSClient = _mod.NATSClient


class MarketingNATSClient:
    @classmethod
    async def connect(cls, url: str, user: str = None, password: str = None) -> bool:
        return await NATSClient.connect(url, user or "", password or "")

    @classmethod
    async def close(cls):
        return await NATSClient.close()

    @classmethod
    def is_available(cls) -> bool:
        return NATSClient.is_available()
