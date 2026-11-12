from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App
    PROJECT_NAME: str = "OmniRAG API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    # Database
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/omnirag"
    REDIS_URL: str = "redis://localhost:6379/0"
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "documents_kb_phase3"
    EMBEDDING_MODEL: str = "embeddinggemma"
    SPARSE_MODEL: str = "Qdrant/bm25"
    HYBRID_RETRIEVAL_ENABLED: bool = True
    RETRIEVAL_CANDIDATE_LIMIT: int = 40
    RERANKER_ENABLED: bool = False
    RERANKER_MODEL: str = "BAAI/bge-reranker-base"
    RERANKER_CANDIDATE_LIMIT: int = 20
    CHUNK_TOKENIZER: str = "sentence-transformers/all-MiniLM-L6-v2"
    OBJECT_STORE: str = "local"
    OBJECT_STORE_PATH: str = "./data/objects"
    S3_BUCKET: str = ""
    S3_ENDPOINT_URL: str | None = None
    MAX_UPLOAD_BYTES: int = 25 * 1024 * 1024
    LOCAL_WORKSPACE_ID: str = "local-workspace"

    # Auth
    JWT_SECRET: str = "changeme"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8

    # LLM Providers
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OPENAI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    GOOGLE_API_KEY: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
