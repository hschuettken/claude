"""
NATS JetStream Publisher for Orchestrator — Task 144

Publishes HEMS (Home Energy Management System) events to the NATS HEMS stream:
- hems.ev.charge_started — EV charging session started
- hems.ev.charge_completed — EV charging session completed
- hems.pv.surplus — PV (solar) surplus available

These events are consumed by:
- NB9OS HEMS API for dashboard updates
- Home Assistant automations
- Energy optimization algorithms
"""

import json
import logging
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    import nats
    from nats.js.api import PublishAck
except ImportError:
    nats = None
    PublishAck = None


class HemsNatsPublisher:
    """Publisher for HEMS events to NATS JetStream."""
    
    _instance = None
    _nc: Optional[nats.NATS] = None
    _js: Optional[nats.js.JetStreamContext] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    async def connect(
        cls,
        url: str = "nats://localhost:4222",
        user: str = "client",
        password: str = "client-secret",
    ) -> bool:
        """
        Connect to NATS server.
        
        Args:
            url: NATS connection URL
            user: Username for auth
            password: Password for auth
        
        Returns:
            True if connected, False otherwise
        """
        if nats is None:
            logger.warning(
                "nats-py not installed. Install with: pip install nats-py"
            )
            return False
        
        try:
            cls._nc = await nats.connect(
                url,
                user=user,
                password=password,
                max_reconnect_attempts=3,
                reconnect_time_wait=2,
            )
            cls._js = cls._nc.jetstream()
            logger.info(f"✅ HEMS NATS publisher connected: {url}")
            return True
        
        except Exception as e:
            logger.warning(f"⚠️  Failed to connect NATS publisher: {e}")
            return False
    
    @classmethod
    async def publish_ev_charge_started(
        cls,
        vehicle_id: str,
        charger_id: str,
        power_kw: float,
        estimated_duration_minutes: Optional[int] = None,
        target_soc_pct: Optional[int] = None,
    ) -> bool:
        """
        Publish EV charging started event.
        
        Args:
            vehicle_id: Vehicle identifier (e.g., "tesla")
            charger_id: Charger identifier (e.g., "wallbox_garage")
            power_kw: Charging power in kW
            estimated_duration_minutes: Estimated charging time
            target_soc_pct: Target state of charge percentage
        
        Returns:
            True if published, False on error
        """
        if cls._js is None:
            return False
        
        try:
            payload = {
                "vehicle_id": vehicle_id,
                "charger_id": charger_id,
                "power_kw": power_kw,
                "estimated_duration_minutes": estimated_duration_minutes,
                "target_soc_pct": target_soc_pct,
                "timestamp": datetime.utcnow().isoformat(),
                "event_type": "charge_started",
            }
            
            message = json.dumps(payload).encode()
            await cls._js.publish("hems.ev.charge_started", message)
            
            logger.info(
                f"📤 Published hems.ev.charge_started: {vehicle_id} @ {power_kw}kW"
            )
            return True
        
        except Exception as e:
            logger.warning(f"⚠️  Failed to publish charge_started: {e}")
            return False
    
    @classmethod
    async def publish_ev_charge_completed(
        cls,
        vehicle_id: str,
        charger_id: str,
        energy_delivered_kwh: float,
        duration_minutes: int,
        final_soc_pct: Optional[int] = None,
    ) -> bool:
        """
        Publish EV charging completed event.
        
        Args:
            vehicle_id: Vehicle identifier
            charger_id: Charger identifier
            energy_delivered_kwh: Energy delivered in kWh
            duration_minutes: Charging duration in minutes
            final_soc_pct: Final state of charge percentage
        
        Returns:
            True if published, False on error
        """
        if cls._js is None:
            return False
        
        try:
            payload = {
                "vehicle_id": vehicle_id,
                "charger_id": charger_id,
                "energy_delivered_kwh": energy_delivered_kwh,
                "duration_minutes": duration_minutes,
                "final_soc_pct": final_soc_pct,
                "cost_usd": round(energy_delivered_kwh * 0.15, 2),  # Approx $0.15/kWh
                "timestamp": datetime.utcnow().isoformat(),
                "event_type": "charge_completed",
            }
            
            message = json.dumps(payload).encode()
            await cls._js.publish("hems.ev.charge_completed", message)
            
            logger.info(
                f"📤 Published hems.ev.charge_completed: {vehicle_id} "
                f"({energy_delivered_kwh}kWh in {duration_minutes}min)"
            )
            return True
        
        except Exception as e:
            logger.warning(f"⚠️  Failed to publish charge_completed: {e}")
            return False
    
    @classmethod
    async def publish_pv_surplus(
        cls,
        power_kw: float,
        available_minutes: int,
        efficiency_pct: int = 100,
        recommended_action: Optional[str] = None,
    ) -> bool:
        """
        Publish PV (solar) surplus available event.
        
        This event indicates that solar production exceeds consumption
        and surplus energy is available for charging, heating, or export.
        
        Args:
            power_kw: Surplus power in kW
            available_minutes: Estimated duration of surplus in minutes
            efficiency_pct: System efficiency (default 100%)
            recommended_action: Optional recommendation (e.g., "start_ev_charge")
        
        Returns:
            True if published, False on error
        """
        if cls._js is None:
            return False
        
        try:
            payload = {
                "power_kw": power_kw,
                "available_minutes": available_minutes,
                "efficiency_pct": efficiency_pct,
                "recommended_action": recommended_action,
                "timestamp": datetime.utcnow().isoformat(),
                "event_type": "pv_surplus",
            }
            
            message = json.dumps(payload).encode()
            await cls._js.publish("hems.pv.surplus", message)
            
            logger.info(
                f"📤 Published hems.pv.surplus: {power_kw}kW available for {available_minutes}min"
            )
            return True
        
        except Exception as e:
            logger.warning(f"⚠️  Failed to publish pv_surplus: {e}")
            return False
    
    @classmethod
    async def publish_hems_event(
        cls,
        subject: str,
        payload: Dict[str, Any],
    ) -> bool:
        """
        Publish a generic HEMS event.
        
        Args:
            subject: Subject under hems.> (e.g., "ev.custom", "heating.mode_changed")
            payload: Event payload dict
        
        Returns:
            True if published, False on error
        """
        if cls._js is None:
            return False
        
        try:
            # Ensure timestamp is present
            if "timestamp" not in payload:
                payload["timestamp"] = datetime.utcnow().isoformat()
            
            message = json.dumps(payload).encode()
            full_subject = f"hems.{subject}" if not subject.startswith("hems.") else subject
            await cls._js.publish(full_subject, message)
            
            logger.debug(f"📤 Published {full_subject}")
            return True
        
        except Exception as e:
            logger.warning(f"⚠️  Failed to publish HEMS event: {e}")
            return False
    
    @classmethod
    async def close(cls) -> None:
        """Close NATS connection gracefully."""
        if cls._nc and cls._nc.is_connected:
            try:
                await cls._nc.close()
                logger.info("HEMS NATS publisher closed")
            except Exception as e:
                logger.error(f"Error closing NATS: {e}")
            finally:
                cls._nc = None
                cls._js = None


