# file: Frontend/main.py
import os
import traceback
from fastapi import FastAPI # Keep import for type hint in init_nicegui
from nicegui import ui, app, Client
from typing import Optional, List, Dict, Any
import datetime
from email_validator import validate_email, EmailNotValidError
import asyncio

# Use relative imports
from . import api_client
from . import sse_client

# --- Constants ---
ASSISTANT_PLACEHOLDER_ID_PREFIX = "assist_placeholder_"

# --- State Management Helpers ---
def create_chat_state() -> Dict:
    """Creates the initial structure for chat state."""
    print("DEBUG: Creating initial chat state")
    return {"current_session_id": None, "current_messages": [], "sessions_list": [], "is_generating": False, "current_title": "New Chat"}

def get_chat_state(client: Client) -> Dict:
    """Safely gets the chat state, initializing if needed."""
    if "chat" not in client.storage or not isinstance(client.storage.get("chat"), dict):
        print(f"DEBUG: Initializing chat state for client {client.id}")
        client.storage["chat"] = create_chat_state()
    # Ensure essential keys exist if state was partially formed
    state = client.storage["chat"]
    if "current_messages" not in state: state["current_messages"] = []
    if "sessions_list" not in state: state["sessions_list"] = []
    if "current_session_id" not in state: state["current_session_id"] = None
    if "current_title" not in state: state["current_title"] = "New Chat"
    if "is_generating" not in state: state["is_generating"] = False
    return state

def update_chat_state(client: Client, **kwargs):
    """Updates the chat state explicitly, ensuring reactivity."""
    # Ensure state exists before trying to update
    current_state = get_chat_state(client).copy()
    current_state.update(kwargs)
    client.storage["chat"] = current_state
    # print(f"DEBUG: Updated chat state for client {client.id}: {kwargs.keys()}")

# --- Standalone Async Helper Functions ---

async def scroll_chat_to_bottom(client: Client, messages_column_id: Optional[int]):
    """Scrolls the specified messages column to the bottom."""
    chat_state = get_chat_state(client)
    if not chat_state['current_messages'] or not messages_column_id: return
    await asyncio.sleep(0.15) # Delay for rendering
    # Use client.run_javascript since this runs potentially outside the page function context
    await client.run_javascript(f'''
        const el = getElement({messages_column_id});
        if (el) {{ el.scrollTop = el.scrollHeight; }}
        else {{ console.warn('Scroll target element not found:', {messages_column_id}); }}
    ''')

async def update_sessions_list(client: Client, sessions_container_refresh_func: callable):
    """Fetches sessions and refreshes the list UI."""
    try:
        sessions = await api_client.api_get_sessions()
        print(f"UI Helper: Fetched sessions: {len(sessions)}")
        update_chat_state(client, sessions_list=sessions)
        sessions_container_refresh_func() # Call the passed refresh method
    except Exception as e: print(f"Error updating sessions list: {e}"); ui.notify("Failed history load.", type='negative')

async def update_chat_display(client: Client, chat_messages_area_refresh_func: callable, messages_column_id: Optional[int]):
    """Refreshes chat messages and schedules scroll."""
    print("UI Helper: Triggering chat messages refresh.")
    chat_messages_area_refresh_func() # Call the passed refresh method
    asyncio.create_task(scroll_chat_to_bottom(client, messages_column_id))

async def select_chat_session(client: Client, session_id: Optional[str], chat_refresh_func: callable, messages_column_id: Optional[int]):
    """Selects a session, fetches messages, updates state and UI."""
    print(f"UI Helper: Selecting session: {session_id}")
    messages = []
    title = "New Chat"
    loaded_session_id = None
    if session_id:
        session_details = await api_client.api_get_session_details(session_id)
        if session_details and 'messages' in session_details:
            messages = [{'id': msg.get('id'), 'role': msg.get('role'), 'content': msg.get('content')}
                        for msg in session_details['messages']]
            title = session_details.get('title') or f"Chat {session_id[:8]}..."
            loaded_session_id = session_id
        else:
            ui.notify("Could not load session details.", type='negative')
    update_chat_state(client, current_session_id=loaded_session_id, current_messages=messages, current_title=title)
    await update_chat_display(client, chat_refresh_func, messages_column_id)

