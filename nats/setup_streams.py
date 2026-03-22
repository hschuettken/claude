#!/usr/bin/env python3
"""
NATS JetStream stream setup script.
Run once after NATS deployment to create all required streams.

Usage:
    python setup_streams.py --url nats://localhost:4222 --user nb9os --password <password>
"""

import asyncio
import json
import logging
import argparse
from typing import List
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


STREAMS = [
    {
        "name": "MARKETING",
        "subjects": ["marketing.>"],
        "retention": "limits",
        "max_age": 7 * 24 * 3600 * 1_000_000_000,  # 7 days in nanoseconds
        "storage": "file",
        "description": "Marketing agent events: signals, drafts, posts"
    },
    {
        "name": "ORBIT",
        "subjects": ["orbit.>"],
        "retention": "limits",
        "max_age": 30 * 24 * 3600 * 1_000_000_000,  # 30 days in nanoseconds
        "storage": "file",
        "description": "Orbit task/goal lifecycle events"
    },
    {
        "name": "SYNTHESIS",
        "subjects": ["synthesis.>"],
        "retention": "limits",
        "max_age": 3 * 24 * 3600 * 1_000_000_000,  # 3 days in nanoseconds
        "storage": "memory",
        "description": "SynthesisOS context snapshots, day shaper events"
    },
    {
        "name": "INFRA",
        "subjects": ["infra.>"],
        "retention": "limits",
        "max_age": 24 * 3600 * 1_000_000_000,  # 1 day in nanoseconds
        "storage": "memory",
        "description": "Container health, remediation events"
    },
    {
        "name": "HENNING",
        "subjects": ["henning.>"],
        "retention": "limits",
        "max_age": 30 * 24 * 3600 * 1_000_000_000,  # 30 days in nanoseconds
        "storage": "file",
        "description": "HenningGPT intents, actions, confirmations"
    }
]


async def setup_streams(nats_url: str, user: str, password: str) -> bool:
    """
    Connect to NATS and create all required streams.
    
    Returns True if all streams created/exist, False on error.
    """
    try:
        import nats
    except ImportError:
        logger.error("nats-py not installed. Install with: pip install nats-py")
        return False
    
    try:
        nc = await nats.connect(
            nats_url,
            user=user,
            password=password,
            max_reconnect_attempts=3,
            reconnect_time_wait=2
        )
        logger.info(f"✅ Connected to NATS: {nats_url}")
    except Exception as e:
        logger.error(f"❌ Failed to connect to NATS: {e}")
        return False
    
    js = nc.jetstream()
    success = True
    
    for stream_cfg in STREAMS:
        try:
            # Check if stream exists
            existing = None
            try:
                existing = await js.stream_info(stream_cfg["name"])
            except:
                pass
            
            if existing:
                logger.info(f"⏸️  Stream '{stream_cfg['name']}' already exists")
            else:
                await js.add_stream(
                    name=stream_cfg["name"],
                    subjects=stream_cfg["subjects"],
                    retention=stream_cfg["retention"],
                    max_age=stream_cfg["max_age"],
                    storage=stream_cfg["storage"],
                    description=stream_cfg["description"]
                )
                logger.info(f"✅ Stream '{stream_cfg['name']}' created")
        except Exception as e:
            logger.warning(f"⚠️  Stream '{stream_cfg['name']}': {e}")
            success = False
    
    try:
        await nc.close()
    except:
        pass
    
    return success


async def main():
    parser = argparse.ArgumentParser(description="Setup NATS JetStream streams")
    parser.add_argument("--url", default="nats://localhost:4222", help="NATS URL")
    parser.add_argument("--user", default="nb9os", help="NATS username")
    parser.add_argument("--password", required=True, help="NATS password")
    
    args = parser.parse_args()
    
    logger.info(f"Setting up NATS streams at {args.url}...")
    success = await setup_streams(args.url, args.user, args.password)
    
    if success:
        logger.info("✅ All streams configured successfully")
        sys.exit(0)
    else:
        logger.error("❌ Some streams failed to configure")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
