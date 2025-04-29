from nicegui import Client
from typing import Dict


# --- Constants ---
ASSISTANT_PLACEHOLDER_ID_PREFIX = "assist_placeholder_"

# --- State Management Helpers ---
def create_chat_state() -> Dict:
    """Creates the initial structure for chat state."""
    print("DEBUG: Creating initial chat state")
    return {
        "current_session_id": None,
        "current_messages": [],
        "sessions_list": [],
        "is_generating": False,
        "current_title": "New Chat"
    }

def get_chat_state(client: Client) -> Dict:
    """Safely gets the chat state, initializing if needed."""
    if "chat" not in client.storage or not isinstance(client.storage.get("chat"), dict):
        print(f"DEBUG: Initializing chat state for client {client.id}")
        client.storage["chat"] = create_chat_state()
    # Ensure essential keys exist
    state = client.storage["chat"]
    state.setdefault("current_session_id", None)
    state.setdefault("current_messages", [])
    state.setdefault("sessions_list", [])
    state.setdefault("is_generating", False)
    state.setdefault("current_title", "New Chat" if not state.get("current_session_id") else "Chat")
    return state

def update_chat_state(client: Client, **kwargs):
    """Updates the chat state explicitly by reassigning the dict."""
    current_state = get_chat_state(client).copy()
    current_state.update(kwargs)
    client.storage["chat"] = current_state # Reassign the entire dict