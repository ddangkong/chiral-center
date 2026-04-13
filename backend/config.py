from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    llm_provider: str = "openai"
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    embedding_model: str = "all-MiniLM-L6-v2"

    sim_max_turns: int = 20
    sim_platform: str = "discussion"

    tavily_api_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
