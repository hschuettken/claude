import re

with open('main.py', 'r') as f:
    content = f.read()

# Find and replace the idea_vault import section
old_section = """from idea_vault import (
    IdeaVaultService,
    CaptureRequest,
    CaptureResponse,
    IdeaCard,
    CaptureType,
    PillarTag,
)

# Configure logging"""

new_section = """from idea_vault import (
    IdeaVaultService,
    CaptureRequest,
    CaptureResponse,
    IdeaCard,
    CaptureType,
    PillarTag,
)

try:
    from life_nav_routes import router as life_nav_router
    LIFE_NAV_AVAILABLE = True
except ImportError:
    LIFE_NAV_AVAILABLE = False

try:
    from family_os_routes import router as family_os_router
    FAMILY_OS_AVAILABLE = True
except ImportError:
    FAMILY_OS_AVAILABLE = False

# Configure logging"""

content = content.replace(old_section, new_section)

# Find and replace the startup event
old_startup = """@app.on_event("startup")
async def startup_event():
    \"\"\"Initialize service on startup.\"\"\"
    global startup_time
    startup_time = datetime.utcnow()
    logger.info("Backend Service starting up...")
    logger.info(f"Environment: {os.getenv('ENVIRONMENT', 'development')}")\"""

new_startup = """@app.on_event("startup")
async def startup_event():
    \"\"\"Initialize service on startup.\"\"\"
    global startup_time
    startup_time = datetime.utcnow()
    logger.info("Backend Service starting up...")
    logger.info(f"Environment: {os.getenv('ENVIRONMENT', 'development')}")
    
    # Register optional routers
    if LIFE_NAV_AVAILABLE:
        app.include_router(life_nav_router)
        logger.info("Life Navigation router registered")
    
    if FAMILY_OS_AVAILABLE:
        app.include_router(family_os_router)
        logger.info("Family OS router registered")\"""

content = content.replace(old_startup, new_startup)

with open('main.py', 'w') as f:
    f.write(content)

print("✓ main.py patched successfully")
