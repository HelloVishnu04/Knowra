import uuid
# pyrefly: ignore [missing-import]
from sqlalchemy import Column, String, DateTime, ForeignKey, JSON
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.models.base import Base

class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    title = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Message(Base):
    __tablename__ = "messages"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String, ForeignKey("conversations.id"), nullable=False)
    role = Column(String, nullable=False)
    content = Column(String, nullable=False)
    run_id = Column(String)
    citations_json = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
