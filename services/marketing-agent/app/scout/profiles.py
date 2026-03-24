"""Search profiles for Scout Engine."""

from dataclasses import dataclass


@dataclass
class SearchProfile:
    """Configuration for a search profile."""

    id: str
    name: str
    queries: list[str]
    engines: list[str]
    pillar_id: int
    interval_hours: int


# Default search profiles
DEFAULT_PROFILES = [
    SearchProfile(
        id="sap_datasphere",
        name="SAP Datasphere News",
        queries=[
            "SAP Datasphere new features 2025",
            "SAP Datasphere release notes",
            "SAP Business Data Cloud",
        ],
        engines=["google", "bing", "duckduckgo"],
        pillar_id=1,
        interval_hours=4,
    ),
    SearchProfile(
        id="sap_community",
        name="SAP Community Activity",
        queries=[
            "SAP Analytics Cloud site:community.sap.com",
            "SAP Datasphere modeling site:community.sap.com",
            "SAP community discussions 2025",
        ],
        engines=["google"],
        pillar_id=5,
        interval_hours=8,
    ),
    SearchProfile(
        id="sap_release",
        name="SAP Release Notes",
        queries=[
            "SAP Datasphere release notes 2025",
            "SAP BTP release notes Q1 2025",
            "SAP product roadmap 2025",
        ],
        engines=["google"],
        pillar_id=2,
        interval_hours=24,
    ),
    SearchProfile(
        id="ai_enterprise",
        name="AI in Enterprise",
        queries=[
            "enterprise AI data architecture 2025",
            "LLM enterprise integration",
            "generative AI data governance",
        ],
        engines=["google", "bing"],
        pillar_id=4,
        interval_hours=12,
    ),
    SearchProfile(
        id="linkedin_signals",
        name="LinkedIn Thought Leader Signals",
        queries=[
            "SAP data architect site:linkedin.com",
            "datasphere analytics site:linkedin.com",
            "enterprise data strategy 2025 site:linkedin.com",
        ],
        engines=["google"],
        pillar_id=3,
        interval_hours=12,
    ),
]


def get_default_profiles() -> list[SearchProfile]:
    """Get all default search profiles."""
    return DEFAULT_PROFILES


def get_profile_by_id(profile_id: str) -> SearchProfile | None:
    """Get a profile by ID."""
    for profile in DEFAULT_PROFILES:
        if profile.id == profile_id:
            return profile
    return None
