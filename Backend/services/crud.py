from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload 
from ..models import User, ChatSession, ChatMessage
from .auth import get_password_hash
import uuid
from typing import List, Optional

async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    result = await db.execute(select(User).filter(User.email == email))
    return result.scalar_one_or_none()

async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    result = await db.execute(select(User).filter(User.id == user_id))
    return result.scalar_one_or_none()

async def create_user(db: AsyncSession, email: str, password: str) -> User:
    hashed_password = get_password_hash(password)
    db_user = User(email=email, hashed_password=hashed_password)
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user

async def get_user_sessions(db: AsyncSession, user_id: int) -> List[ChatSession]:
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.last_updated_at.desc())
    )
    return result.scalars().all()

async def get_session_by_id(db: AsyncSession, session_id: str, user_id: int) -> Optional[ChatSession]:
     # Ensure user owns the session
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.id == session_id, ChatSession.user_id == user_id)
        .options(selectinload(ChatSession.messages)) # Eager load messages
    )
    return result.scalar_one_or_none()


async def create_chat_session(db: AsyncSession, user_id: int, title: Optional[str] = None) -> ChatSession:
    session_id = str(uuid.uuid4())
    db_session = ChatSession(id=session_id, user_id=user_id, title=title)
    db.add(db_session)
    # Flush to get the object associated with the session for refresh
    await db.flush([db_session])
    # Refresh to load defaults (like created_at) before returning
    await db.refresh(db_session)
    # REMOVE EXPLICIT COMMIT - Let the caller handle it
    # await db.commit() # <-- REMOVE THIS LINE
    return db_session

async def add_chat_message(db: AsyncSession, session_id: str, role: str, content: str) -> ChatMessage:
    """Adds a message and updates session timestamp."""
    # Update session timestamp
    stmt = (
         update(ChatSession)
         .where(ChatSession.id == session_id)
         .values(last_updated_at=func.now())
     )
    await db.execute(stmt)
    # Add message
    db_message = ChatMessage(session_id=session_id, role=role, content=content)
    db.add(db_message)
    # Flush and Refresh 
    await db.flush([db_message])

    await db.refresh(db_message)

    return db_message

async def delete_chat_session(db: AsyncSession, session_id: str, user_id: int):
    """
    Deletes a specific chat session and its related messages using ORM cascade.
    Ensures the user owns the session before deleting.
    Returns True if deleted, False if not found or not owned.
    """
    # 1. Fetch the session object first, ensuring ownership
    stmt = select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id)
    result = await db.execute(stmt)
    session_to_delete = result.scalar_one_or_none()

    if session_to_delete:

        await db.delete(session_to_delete)
        # --- Commit the deletion of the session and cascaded messages ---
        await db.commit() 
        print(f"CRUD: Deleted session {session_id} and its messages via ORM cascade.")
        # Indicate success
        return True
    else:
        # Session not found or doesn't belong to the user
        print(f"CRUD: Session {session_id} not found for user {user_id} or already deleted.")
        # Indicate session not found/deleted
        return False 

async def delete_all_user_sessions(db: AsyncSession, user_id: int):
    """
    Deletes all chat sessions for a user using ORM cascade for messages.
    """
    # --- Fetch all session objects for the user ---
    stmt = select(ChatSession).where(ChatSession.user_id == user_id)
    result = await db.execute(stmt)
    sessions_to_delete = result.scalars().all()

    if sessions_to_delete:
        print(f"CRUD: Deleting {len(sessions_to_delete)} sessions for user {user_id} via ORM cascade...")
        for session in sessions_to_delete:
            await db.delete(session) # Delete each session object
        await db.commit() # Commit all deletions
        print(f"CRUD: Finished deleting sessions for user {user_id}.")
    else:
        print(f"CRUD: No sessions found to delete for user {user_id}.")