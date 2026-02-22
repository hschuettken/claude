"""Orchestrator service configuration.

Extends the shared Settings with orchestrator-specific fields for LLM,
Telegram, proactive features, and energy entity references.
"""

from __future__ import annotations

from shared.config import Settings as BaseSettings


class OrchestratorSettings(BaseSettings):
    # --- LLM provider ---
    llm_provider: str = "gemini"  # gemini | openai | anthropic | ollama
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    openai_model: str = "gpt-4o"
    anthropic_model: str = "claude-sonnet-4-20250514"
    ollama_model: str = "llama3"
    llm_max_tool_rounds: int = 10
    llm_temperature: float = 0.7
    llm_max_tokens: int = 4096  # max tokens for LLM response

    # --- Embedding models (for semantic memory) ---
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_embedding_dims: int = 768
    openai_embedding_model: str = "text-embedding-3-small"
    ollama_embedding_model: str = "nomic-embed-text"

    # --- Telegram ---
    telegram_bot_token: str = ""
    telegram_allowed_chat_ids: str = ""  # comma-separated chat IDs

    # --- Proactive features ---
    morning_briefing_time: str = "07:00"  # HH:MM local time
    evening_briefing_time: str = "21:00"
    proactive_check_interval_minutes: int = 30
    enable_proactive_suggestions: bool = True
    enable_morning_briefing: bool = True
    enable_evening_briefing: bool = False
    proactive_startup_delay_seconds: int = 120  # delay before optimization suggestions start
    consolidation_startup_delay_seconds: int = 300  # delay before memory consolidation starts
    consolidation_check_interval_seconds: int = 600  # how often to check if consolidation is due

    # --- Energy entities (defaults match CLAUDE.md setup) ---
    grid_power_entity: str = "sensor.power_meter_active_power"
    house_power_entity: str = "sensor.shelly3em_main_channel_total_power"
    pv_power_entity: str = "sensor.inverter_input_power"
    pv_ac_output_entity: str = "sensor.inverter_active_power"
    battery_power_entity: str = "sensor.batteries_charge_discharge_power"
    battery_soc_entity: str = "sensor.batteries_state_of_capacity"
    ev_power_entity: str = "sensor.amtron_meter_total_power_w"
    ev_energy_entity: str = "sensor.amtron_meter_total_energy_kwh"

    # PV forecast sensors (from pv-forecast service)
    pv_forecast_today_entity: str = "sensor.pv_ai_forecast_today_kwh"
    pv_forecast_today_remaining_entity: str = "sensor.pv_ai_forecast_today_remaining_kwh"
    pv_forecast_tomorrow_entity: str = "sensor.pv_ai_forecast_tomorrow_kwh"

    # PV production sensors
    pv_east_energy_entity: str = "sensor.inverter_pv_east_energy"
    pv_west_energy_entity: str = "sensor.inverter_pv_west_energy"

    # EV charging helpers
    ev_charge_mode_entity: str = "input_select.ev_charge_mode"
    ev_target_energy_entity: str = "input_number.ev_target_energy_kwh"
    ev_departure_time_entity: str = "input_datetime.ev_departure_time"

    # Weather
    weather_entity: str = "weather.forecast_home"

    # Energy prices
    epex_price_entity: str = "sensor.epex_spot_data_price_2"
    grid_price_ct: float = 25.0
    feed_in_tariff_ct: float = 7.0
    oil_price_per_kwh_ct: float = 10.0

    # --- Google Calendar ---
    google_calendar_credentials_file: str = ""  # path to service account JSON key
    google_calendar_credentials_json: str = ""  # or base64-encoded JSON (for Docker)
    google_calendar_family_id: str = ""  # shared family calendar (read-only)
    google_calendar_orchestrator_id: str = ""  # orchestrator's own calendar (read/write)

    # --- Memory ---
    max_conversation_history: int = 50
    max_decisions: int = 500  # max decision log entries
    enable_semantic_memory: bool = True  # vector-based long-term memory

    # --- Knowledge store (structured facts + memory.md) ---
    enable_knowledge_store: bool = True  # structured knowledge persistence
    memory_document_max_size: int = 4000  # max chars for memory.md (injected into context)
    knowledge_auto_extract: bool = True  # LLM auto-extracts structured facts from conversations

    # --- Semantic memory tuning ---
    semantic_memory_max_entries: int = 5000  # cap to keep file size reasonable
    semantic_memory_text_max_len: int = 2000  # truncate text before embedding
    semantic_memory_search_top_k: int = 5  # default number of search results
    semantic_memory_recency_weight: float = 0.15  # 0=pure similarity, 1=pure recency
    semantic_memory_recency_half_life_days: int = 30  # recency decay half-life
    memory_similarity_threshold: float = 0.5  # min similarity for context injection
    memory_context_results: int = 3  # semantic results injected into LLM context

    # --- Memory consolidation ---
    memory_consolidation_hour: int = 3  # hour (local time) for nightly consolidation
    memory_consolidation_min_age_days: float = 1.0  # min age before consolidation
    memory_consolidation_batch_limit: int = 50  # max entries per consolidation run
    memory_consolidation_batch_size: int = 10  # entries per consolidation batch
    memory_consolidation_min_batch_size: int = 5  # min entries to trigger consolidation

    # --- API server (REST + MCP) ---
    orchestrator_api_port: int = 8100  # Port for REST API + MCP server
    orchestrator_api_key: str = ""  # X-API-Key for authentication (empty = deny all)
    orchestrator_api_host: str = "0.0.0.0"  # Bind address

    # --- Household info ---
    household_users: str = "Henning,Nicole"  # comma-separated
    household_language: str = "de"  # default response language

    @property
    def allowed_chat_ids(self) -> list[int]:
        if not self.telegram_allowed_chat_ids:
            return []
        return [int(x.strip()) for x in self.telegram_allowed_chat_ids.split(",") if x.strip()]

    @property
    def user_list(self) -> list[str]:
        return [u.strip() for u in self.household_users.split(",") if u.strip()]
