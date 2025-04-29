# file: Backend/routes.py
import asyncio
import uuid
import traceback # Import traceback
from fastapi import APIRouter, HTTPException, Depends, status, Request
from fastapi.responses import StreamingResponse
from typing import List, Dict, Optional, AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession

# Use relative imports
from .services import crud, auth
from .database import get_db_session, async_session_maker # Import session maker
from .dependencies import get_current_active_user, get_current_user_id_from_session
from .models import User, UserCreate, UserLogin, UserPublic, SessionInfo, SessionDetail, InitiateChatRequestApi, InitiateChatResponseApi
from .algorithm import llm

router = APIRouter(prefix="/api", tags=["ChatApp"]) # Changed tag

# --- Auth Routes ---
@router.post("/signup", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def api_signup(user_data: UserCreate, db: AsyncSession = Depends(get_db_session)):
    existing_user = await crud.get_user_by_email(db, email=user_data.email)
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered.")
    user = await crud.create_user(db, email=user_data.email, password=user_data.password)
    return user

@router.post("/login")
async def api_login(request: Request, form_data: UserLogin, db: AsyncSession = Depends(get_db_session)):
    user = await crud.get_user_by_email(db, email=form_data.email)
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    request.session["user_id"] = user.id
    request.session["email"] = user.email
    print(f"API: Session set for user_id: {request.session['user_id']}")
    return {"message": "Login successful", "user_id": user.id, "email": user.email}

@router.post("/logout")
async def api_logout(request: Request):
    request.session.clear()
    print("API: Session cleared.")
    return {"message": "Logout successful"}

# --- User Route ---
@router.get("/users/me", response_model=UserPublic)
async def api_read_users_me(current_user: User = Depends(get_current_active_user)):
    return current_user

# --- Session Routes ---
@router.get("/sessions", response_model=List[SessionInfo])
async def api_get_sessions(user_id: int = Depends(get_current_user_id_from_session), db: AsyncSession = Depends(get_db_session)):
    sessions = await crud.get_user_sessions(db, user_id=user_id)
    return sessions

@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def api_get_session_details(session_id: str, user_id: int = Depends(get_current_user_id_from_session), db: AsyncSession = Depends(get_db_session)):
    session = await crud.get_session_by_id(db, session_id=session_id, user_id=user_id)
    if not session: raise HTTPException(status_code=404, detail="Session not found")
    return session

@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def api_delete_session(session_id: str, user_id: int = Depends(get_current_user_id_from_session), db: AsyncSession = Depends(get_db_session)):
    deleted = await crud.delete_chat_session(db, session_id=session_id, user_id=user_id)
    if not deleted: raise HTTPException(status_code=404, detail="Session not found")
    return None

# --- Chat Routes ---
stream_contexts: Dict[str, Dict] = {} # Store context info

@router.post("/chat/initiate", response_model=InitiateChatResponseApi)
async def api_initiate_chat(
    request_data: InitiateChatRequestApi,
    user_id: int = Depends(get_current_user_id_from_session),
    db: AsyncSession = Depends(get_db_session)
):
    if llm.model is None: raise HTTPException(status_code=503, detail="LLM not loaded")
    session_id = request_data.session_id
    user_message_content = request_data.user_message

    # Use transaction block for session creation AND message adding
    async with db.begin():
        if session_id:
            session = await crud.get_session_by_id(db, session_id=session_id, user_id=user_id)
            if not session: raise HTTPException(status_code=404, detail="Session not found")
        else:
            session = await crud.create_chat_session(db, user_id=user_id, title=user_message_content[:50])
            session_id = session.id
            print(f"API: Created new session {session_id} for user {user_id}")

        user_message = await crud.add_chat_message(
            db, session_id=session_id, role="user", content=user_message_content
        )
        # No explicit commit needed here, db.begin() handles it on successful block exit

    # Fetch history *after* transaction is committed
    updated_session = await crud.get_session_by_id(db, session_id=session_id, user_id=user_id)
    # Ensure messages are loaded (selectinload should handle this, but double-check if issues persist)
    if not updated_session or not hasattr(updated_session, 'messages'):
         raise HTTPException(status_code=500, detail="Failed to load session messages after update")

    history_for_llm = [{"role": msg.role, "content": msg.content} for msg in updated_session.messages]
    print(f"History for LLM ({len(history_for_llm)} messages): {history_for_llm}") # Log history

    stream_id = str(uuid.uuid4())
    stream_contexts[stream_id] = {'history': history_for_llm, 'session_id': session_id, 'user_id': user_id}
    print(f"API: Initiated stream {stream_id} for session {session_id}")

    return InitiateChatResponseApi(session_id=session_id, user_message_id=user_message.id, stream_id=stream_id)

@router.get("/chat/stream/{stream_id}")
async def api_stream_chat(stream_id: str):
    """Handles the SSE connection, filters <think> tags, and streams the final response."""
    print(f"API: SSE connection requested for stream ID: {stream_id}")

    # LLM object check now implicitly checks if lc_llm is loaded via llm.py
    if llm.lc_llm is None: # Check the LangChain LLM object
         raise HTTPException(status_code=503, detail="LLM not loaded yet")

    context = stream_contexts.pop(stream_id, None)
    if not context:
         print(f"API: Stream ID {stream_id} not found or already processed.")
         raise HTTPException(status_code=404, detail="Stream session not found or expired")

    history = context['history']
    session_id = context['session_id']
    user_id = context['user_id']

    async def event_generator():
        """Generator yields tokens AFTER the last </think> tag and saves that part."""
        full_response = ""
        llm_error_occurred = False


        try:
            token_count = 0
            print(f"API: Starting LangChain LLM stream for {stream_id}")
            async for token in llm.generate_lc_response_stream(history):
                token_count += 1
                # print(f"API: Received token from LLM stream: '{token}'") # Optional debug

                if "[ERROR]" in token:
                    print(f"API: LLM Error received via LangChain stream {stream_id}: {token}")
                    full_response = token # Store error message
                    llm_error_occurred = True
                    yield f"data: {token}\n\n" # Send error to client
                    break

                # --- Yield token directly (NO filtering) ---
                full_response += token
                sse_data = f"data: {token}\n\n"
                # print(f"API: Yielding SSE data: {sse_data.strip()}") # Optional debug
                yield sse_data
                # --- End direct yield ---

                await asyncio.sleep(0.01)

            print(f"API: LangChain Streaming finished for {stream_id}. Tokens received: {token_count}.")

        except Exception as e:
            llm_error_occurred = True
            full_response = f"[ERROR] Streaming failed unexpectedly in generator: {e}"
            print(f"API: Error during event_generator for {stream_id}: {e}")
            try: yield f"data: {full_response}\n\n"
            except Exception: pass
        finally:
            # --- Save the FULL raw response (or error) ---
            final_content_to_save = full_response.strip() # Use the raw response

            if not llm_error_occurred and final_content_to_save:
                print(f"API: Attempting to save FULL response for session {session_id}. Length: {len(final_content_to_save)}")
                try:
                    async with async_session_maker() as db_session:
                        async with db_session.begin():
                            await crud.add_chat_message(db_session, session_id, "assistant", final_content_to_save)
                        print(f"API: Successfully saved FULL assistant message for session {session_id}")
                except Exception as db_err:
                    print(f"API: CRITICAL - Failed to save FULL assistant message for session {session_id}: {db_err}")
                    # try: yield f"data: [ERROR] Failed to save response to DB.\n\n"
                    # except Exception: pass
            elif not final_content_to_save and not llm_error_occurred:
                 print(f"API: No response generated for stream {stream_id}, not saving.")
            else: # Error occurred
                print(f"API: Skipping DB save due to error or empty response for stream {stream_id}.")

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# --- Health Check ---
@router.get("/health")
async def health_check():
    return {"status": "ok", "model_loaded": llm.model is not None}