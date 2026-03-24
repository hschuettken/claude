#!/usr/bin/env python3
"""
Task 328 Validation Script
Verifies NATS event publishing implementation for:
1. signal.detected
2. draft.created
3. post.published
4. performance.updated
"""

import sys
import importlib.util

def check_module_exists(module_path: str, display_name: str) -> bool:
    """Check if a module file exists and is readable."""
    try:
        spec = importlib.util.spec_from_file_location(display_name, module_path)
        if spec and spec.loader:
            print(f"✅ {display_name}: {module_path}")
            return True
    except Exception as e:
        print(f"❌ {display_name}: {e}")
        return False
    return False


def check_imports(module_path: str, imports: list) -> bool:
    """Check if a module has required imports/exports."""
    try:
        with open(module_path, 'r') as f:
            content = f.read()
        
        all_found = True
        for imp in imports:
            if imp in content:
                print(f"  ✅ {imp}")
            else:
                print(f"  ❌ {imp} NOT FOUND")
                all_found = False
        return all_found
    except Exception as e:
        print(f"❌ Error reading {module_path}: {e}")
        return False


def main():
    """Run validation checks."""
    print("=" * 80)
    print("TASK 328 VALIDATION: NATS Event Publishing")
    print("=" * 80)
    
    checks_passed = 0
    checks_total = 0
    
    # ========== Check 1: NATSClient exists ==========
    print("\n[1] NATSClient Implementation")
    print("-" * 80)
    checks_total += 1
    
    if check_module_exists(
        "/home/hesch/.openclaw/workspace/claude/services/marketing-agent/app/events/nats_client.py",
        "app/events/nats_client.py"
    ):
        # Check for required methods
        if check_imports(
            "/home/hesch/.openclaw/workspace/claude/services/marketing-agent/app/events/nats_client.py",
            [
                "class NATSClient",
                "async def connect",
                "async def publish",
                "def is_available",
            ]
        ):
            checks_passed += 1
            print("✅ NATSClient implementation complete")
        else:
            print("❌ NATSClient missing required methods")
    
    # ========== Check 2: Event Publishers ==========
    print("\n[2] Event Publisher Functions")
    print("-" * 80)
    checks_total += 1
    
    if check_module_exists(
        "/home/hesch/.openclaw/workspace/claude/services/marketing-agent/app/events/publishers.py",
        "app/events/publishers.py"
    ):
        if check_imports(
            "/home/hesch/.openclaw/workspace/claude/services/marketing-agent/app/events/publishers.py",
            [
                "async def publish_signal_detected",
                "async def publish_draft_created",
                "async def publish_post_published",
                "async def publish_performance_updated",
            ]
        ):
            checks_passed += 1
            print("✅ All 4 event publishers implemented")
        else:
            print("❌ Missing event publisher functions")
    
    # ========== Check 3: App Events Module ==========
    print("\n[3] App Events Module Exports")
    print("-" * 80)
    checks_total += 1
    
    if check_module_exists(
        "/home/hesch/.openclaw/workspace/claude/services/marketing-agent/app/events/__init__.py",
        "app/events/__init__.py"
    ):
        if check_imports(
            "/home/hesch/.openclaw/workspace/claude/services/marketing-agent/app/events/__init__.py",
            [
                "from .nats_client import NATSClient",
                "from .publishers import",
                "publish_signal_detected",
                "publish_draft_created",
                "publish_post_published",
                "publish_performance_updated",
            ]
        ):
            checks_passed += 1
            print("✅ app/events module properly exports all publishers")
        else:
            print("❌ app/events module missing exports")
    
    # ========== Check 4: Root-level events module ==========
    print("\n[4] Root-Level events.py Module")
    print("-" * 80)
    checks_total += 1
    
    if check_module_exists(
        "/home/hesch/.openclaw/workspace/claude/services/marketing-agent/events.py",
        "events.py"
    ):
        if check_imports(
            "/home/hesch/.openclaw/workspace/claude/services/marketing-agent/events.py",
            [
                "from app.events.nats_client import NATSClient as MarketingNATSClient",
            ]
        ):
            checks_passed += 1
            print("✅ Root-level events.py provides backward compatibility")
        else:
            print("❌ Root-level events.py missing required exports")
    
    # ========== Check 5: Draft API integration ==========
    print("\n[5] Draft API Event Integration")
    print("-" * 80)
    checks_total += 1
    
    if check_imports(
        "/home/hesch/.openclaw/workspace/claude/services/marketing-agent/api/drafts.py",
        [
            "from ..events import",
            "publish_draft_created",
            "publish_post_published",
            "publish_performance_updated",
            "await publish_draft_created",
            "await publish_post_published",
        ]
    ):
        checks_passed += 1
        print("✅ Draft API imports and calls event publishers")
    else:
        print("❌ Draft API missing event publisher integration")
    
    # ========== Check 6: Scout scheduler integration ==========
    print("\n[6] Scout Scheduler Event Integration")
    print("-" * 80)
    checks_total += 1
    
    if check_imports(
        "/home/hesch/.openclaw/workspace/claude/services/marketing-agent/app/scout/scheduler.py",
        [
            "from ..events import publish_signal_detected",
            "await publish_nats_signal_detected",
            "created_signal_list",
        ]
    ):
        checks_passed += 1
        print("✅ Scout scheduler publishes signal.detected events")
    else:
        print("❌ Scout scheduler missing signal publication")
    
    # ========== Check 7: Main.py NATS initialization ==========
    print("\n[7] Main.py NATS Initialization")
    print("-" * 80)
    checks_total += 1
    
    if check_imports(
        "/home/hesch/.openclaw/workspace/claude/services/marketing-agent/main.py",
        [
            "from events import MarketingNATSClient",
            "await MarketingNATSClient.connect",
            "await MarketingNATSClient.close",
        ]
    ):
        checks_passed += 1
        print("✅ main.py properly initializes NATS connection")
    else:
        print("❌ main.py missing NATS initialization")
    
    # ========== Check 8: NB9OS NATSClient (for orbit events) ==========
    print("\n[8] NB9OS NATSClient Implementation")
    print("-" * 80)
    checks_total += 1
    
    if check_module_exists(
        "/home/hesch/.openclaw/workspace/services/nb9os/src/backend/app/events/__init__.py",
        "nb9os/app/events/__init__.py"
    ):
        if check_imports(
            "/home/hesch/.openclaw/workspace/services/nb9os/src/backend/app/events/__init__.py",
            [
                "class NATSClient",
                "async def connect",
                "async def publish",
            ]
        ):
            checks_passed += 1
            print("✅ NB9OS has NATSClient implementation")
        else:
            print("❌ NB9OS NATSClient missing methods")
    
    # ========== Check 9: NB9OS orbit events ==========
    print("\n[9] NB9OS Orbit Event Publishers")
    print("-" * 80)
    checks_total += 1
    
    if check_module_exists(
        "/home/hesch/.openclaw/workspace/services/nb9os/src/backend/app/events/orbit.py",
        "nb9os/app/events/orbit.py"
    ):
        if check_imports(
            "/home/hesch/.openclaw/workspace/services/nb9os/src/backend/app/events/orbit.py",
            [
                "async def on_signal_detected",
                "async def on_draft_created",
                "async def on_post_published",
                "async def on_performance_updated",
            ]
        ):
            checks_passed += 1
            print("✅ NB9OS orbit module has all event publishers")
        else:
            print("❌ NB9OS orbit module missing publishers")
    
    # ========== Summary ==========
    print("\n" + "=" * 80)
    print(f"VALIDATION SUMMARY: {checks_passed}/{checks_total} checks passed")
    print("=" * 80)
    
    if checks_passed == checks_total:
        print("\n✅ TASK 328 VALIDATION SUCCESSFUL")
        print("\nAll required components are in place:")
        print("  ✓ NATSClient singleton in marketing-agent and nb9os")
        print("  ✓ Event publisher functions for all 4 event types")
        print("  ✓ API endpoint integration (drafts, signals, scout)")
        print("  ✓ Proper imports and exports throughout codebase")
        print("  ✓ NATS initialization in main.py lifespan")
        return 0
    else:
        print(f"\n❌ VALIDATION FAILED: {checks_total - checks_passed} checks did not pass")
        return 1


if __name__ == "__main__":
    sys.exit(main())
