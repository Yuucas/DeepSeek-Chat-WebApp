# file: frontend/api_client.py
import httpx
from typing import Optional, List, Dict, Any
import os
from dotenv import load_dotenv

# Load environment variables first
load_dotenv()
# Get base URL from environment or use a default for local dev
# Note: When running combined, this might be tricky. Usually you'd configure this.
# For now, assume it runs on the same host/port.
BACKEND_BASE_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
print(f"---- Using backend URL: ----- {BACKEND_BASE_URL}")

# Store cookies globally for the client instance (simplistic approach)
# In a real app, manage cookies per user session more carefully.
_client = httpx.AsyncClient(base_url=BACKEND_BASE_URL, timeout=180.0) # Longer timeout

async def api_login(email: str, password: str) -> Optional[Dict[str, Any]]:
    """Calls the backend login API."""
    try:
        response = await _client.post("api/login", json={"email": email, "password": password})
        response.raise_for_status() # Raise exception for 4xx/5xx errors
        # Login success sets a cookie automatically handled by httpx client instance
        return response.json() # Return user info or success message
    except httpx.HTTPStatusError as e:
        print(f"Login API error: {e.response.status_code} - {e.response.text}")
        return None # Indicate login failure
    except Exception as e:
        print(f"Login request error: {e}")
        return None

async def api_signup(email: str, password: str) -> Optional[Dict[str, Any]]:
    """Calls the backend signup API."""
    try:
        response = await _client.post("api/signup", json={"email": email, "password": password})
        response.raise_for_status()
        return response.json() # Return created user info
    except httpx.HTTPStatusError as e:
        print(f"Signup API error: {e.response.status_code} - {e.response.text}")
        # Extract detail message if possible
        detail = "Signup failed."
        try:
            detail = e.response.json().get("detail", detail)
        except Exception: pass
        raise ValueError(detail) # Raise specific error for UI
    except Exception as e:
        print(f"Signup request error: {e}")
        raise ValueError("An unexpected error occurred during signup.")
    

async def api_logout() -> bool:
    """Calls the backend logout API."""
    try:
        response = await _client.post("/api/logout") # Correct path
        response.raise_for_status()
        # Clear local cookies managed by the client instance
        _client.cookies.clear()
        return True
    except Exception as e:
        print(f"Logout API error: {e}")
        return False


async def api_get_current_user() -> Optional[Dict[str, Any]]:
    """Calls the backend /api/users/me endpoint."""
    try:
        response = await _client.get("api/users/me")
        if response.status_code == 401: # Handle unauthorized specifically
            return None
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
         print(f"Get current user API error: {e.response.status_code} - {e.response.text}")
         return None
    except Exception as e:
        print(f"Get current user request error: {e}")
        return None

async def api_get_sessions() -> List[Dict[str, Any]]:
    """Calls the backend to get user's sessions."""
    try:
        response = await _client.get("api/sessions")
        if response.status_code == 401: return [] # Not logged in
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Get sessions error: {e}")
        return []

async def api_get_session_details(session_id: str) -> Optional[Dict[str, Any]]:
     """Calls backend to get messages for a session."""
     try:
         response = await _client.get(f"api/sessions/{session_id}")
         if response.status_code == 401: return None
         if response.status_code == 404: return None
         response.raise_for_status()
         return response.json()
     except Exception as e:
         print(f"Get session details error for {session_id}: {e}")
         return None

async def api_delete_session(session_id: str) -> bool:
    """Calls backend to delete a session."""
    try:
        response = await _client.delete(f"api/sessions/{session_id}")
        if response.status_code == 401: return False
        response.raise_for_status() # Raises for 4xx/5xx excluding 401 handled above
        return response.status_code == 204 # Success is No Content
    except Exception as e:
        print(f"Delete session error for {session_id}: {e}")
        return False

async def api_initiate_chat(session_id: Optional[str], user_message: str) -> Optional[Dict[str, Any]]:
     """Calls backend to start chat generation."""
     try:
         payload = {"session_id": session_id, "user_message": user_message}

         response = await _client.post("/api/chat/initiate", json=payload)

         if response.status_code == 401: return None
         response.raise_for_status()
         return response.json() # Returns {session_id, user_message_id, stream_id}
     
     except Exception as e:
         print(f"Initiate chat error: {e}")
         return None

# Note: SSE connection handled separately in sse_client.py or directly in UI logic