async def delete_chat_session(client: Client, session_id: str, sessions_refresh_func: callable, chat_refresh_func: callable, messages_column_id: Optional[int]):
    """Deletes a session, updates state and UI."""
    success = await api_client.api_delete_session(session_id)
    if success:
        ui.notify(f"Session deleted.", type='positive')
        chat_state = get_chat_state(client)
        if chat_state.get("current_session_id") == session_id:
            # Select "New Chat" state
            await select_chat_session(client, None, chat_refresh_func, messages_column_id)
        # Always refresh the session list
        await update_sessions_list(client, sessions_refresh_func)
    else:
        ui.notify("Error deleting session.", type='negative')

async def handle_send_message(client: Client, chat_input: ui.input, send_button: ui.button, chat_refresh_func: callable, sessions_refresh_func: callable, messages_column_id: Optional[int]):
    """Handles sending message, API calls, streaming, state, and UI updates."""
    chat_state = get_chat_state(client)
    user_input = chat_input.value
    if not user_input or chat_state.get("is_generating"): return
    chat_input.set_value(None)

    current_session_id = chat_state.get("current_session_id")
    print(f"UI Helper: Sending '{user_input}' for session: {current_session_id}")

    # 1. Prepare & Update UI Immediately
    temp_user_msg_id = f"user_{datetime.datetime.now().timestamp()}"
    user_message = {"role": "user", "content": user_input, "id": temp_user_msg_id}
    temp_assist_msg_id = f"{ASSISTANT_PLACEHOLDER_ID_PREFIX}{datetime.datetime.now().timestamp()}"
    assistant_placeholder = {"role": "assistant", "content": "", "id": temp_assist_msg_id}

    new_messages_list = chat_state["current_messages"] + [user_message, assistant_placeholder]
    update_chat_state(client, current_messages=new_messages_list.copy(), is_generating=True)
    send_button.props('loading').classes('animate-pulse')
    await update_chat_display(client, chat_refresh_func, messages_column_id)

    # 2. Call API
    init_response = await api_client.api_initiate_chat(current_session_id, user_input)

    # 3. Handle API Failure
    if not init_response or "stream_id" not in init_response:
        ui.notify("Error starting chat.", type='negative')
        final_messages = [m for m in get_chat_state(client)["current_messages"] if m.get('id') != temp_assist_msg_id]
        update_chat_state(client, current_messages=final_messages, is_generating=False)
        send_button.props(remove='loading').classes(remove='animate-pulse')
        await update_chat_display(client, chat_refresh_func, messages_column_id)
        print("UI Helper: API initiate chat failed.")
        return

    # --- API Call Success ---
    new_session_id = init_response["session_id"]
    actual_user_message_id = init_response["user_message_id"]
    stream_id = init_response["stream_id"]
    print(f"UI Helper: API initiate success. Session: {new_session_id}, Stream: {stream_id}")

    # Update user message ID in state
    current_msgs = get_chat_state(client)["current_messages"].copy()
    user_msg_updated = False
    for i, msg in enumerate(current_msgs):
        if msg.get('id') == temp_user_msg_id:
            current_msgs[i] = {**msg, 'id': actual_user_message_id}; user_msg_updated = True; break
    if user_msg_updated: update_chat_state(client, current_messages=current_msgs)

    # Update session list and current ID if it was a new chat
    if current_session_id is None:
        update_chat_state(client, current_session_id=new_session_id)
        # Fetch updated title if needed, then refresh list
        await update_sessions_list(client, sessions_refresh_func)

    # 4. Stream SSE response
    assistant_response_content = ""
    placeholder_index = -1
    try:
        print(f"UI Helper: Starting SSE stream for {stream_id}")
        cookies_to_pass = api_client._client.cookies
        async for token in sse_client.stream_chat_responses(stream_id, cookies=cookies_to_pass):
            if token.startswith("[ERROR]"):
                assistant_response_content = token; ui.notify(f"Streaming Error: {token}"); break
            assistant_response_content += token

            # Update placeholder content in state explicitly
            current_msgs = get_chat_state(client)["current_messages"].copy()
            if placeholder_index == -1:
                 try: placeholder_index = next(i for i, msg in enumerate(current_msgs) if msg.get('id') == temp_assist_msg_id)
                 except StopIteration: print("ERROR: Placeholder not found!"); break
            if placeholder_index != -1:
                 current_msgs[placeholder_index] = {**current_msgs[placeholder_index], 'content': assistant_response_content}
                 update_chat_state(client, current_messages=current_msgs)
                 chat_refresh_func() # Trigger refresh directly
                 await asyncio.sleep(0.02)

        print(f"UI Helper: Finished streaming. Length: {len(assistant_response_content)}")
    except Exception as e:
        print(f"UI Helper: SSE Error: {e}"); traceback.print_exc()
        assistant_response_content = f"[ERROR] Stream failed: {e}"; ui.notify(f"Error: {e}")
    finally:
        # 5. Finalize state and UI
        print("UI Helper: Finalizing message send.")
        current_chat_state = get_chat_state(client)
        current_msgs = current_chat_state["current_messages"]
        # Get actual assistant message ID? Backend saves it, but doesn't return it easily yet.
        # We could fetch the session details again, but for now, use a placeholder final ID.
        final_messages_list = [m for m in current_msgs if m.get('id') != temp_assist_msg_id]
        final_assistant_msg_id = f"assist_final_{datetime.datetime.now().timestamp()}"
        final_assistant_msg = {"role": "assistant", "content": assistant_response_content, "id": final_assistant_msg_id}
        final_messages_list.append(final_assistant_msg)
        update_chat_state(client, current_messages=final_messages_list, is_generating=False)
        send_button.props(remove='loading').classes(remove='animate-pulse')
        await update_chat_display(client, chat_refresh_func, messages_column_id)
        await update_sessions_list(client, sessions_refresh_func)

