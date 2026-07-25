from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_provider: str = "gemini"
    gemini_api_key: str = ""
    openai_api_key: str = ""
    groq_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b-instruct"

    aml_use_mocks: bool = True
    aml_dataset_path: str = "data/sample/aml_sample.csv"
    aml_api_base_url: str = "http://localhost:8000"


settings = Settings()
