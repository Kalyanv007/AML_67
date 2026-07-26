from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_provider: str = "gemini"
    gemini_api_key: str = ""
    openai_api_key: str = ""
    groq_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b-instruct"
    # How long to keep the Ollama model in VRAM after the last call.
    # Prevents cold-start reload on every request (default Ollama idle = 5m).
    ollama_keep_alive: str = "30m"
    # Per-call LLM timeout in seconds.  Hosted APIs (Gemini/Groq/OpenAI) are
    # fast and rarely need more than 10s.  Local Ollama with a 14B model may
    # take 15-30s for longer prompts, so allow more headroom.
    llm_timeout_seconds: int = 60
    # Max number of flags per response that get an LLM-polished explanation
    # (top N by risk_score). Bounds worst-case per-request LLM call count
    # regardless of how many entities end up HIGH-risk — a full_analysis run
    # can produce 20+ HIGH flags, and at several seconds per call (especially
    # on local Ollama, which has no rate limit to fail fast on) that multiplies
    # past the frontend's request timeout. The rest still get the accurate
    # template-based explanation, just not LLM-rewritten prose.
    llm_polish_max_flags: int = 5

    aml_use_mocks: bool = True
    aml_dataset_path: str = "data/sample/aml_sample.csv"
    aml_api_base_url: str = "http://localhost:8000"


settings = Settings()