async def handle_logout():
     success = await api_client.api_logout()
     if success:
         app.storage.user.clear()
         # Client storage is per-tab, should clear on navigation/reload anyway
         ui.navigate.to('/login')
     else:
         ui.notify("Logout failed.", type='negative')

# --- NiceGUI Page Definitions ---

@ui.page('/')
async def route_root():
    # Check auth status via API and redirect accordingly
    if await api_client.api_get_current_user():
        print("UI Root: User authenticated, redirecting to /main")
        ui.navigate.to('/main')
    else:
        print("UI Root: User not authenticated, redirecting to /login")
        ui.navigate.to('/login')

@ui.page('/login')
async def login_page(client: Client):
    # Check if already logged in
    if await api_client.api_get_current_user():
        ui.navigate.to('/main')
        return # Stop rendering if already logged in

    # --- Build Login UI ---
    with ui.card().classes('absolute-center w-96'): # Added width
        ui.label("Login").classes('text-2xl self-center mb-6')
        email_input = ui.input("Email").props('type="email" outlined autocomplete="email"').classes('w-full')
        password_input = ui.input("Password").props('type="password" outlined autocomplete="current-password"').classes('w-full')
        error_label = ui.label().classes('text-red-500 mt-2 self-center h-6') # Added height for stability

        async def handle_login_click(): # Renamed inner function
            error_label.set_text("")
            email = email_input.value
            password = password_input.value
            if not email or not password: error_label.set_text("Please enter email and password."); return
            user_info = await api_client.api_login(email, password)
            if user_info and user_info.get("user_id"):
                if "chat" in client.storage: del client.storage["chat"] # Clear old state
                print(f"UI: User logged in: {user_info.get('email', 'Unknown')}")
                ui.navigate.to('/main')
            else: error_label.set_text("Invalid email or password.")

        ui.button("Login", on_click=handle_login_click).classes('w-full mt-6')
        ui.link("Don't have an account? Sign up", '/signup').classes('mt-4 self-center')

