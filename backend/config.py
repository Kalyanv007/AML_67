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

    aml_use_mocks: bool = True
    aml_dataset_path: str = "data/sample/aml_sample.csv"
    aml_api_base_url: str = "http://localhost:8000"


settings = Settings()