# Singleton instance
hems_nats_publisher = HemsNatsPublisher()


# Module-level convenience functions
async def init_hems_nats(
    url: str = "nats://localhost:4222",
    user: str = "client",
    password: str = "client-secret",
) -> bool:
    """Initialize HEMS NATS publisher."""
    return await hems_nats_publisher.connect(url, user, password)


async def publish_ev_charge_started(
    vehicle_id: str,
    charger_id: str,
    power_kw: float,
    estimated_duration_minutes: Optional[int] = None,
    target_soc_pct: Optional[int] = None,
) -> bool:
    """Publish EV charge started event."""
    return await hems_nats_publisher.publish_ev_charge_started(
        vehicle_id, charger_id, power_kw, estimated_duration_minutes, target_soc_pct
    )


async def publish_ev_charge_completed(
    vehicle_id: str,
    charger_id: str,
    energy_delivered_kwh: float,
    duration_minutes: int,
    final_soc_pct: Optional[int] = None,
) -> bool:
    """Publish EV charge completed event."""
    return await hems_nats_publisher.publish_ev_charge_completed(
        vehicle_id, charger_id, energy_delivered_kwh, duration_minutes, final_soc_pct
    )


async def publish_pv_surplus(
    power_kw: float,
    available_minutes: int,
    efficiency_pct: int = 100,
    recommended_action: Optional[str] = None,
) -> bool:
    """Publish PV surplus event."""
    return await hems_nats_publisher.publish_pv_surplus(
        power_kw, available_minutes, efficiency_pct, recommended_action
    )


async def close_hems_nats() -> None:
    """Close HEMS NATS publisher."""
    await hems_nats_publisher.close()
