# file: backend/dependencies.py
from fastapi import Request, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from .services import crud
from .models import *
from .database import get_db_session


async def get_current_user_id_from_session(request: Request) -> int:
    """
    Retrieves the user ID from the session managed by SessionMiddleware.
    Raises 401 Unauthorized if user_id is not found in the session.
    """
    user_id = request.session.get("user_id")
    # print(f"DEBUG: Checking session for user_id: {user_id}") # Debug print
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"}, # Standard header
        )
    try:
        return int(user_id)
    except (ValueError, TypeError):
         request.session.clear() # Clear corrupted session
         raise HTTPException(
             status_code=status.HTTP_401_UNAUTHORIZED,
             detail="Invalid session data",
             headers={"WWW-Authenticate": "Bearer"},
         )


async def get_current_active_user(
    user_id: int = Depends(get_current_user_id_from_session), 
    db: AsyncSession = Depends(get_db_session)
) -> User:
    """
    Fetches the full User object from DB based on the authenticated user ID from session.
    """
    user = await crud.get_user_by_id(db, user_id=user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    # --- Checks here if users can be inactive ---
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user