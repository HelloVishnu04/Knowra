import base64
import json
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App
    PROJECT_NAME: str = "Knowra API"
    VERSION: str = "1.0.0"
    APP_ENVIRONMENT: Literal["development", "test", "production"] = "development"
    API_V1_STR: str = "/api/v1"
    DIAGNOSTIC_TIMEOUT_SECONDS: float = 2.0
    ALLOW_MODEL_DOWNLOADS: bool = False

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
    LANGGRAPH_CHECKPOINTER: str = "redis"
    AGENT_TOP_K: int = 8
    SQL_DATABASE_URL: str = ""
    SQL_ALLOWED_TABLES: str = ""
    SQL_SENSITIVE_TABLES: str = ""
    DEFAULT_ROW_LIMIT: int = 100
    STATEMENT_TIMEOUT_MS: int = 10000
    CODE_REPOSITORY_PATH: str = "./data/repositories"
    CODE_LOCAL_ROOT: str = ""
    CODE_GIT_ALLOWED_HOSTS: str = "github.com,gitlab.com"
    CODE_COLLECTION: str = "code_symbols_phase6"
    CODE_MAX_ARCHIVE_BYTES: int = 50 * 1024 * 1024
    CODE_MAX_EXTRACTED_BYTES: int = 250 * 1024 * 1024
    CODE_MAX_FILES: int = 20000
    CODE_MAX_SOURCE_BYTES: int = 1024 * 1024
    CODE_PARSER_TIMEOUT_SECONDS: int = 20
    CODE_PARSER_MEMORY_MB: int = 512
    CODE_INDEX_EMBEDDINGS: bool = False
    EDITOR_MAX_FILE_BYTES: int = 1024 * 1024
    EDITOR_MAX_WORKSPACE_BYTES: int = 64 * 1024 * 1024
    SANDBOX_EXECUTION_ENABLED: bool = False
    SANDBOX_QUEUE: str = "queue:sandbox"
    SANDBOX_PYTHON_IMAGE: str = "knowra-sandbox-python:phase8"
    SANDBOX_NODE_IMAGE: str = "knowra-sandbox-node:phase8"
    SANDBOX_WALL_TIMEOUT_SECONDS: int = 60
    SANDBOX_MEMORY_BYTES: int = 512 * 1024 * 1024
    SANDBOX_PIDS_LIMIT: int = 128
    SANDBOX_SNAPSHOT_BYTES: int = 10 * 1024 * 1024
    SANDBOX_OUTPUT_BYTES: int = 1024 * 1024

    # Auth
    JWT_SECRET: str = "changeme"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 8
    AUTH_REQUIRED: bool = False
    AUTH_COOKIE_SECURE: bool = False
    CORS_ALLOWED_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"
    REGISTRATION_ENABLED: bool = True
    AUTH_FAILURE_LIMIT: int = 5
    AUTH_FAILURE_WINDOW_MINUTES: int = 15
    AUTH_LOCKOUT_MINUTES: int = 15

    # Provider network policy
    PROVIDER_BLOCK_PRIVATE_NETWORKS: bool = False
    PROVIDER_PRIVATE_HOST_ALLOWLIST: str = ""
    PROVIDER_ENCRYPTION_ACTIVE_KEY_ID: str = "local-v1"
    PROVIDER_ENCRYPTION_KEYS: str = ""
    PROVIDER_ALLOW_LEGACY_JWT_KEY: bool = True

    # Web retrieval
    WEB_RETRIEVAL_ENABLED: bool = True
    WEB_SEARCH_PROVIDER: Literal["duckduckgo", "tavily", "searxng", "brave"] = (
        "duckduckgo"
    )
    WEB_SEARCH_API_KEY: str = ""
    WEB_SEARXNG_URL: str = ""
    WEB_TIMEOUT_SECONDS: float = 10.0
    WEB_MAX_RESULTS: int = 5
    WEB_FETCH_PAGE_CONTENT: bool = True
    WEB_MAX_PAGE_BYTES: int = 512 * 1024
    WEB_MAX_CONTENT_CHARS: int = 2500
    WEB_BLOCK_PRIVATE_NETWORKS: bool = True
    WEB_ALLOWED_DOMAINS: str = ""
    WEB_BLOCKED_DOMAINS: str = ""

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

    @model_validator(mode="after")
    def validate_production_security(self):
        if self.APP_ENVIRONMENT != "production":
            return self
        weak_secrets = {"changeme", "local-development-change-me", ""}
        if self.JWT_SECRET in weak_secrets or len(self.JWT_SECRET) < 32:
            raise ValueError(
                "Production JWT_SECRET must be a unique value of 32+ characters"
            )
        if not self.AUTH_REQUIRED:
            raise ValueError("Production requires AUTH_REQUIRED=true")
        if not self.AUTH_COOKIE_SECURE:
            raise ValueError("Production requires AUTH_COOKIE_SECURE=true")
        if not self.PROVIDER_BLOCK_PRIVATE_NETWORKS:
            raise ValueError("Production requires PROVIDER_BLOCK_PRIVATE_NETWORKS=true")
        try:
            keyring = json.loads(self.PROVIDER_ENCRYPTION_KEYS)
            active_key = keyring[self.PROVIDER_ENCRYPTION_ACTIVE_KEY_ID]
            decoded_key = base64.urlsafe_b64decode(active_key)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "Production requires a valid PROVIDER_ENCRYPTION_KEYS keyring "
                "containing PROVIDER_ENCRYPTION_ACTIVE_KEY_ID"
            ) from exc
        if (
            not isinstance(keyring, dict)
            or not isinstance(active_key, str)
            or len(decoded_key) != 32
            or ":" in self.PROVIDER_ENCRYPTION_ACTIVE_KEY_ID
        ):
            raise ValueError(
                "Production provider encryption keys must be named Fernet keys"
            )
        return self


settings = Settings()
