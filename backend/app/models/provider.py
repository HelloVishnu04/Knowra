import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.sql import func

from app.models.base import Base


class ProviderConfiguration(Base):
    __tablename__ = "provider_configurations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id = Column(
        String, ForeignKey("workspaces.id"), nullable=False, index=True
    )
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    provider_type = Column(String, nullable=False)
    base_url = Column(String, nullable=False)
    api_key_encrypted = Column(Text)
    api_key_version = Column(String)
    models_json = Column(JSON, nullable=False, default=list)
    is_enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