@ui.page('/signup')
async def signup_page(client: Client):
    if await api_client.api_get_current_user(): ui.navigate.to('/main'); return

    # --- Build Signup UI ---
    with ui.card().classes('absolute-center w-96'):
        ui.label("Sign Up").classes('text-2xl self-center mb-6')
        email_input = ui.input("Email").props('type="email" outlined autocomplete="email"').classes('w-full')
        password_input = ui.input("Password").props('type="password" outlined autocomplete="new-password"').classes('w-full')
        confirm_password_input = ui.input("Confirm Password").props('type="password" outlined autocomplete="new-password"').classes('w-full')
        error_label = ui.label().classes('text-red-500 mt-2 self-center h-6') # Added height

        async def handle_signup_click(): # Renamed inner function
            error_label.set_text("")
            email = email_input.value; password = password_input.value; confirm = confirm_password_input.value
            # ... (Validation logic remains the same) ...
            if not email or not password or not confirm: error_label.set_text("Please fill all fields."); return
            try: validate_email(email)
            except EmailNotValidError as e: error_label.set_text(f"Invalid email: {e}"); return
            if password != confirm: error_label.set_text("Passwords do not match."); return
            if len(password) < 8: error_label.set_text("Password too short (min 8 chars)."); return

            try:
                user_info = await api_client.api_signup(email, password)
                if user_info:
                     login_result = await api_client.api_login(email, password)
                     if login_result and login_result.get("user_id"):
                         if "chat" in client.storage: del client.storage["chat"] # Clear old state
                         print(f"UI: User signed up & logged in: {login_result['email']}")
                         ui.navigate.to('/main')
                     else: error_label.set_text("Signup ok, auto-login failed."); ui.navigate.to('/login')
            except ValueError as e: error_label.set_text(str(e))
            except Exception as e: print(f"UI Signup Error: {e}"); error_label.set_text("Error.")

        ui.button("Sign Up", on_click=handle_signup_click).classes('w-full mt-6')
        ui.link("Have an account? Login", '/login').classes('mt-4 self-center')

