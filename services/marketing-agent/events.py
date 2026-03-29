# events.py — top-level shim for MarketingNATSClient and publisher functions
# Uses importlib to avoid naming conflict (this file IS named events.py)
import os
import importlib.util

_base = os.path.dirname(os.path.abspath(__file__))

def _load_module(name, rel_path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_base, rel_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_nats_client_mod = _load_module("app_events_nats_client", "app/events/nats_client.py")
_publishers_mod = _load_module("app_events_publishers", "app/events/publishers.py")

NATSClient = _nats_client_mod.NATSClient

# Re-export publisher functions
publish_signal_detected = _publishers_mod.publish_signal_detected
publish_draft_created = _publishers_mod.publish_draft_created
publish_performance_updated = _publishers_mod.publish_performance_updated
publish_post_published = _publishers_mod.publish_post_published


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
