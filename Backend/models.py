from .database import Base
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Text, ForeignKey, BigInteger, func, DateTime
import datetime
from typing import List, Optional

class User(Base):
    __tablename__ = "chat_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    sessions: Mapped[List["ChatSession"]] = relationship("ChatSession", back_populates="user", cascade="all, delete-orphan")

class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("chat_users.id"), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[datetime.datetime] = mapped_column(
         DateTime(timezone=True), server_default=func.now()
    )
    last_updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="sessions")
    messages: Mapped[List["ChatMessage"]] = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.timestamp")

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    session_id: Mapped[str] = mapped_column(String, ForeignKey("chat_sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False) # "user" or "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped["ChatSession"] = relationship("ChatSession", back_populates="messages")



# --- Pydantic Models for API ---
class UserCreate(BaseModel):
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserPublic(BaseModel):
    id: int
    email: EmailStr
    class Config:
        from_attributes = True 

class SessionInfo(BaseModel):
    id: str
    title: Optional[str] = None
    last_updated_at: datetime.datetime

    class Config:
        from_attributes = True

class MessageInfo(BaseModel):
    id: int
    role: str
    content: str
    timestamp: datetime.datetime 
    class Config:
        from_attributes = True

class SessionDetail(SessionInfo):
    messages: List[MessageInfo] = []

class InitiateChatRequestApi(BaseModel): 
    session_id: Optional[str] = None 
    user_message: str

class InitiateChatResponseApi(BaseModel):
    session_id: str
    user_message_id: int
    stream_id: str # ID to use for the SSE connection