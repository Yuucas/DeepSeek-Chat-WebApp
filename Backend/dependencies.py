# file: backend/dependencies.py
from fastapi import Request, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from .services import crud
from .models import *
from .database import get_db_session

# Simple dependency based on NiceGUI's session storage for now.
# For more robust API auth, implement JWT or FastAPI session middleware.
async def get_current_user_id_from_session(request: Request) -> int: # Renamed for clarity
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
            headers={"WWW-Authenticate": "Bearer"}, # Standard header, though not strictly bearer here
        )
    try:
        return int(user_id)
    except (ValueError, TypeError):
         # Should not happen if session is set correctly, but good practice
         request.session.clear() # Clear corrupted session
         raise HTTPException(
             status_code=status.HTTP_401_UNAUTHORIZED,
             detail="Invalid session data",
             headers={"WWW-Authenticate": "Bearer"},
         )


async def get_current_active_user(
    user_id: int = Depends(get_current_user_id_from_session), # Use the session-based dependency
    db: AsyncSession = Depends(get_db_session)
) -> User:
    """
    Fetches the full User object from DB based on the authenticated user ID from session.
    """
    user = await crud.get_user_by_id(db, user_id=user_id)
    if user is None:
        # User ID was in session but not in DB (e.g., deleted user) - clear session
        # request.session.clear() # Cannot access request here directly, handle in endpoint if needed
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    # Add checks here if users can be inactive
    # if not user.is_active:
    #     raise HTTPException(status_code=400, detail="Inactive user")
    return user