@ui.page('/main')
async def main_chat_page(client: Client):
    user = await api_client.api_get_current_user()
    if not user: ui.navigate.to('/login'); return
    print(f"Chat Page: Loading for user {user.get('email')}")

    # Initialize state for this client if needed
    chat_state = get_chat_state(client)

    # --- Define UI Structure ---
    # Header
    with ui.header(elevated=True).classes('justify-between items-center px-4'):
        ui.label().bind_text_from(client.storage['chat'], 'current_title').classes('text-lg font-semibold')
        ui.button("Logout", on_click=handle_logout, icon='logout').props('flat color=white')

    # Left Drawer (Sessions History)
    with ui.left_drawer(bordered=True).classes('bg-gray-100 w-64') as left_drawer: # Added width
        with ui.column().classes('w-full p-2'):
            ui.button("New Chat", icon="add_comment", on_click=lambda: select_chat_session(client, None, chat_messages_area.refresh, MESSAGES_COLUMN_ID)).classes('w-full mb-2')
            ui.label("History").classes('text-base font-medium mb-1 text-gray-600 px-2')
            ui.separator()
            # Define the refreshable container for sessions
            @ui.refreshable
            async def sessions_container():
                # Read state inside the refreshable
                current_state = get_chat_state(client)
                sessions = current_state.get("sessions_list", [])
                current_session_id = current_state.get("current_session_id")
                print(f"UI: Rendering sessions_container. Count: {len(sessions)}")
                if not sessions: ui.label("No history.").classes('p-2 text-xs text-gray-500')
                else:
                    with ui.column().classes('w-full gap-0'): # Use column for list items
                        for session_data in sessions:
                            try:
                                session_id = session_data.get('id')
                                is_selected = session_id == current_session_id
                                base_classes = 'w-full items-center cursor-pointer p-2 rounded text-sm'
                                selected_classes = ' bg-blue-100 text-blue-800 font-medium' if is_selected else ' hover:bg-gray-200'
                                with ui.row().classes(base_classes + selected_classes) \
                                    .on('click', lambda s_id=session_id: select_chat_session(client, s_id, chat_messages_area.refresh, MESSAGES_COLUMN_ID)):
                                    with ui.column().classes('flex-grow gap-0'):
                                        ts_str = session_data.get('last_updated_at'); time_str = "..."
                                        if isinstance(ts_str, str):
                                            try:
                                                if ts_str.endswith('Z'): ts_str = ts_str[:-1] + '+00:00'
                                                ts = datetime.datetime.fromisoformat(ts_str)
                                                time_str = ts.strftime("%b %d, %H:%M")
                                            except ValueError: time_str = ts_str
                                        title = session_data.get('title') or "New Chat"
                                        ui.label(title).classes('font-medium truncate leading-tight')
                                        ui.label(time_str).classes('text-xs text-gray-500 leading-tight')
                                    # Use .stop modifier for delete button click
                                    ui.button(icon='delete', on_click=lambda s_id=session_id: delete_chat_session(client, s_id, sessions_container.refresh, chat_messages_area.refresh, MESSAGES_COLUMN_ID), color='negative') \
                                        .props('flat round dense size=xs').classes('ml-1').on('click.stop') # Add .stop
                            except Exception as e: print(f"ERROR render session: {e}"); traceback.print_exc()

    # Main Chat Area
    with ui.column().classes('w-full h-screen'): # Removed relative for simpler layout
        # Static scroll container - ensure padding for header/input
        messages_column = ui.column().classes('w-full flex-grow overflow-y-auto px-4 pt-20 pb-24') # Adjusted padding
        MESSAGES_COLUMN_ID = messages_column.id
        with messages_column:
            # Refreshable chat messages area
            @ui.refreshable
            def chat_messages_area():
                chat_state = get_chat_state(client)
                messages_to_render = chat_state.get("current_messages", [])
                print(f"UI: Rendering chat_messages_area. Count: {len(messages_to_render)}")
                if not messages_to_render and not chat_state.get("current_session_id"):
                    with ui.row().classes('w-full justify-center mt-10'):
                         ui.spinner(size='lg')
                         ui.label("Select or start a chat...").classes('p-4 text-center text-gray-500')
                else:
                    for msg_data in messages_to_render:
                        try:
                            role = msg_data.get('role', 'unknown')
                            content = msg_data.get('content', '')
                            is_user = role == 'user'
                            name = role.capitalize()
                            is_loading = (role == 'assistant' and
                                          chat_state.get("is_generating", False) and
                                          str(msg_data.get('id', '')).startswith(ASSISTANT_PLACEHOLDER_ID_PREFIX))
                            with ui.chat_message(name=name, sent=is_user, text=content): # Set text directly
                                if is_loading:
                                     with ui.row().classes('items-center'):
                                         ui.spinner(size='sm').classes('mr-2')
                                         ui.label('Generating...')
                        except Exception as e: print(f"ERROR render message: {e}"); traceback.print_exc()

        # Input Area - Placed at bottom using column structure
        ui.separator()
        with ui.row().classes('w-full p-3 bg-white items-center'):
            chat_input = ui.input(placeholder="Type your message...").classes('flex-grow').props('outlined dense') \
                .on('keydown.enter', lambda: handle_send_message(client, chat_input, send_button, chat_messages_area.refresh, sessions_container.refresh, MESSAGES_COLUMN_ID))
            send_button = ui.button(icon='send').props('flat round dense') \
                .on('click', lambda: handle_send_message(client, chat_input, send_button, chat_messages_area.refresh, sessions_container.refresh, MESSAGES_COLUMN_ID))

    # --- Initial Data Load ---
    print("UI: Page load - running initial data fetch...")
    # Need to render refreshables before calling helpers that use their .refresh
    await sessions_container()
    chat_messages_area()
    # Now fetch data and update state, which will trigger refreshes
    await asyncio.gather(
        update_sessions_list(client, sessions_container.refresh),
        select_chat_session(client, chat_state.get("current_session_id"), chat_messages_area.refresh, MESSAGES_COLUMN_ID)
    )
    print("UI: Initial data fetch complete.")


# --- init_nicegui (remains the same) ---
def init_nicegui(fastapi_app: FastAPI):
     ui.run_with(
         fastapi_app,
         mount_path="/",
         storage_secret=os.getenv("SECRET_KEY"),
         title="AI Chat"
     )