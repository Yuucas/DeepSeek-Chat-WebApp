# file: Frontend/main.py
import os
import html
import traceback
from fastapi import FastAPI
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
    return {
        "current_session_id": None,
        "current_messages": [],
        "sessions_list": [],
        "is_generating": False,
        "current_title": "New Chat" # Added title state
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
    # print(f"DEBUG: Updated chat state keys: {list(kwargs.keys())}") # Less verbose debug

# --- Standalone Async Helper Functions ---

async def scroll_chat_to_bottom(client: Client, messages_column_id: Optional[int]):
    """Scrolls the specified messages column to the bottom."""
    chat_state = get_chat_state(client)
    if not chat_state.get('current_messages') or not messages_column_id: return
    await asyncio.sleep(0.15) # Delay for rendering
    # Use client.run_javascript as this might be called from background task
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
    # Schedule scroll to run after current event handling cycle
    asyncio.create_task(scroll_chat_to_bottom(client, messages_column_id))

async def select_chat_session(client: Client, session_id: Optional[str], chat_refresh_func: callable, messages_column_id: Optional[int]):
    """Selects a session, fetches messages, updates state and UI."""
    print(f"UI Helper: Selecting session: {session_id}")
    messages = []
    title = "New Chat"
    loaded_session_id = None # Track the ID actually loaded
    if session_id:
        session_details = await api_client.api_get_session_details(session_id)
        if session_details and 'messages' in session_details:
            messages = [{'id': msg.get('id'), 'role': msg.get('role'), 'content': msg.get('content')}
                        for msg in session_details['messages']]
            title = session_details.get('title') or f"Chat {session_id[:8]}..."
            loaded_session_id = session_id # Confirm this session was loaded
        else:
            ui.notify("Could not load session details.", type='negative')
            # Keep loaded_session_id as None if load failed
    # Update state using helper
    update_chat_state(client, current_session_id=loaded_session_id, current_messages=messages, current_title=title)
    await update_chat_display(client, chat_refresh_func, messages_column_id)

async def delete_chat_session(client: Client, session_id: str, sessions_refresh_func: callable, chat_refresh_func: callable, messages_column_id: Optional[int]):
    """Deletes a session, updates state and UI."""
    success = await api_client.api_delete_session(session_id)
    if success:
        ui.notify(f"Session deleted.", type='positive')
        chat_state = get_chat_state(client) # Get current state
        # Check if the deleted session was the active one
        if chat_state.get("current_session_id") == session_id:
            # Select "New Chat" state by calling select_chat_session with None
            await select_chat_session(client, None, chat_refresh_func, messages_column_id)
        # Always refresh the session list
        await update_sessions_list(client, sessions_refresh_func)
    else:
        ui.notify("Error deleting session.", type='negative')

async def handle_send_message(client: Client, chat_input: ui.input, send_button: ui.button, chat_refresh_func: callable, sessions_refresh_func: callable, messages_column_id: Optional[int]):
    """Handles sending message, API calls, streaming, state, and UI updates."""
    chat_state = get_chat_state(client) # Get current state
    user_input = chat_input.value
    if not user_input or chat_state.get("is_generating"): return
    chat_input.set_value(None) # Clear input

    current_session_id = chat_state.get("current_session_id")
    print(f"UI Helper: Sending '{user_input}' for session: {current_session_id}")

    # 1. Prepare message objects & Update UI Immediately
    temp_user_msg_id = f"user_{datetime.datetime.now().timestamp()}"
    user_message = {"role": "user", "content": user_input, "id": temp_user_msg_id}
    temp_assist_msg_id = f"{ASSISTANT_PLACEHOLDER_ID_PREFIX}{datetime.datetime.now().timestamp()}"
    assistant_placeholder = {"role": "assistant", "content": "", "id": temp_assist_msg_id}

    # --- Explicit State Update ---
    new_messages_list = chat_state["current_messages"] + [user_message, assistant_placeholder]
    update_chat_state(client, current_messages=new_messages_list.copy(), is_generating=True) # Use copy
    send_button.props('loading').classes('animate-pulse')
    await update_chat_display(client, chat_refresh_func, messages_column_id) # Refresh UI now

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
        update_chat_state(client, current_session_id=new_session_id, current_title=user_input[:50])
        await update_sessions_list(client, sessions_refresh_func)

    # 4. Stream SSE response
    assistant_response_content = ""
    placeholder_index = -1
    try:
        print(f"UI Helper: Starting SSE stream for {stream_id}")
        cookies_to_pass = api_client._client.cookies # Get current cookies from shared client
        async for token in sse_client.stream_chat_responses(stream_id, cookies=cookies_to_pass):
            if token.startswith("[ERROR]"):
                assistant_response_content = token; ui.notify(f"Streaming Error: {token}"); break
            assistant_response_content += token

            # --- Explicitly update placeholder content in state ---
            current_msgs = get_chat_state(client)["current_messages"].copy()
            if placeholder_index == -1:
                 try: placeholder_index = next(i for i, msg in enumerate(current_msgs) if msg.get('id') == temp_assist_msg_id)
                 except StopIteration: print("ERROR: Placeholder not found!"); break
            if placeholder_index != -1:
                # Create a *new* dict for the updated message
                updated_placeholder = {**current_msgs[placeholder_index], 'content': assistant_response_content}
                # Create a *new* list with the updated message
                new_messages_list = current_msgs[:placeholder_index] + [updated_placeholder] + current_msgs[placeholder_index+1:]
                # Update the state with the new list
                update_chat_state(client, current_messages=new_messages_list)
                # Trigger refresh
                chat_refresh_func()
                await asyncio.sleep(0.02) # Yield control

        print(f"UI Helper: Finished streaming. Length: {len(assistant_response_content)}")
    except Exception as e:
        print(f"UI Helper: SSE Error: {e}"); traceback.print_exc()
        assistant_response_content = f"[ERROR] Stream failed: {e}"; ui.notify(f"Error: {e}")
    finally:
        # 5. Finalize state and UI
        print("UI Helper: Finalizing message send.")
        current_chat_state = get_chat_state(client) # Get latest state
        current_msgs = current_chat_state["current_messages"]
        # Remove placeholder and add final message
        final_messages_list = [m for m in current_msgs if m.get('id') != temp_assist_msg_id]
        final_assistant_msg_id = f"assist_final_{datetime.datetime.now().timestamp()}"
        final_assistant_msg = {"role": "assistant", "content": assistant_response_content, "id": final_assistant_msg_id}
        final_messages_list.append(final_assistant_msg)
        # Update state, setting generating to false
        update_chat_state(client, current_messages=final_messages_list, is_generating=False)
        send_button.props(remove='loading').classes(remove='animate-pulse')
        # Final refresh and scroll
        await update_chat_display(client, chat_refresh_func, messages_column_id)
        # Update sessions list timestamp
        await update_sessions_list(client, sessions_refresh_func)

async def handle_logout_click(): # Renamed inner function
     success = await api_client.api_logout()
     if success:
         app.storage.user.clear()
         # Client storage is per-tab/connection, should clear on navigation anyway
         ui.navigate.to('/login')
     else:
         ui.notify("Logout failed.", type='negative')

# --- NiceGUI Page Definitions ---

@ui.page('/')
async def route_root():
    if await api_client.api_get_current_user(): ui.navigate.to('/main')
    else: ui.navigate.to('/login')

@ui.page('/login')
async def login_page(client: Client):
    if await api_client.api_get_current_user(): ui.navigate.to('/main'); return
    with ui.card().classes('absolute-center w-96'):
        ui.label("Login").classes('text-2xl self-center mb-6')
        email_input = ui.input("Email").props('type="email" outlined autocomplete="email"').classes('w-full')
        password_input = ui.input("Password").props('type="password" outlined autocomplete="current-password"').classes('w-full')
        error_label = ui.label().classes('text-red-500 mt-2 self-center h-6')
        async def handle_login_click():
            error_label.set_text("")
            email, password = email_input.value, password_input.value
            if not email or not password: error_label.set_text("Enter email/password."); return
            user_info = await api_client.api_login(email, password)
            if user_info and user_info.get("user_id"):
                if "chat" in client.storage: del client.storage["chat"]
                print(f"UI: Logged in: {user_info.get('email')}")
                ui.navigate.to('/main')
            else: error_label.set_text("Invalid email or password.")
        ui.button("Login", on_click=handle_login_click).classes('w-full mt-6')
        ui.link("Sign up", '/signup').classes('mt-4 self-center')

@ui.page('/signup')
async def signup_page(client: Client):
    if await api_client.api_get_current_user(): ui.navigate.to('/main'); return
    with ui.card().classes('absolute-center w-96'):
        ui.label("Sign Up").classes('text-2xl self-center mb-6')
        email_input = ui.input("Email").props('type="email" outlined autocomplete="email"').classes('w-full')
        password_input = ui.input("Password").props('type="password" outlined autocomplete="new-password"').classes('w-full')
        confirm_input = ui.input("Confirm Password").props('type="password" outlined autocomplete="new-password"').classes('w-full')
        error_label = ui.label().classes('text-red-500 mt-2 self-center h-6')
        async def handle_signup_click():
            error_label.set_text("")
            email, password, confirm = email_input.value, password_input.value, confirm_input.value
            if not email or not password or not confirm: error_label.set_text("Fill all fields."); return
            try: validate_email(email)
            except EmailNotValidError as e: error_label.set_text(f"Invalid email: {e}"); return
            if password != confirm: error_label.set_text("Passwords don't match."); return
            if len(password) < 8: error_label.set_text("Password too short."); return
            try:
                user_info = await api_client.api_signup(email, password)
                if user_info:
                     login_result = await api_client.api_login(email, password)
                     if login_result and login_result.get("user_id"):
                         if "chat" in client.storage: del client.storage["chat"]
                         print(f"UI: Signed up & logged in: {login_result['email']}")
                         ui.navigate.to('/main')
                     else: error_label.set_text("Signup ok, auto-login failed."); ui.navigate.to('/login')
            except ValueError as e: error_label.set_text(str(e))
            except Exception as e: print(f"UI Signup Error: {e}"); error_label.set_text("Error.")
        ui.button("Sign Up", on_click=handle_signup_click).classes('w-full mt-6')
        ui.link("Login", '/login').classes('mt-4 self-center')

@ui.page('/main')
async def main_chat_page(client: Client):
    user = await api_client.api_get_current_user()
    if not user: ui.navigate.to('/login'); return
    print(f"Chat Page: Loading for user {user.get('email')}")
    chat_state = get_chat_state(client) # Get/Init state

    # --- Define Refreshable Containers FIRST ---
    @ui.refreshable
    async def sessions_container():
        # Read state inside the refreshable
        current_state = get_chat_state(client) # Get fresh state on each refresh
        sessions = current_state.get("sessions_list", [])
        current_session_id = current_state.get("current_session_id")
        print(f"UI: Rendering sessions_container. Count: {len(sessions)}")
        if not sessions: ui.label("No history.").classes('p-2 text-xs text-gray-500')
        else:
            with ui.column().classes('w-full gap-0'):
                for session_data in sessions:
                    try:
                        session_id = session_data.get('id')
                        is_selected = session_id == current_session_id
                        base_classes = 'w-full items-center cursor-pointer p-2 rounded text-sm'
                        selected_classes = ' bg-blue-100 text-blue-800' if is_selected else ' hover:bg-gray-200'
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
                            ui.button(icon='delete', on_click=lambda s_id=session_id: delete_chat_session(client, s_id, sessions_container.refresh, chat_messages_area.refresh, MESSAGES_COLUMN_ID), color='negative') \
                                .props('flat round dense size=xs').classes('ml-1').on('click.stop')
                    except Exception as e: print(f"ERROR render session: {e}"); traceback.print_exc()

    @ui.refreshable
    def chat_messages_area():
        chat_state = get_chat_state(client) # Get fresh state on each refresh
        messages_to_render = chat_state.get("current_messages", [])
        print(f"UI: Rendering chat_messages_area. Count: {len(messages_to_render)}")
        print(f"Message to Render: {messages_to_render}") # Debug

        if not messages_to_render and not chat_state.get("current_session_id"):
            with ui.column().classes('w-full h-full justify-center items-center text-gray-400'):
                 ui.icon('question_answer', size='xl')
                 ui.label("Select a chat or start a new one.")
        elif not messages_to_render and chat_state.get("current_session_id"):
             with ui.column().classes('w-full h-full justify-center items-center text-gray-400'):
                 ui.icon('chat', size='xl')
                 ui.label("Send a message to start the chat!").classes('mt-2')

        with ui.column().classes('w-full gap-3 px-4 pt-4 pb-2'): # Add padding/gap
                for msg_data in messages_to_render:
                    try:
                        role = msg_data.get('role', 'unknown')
                        raw_content = msg_data.get('content', '') # Get raw content
                        is_user = role == 'user'
                        name = role.capitalize()
                        is_loading = (role == 'assistant' and
                                    chat_state.get("is_generating", False) and
                                    str(msg_data.get('id', '')).startswith(ASSISTANT_PLACEHOLDER_ID_PREFIX))

                        with ui.chat_message(name=name, sent=is_user):
                            # --- Prepare content for HTML display ---
                            # Escape HTML special characters for security!
                            escaped_content = html.escape(raw_content)

                            # Define the style for the <pre> tag
                            # white-space: pre-wrap; -> preserves whitespace, wraps lines
                            # word-wrap: break-word; -> breaks long words if needed
                            # font-family: monospace; -> terminal-like font
                            # margin: 0; -> remove default pre margins
                            pre_style = "white-space: pre-wrap; word-wrap: break-word; font-family: monospace; margin: 0;"

                            # Construct the HTML string
                            html_content = f'<pre style="{pre_style}">{escaped_content}</pre>'
                            # --- End preparation ---
                            if is_loading:
                                with ui.row().classes('items-center'):
                                    ui.spinner(size='sm').classes('mr-2')
                                    # Display streaming raw content using ui.html
                                    if raw_content:
                                        ui.html(html_content) # Use the prepared HTML
                            else:
                                # --- Display RAW content using ui.html with <pre> ---
                                ui.html(html_content) # Use the prepared HTML
                                # --- End Raw Display ---
                    except Exception as e: print(f"ERROR render message: {e}"); traceback.print_exc()

    # --- Build Page Layout ---
    # Header
    with ui.header(elevated=True).classes('items-center justify-between'):
        with ui.row().classes('items-center'):
             # Button to toggle left drawer
             ui.button(icon='menu', on_click=lambda: left_drawer.toggle()).props('flat round dense color=white')
             # Bind title from state
             ui.label().bind_text_from(client.storage['chat'], 'current_title',
                                     backward=lambda t=get_chat_state(client).get("current_title", "New Chat"): t or "New Chat") \
                     .classes('text-lg font-semibold ml-2')
        ui.button("Logout", on_click=lambda: handle_logout_click(client), icon='logout').props('flat color=white') # Pass client

    # Left Drawer
    with ui.left_drawer(value=True, bordered=True).classes('bg-gray-100 w-64') as left_drawer:
        with ui.column().classes('w-full p-2'):
            ui.button("New Chat", icon="add_comment",
                      on_click=lambda: select_chat_session(client, None, chat_messages_area.refresh, MESSAGES_COLUMN_ID)).classes('w-full mb-2')
            ui.label("History").classes('text-base font-medium mb-1 text-gray-600 px-2')
            ui.separator().classes('mb-2')
            # Call the refreshable function to render the initial list
            await sessions_container() # Render sessions list

    with ui.column().classes('w-full h-screen relative'): # Main area takes full height
        # Static scroll container fills remaining space, added padding
        messages_column = ui.column().classes('w-full flex-grow overflow-y-auto pb-20') # Use flex-grow
        MESSAGES_COLUMN_ID = messages_column.id
        with messages_column:
            # Call the refreshable function to render initial messages
            chat_messages_area()

        # Input Area at the bottom
        ui.separator()
        with ui.row().classes('w-full p-2 bg-gray-50 items-center border-t'):
            chat_input = ui.textarea(placeholder="Type your message...") \
                .classes('flex-grow') \
                .props('outlined dense rows=1 max-rows=5 autogrow clearable') \
                .on('keydown.enter', lambda e: handle_send_message(client, chat_input, send_button, chat_messages_area.refresh, sessions_container.refresh, MESSAGES_COLUMN_ID) if not e.args['shiftKey'] else None, throttle=0.1) # Send on Enter unless Shift+Enter
            send_button = ui.button(icon='send').props('flat round dense') \
                .on('click', lambda: handle_send_message(client, chat_input, send_button, chat_messages_area.refresh, sessions_container.refresh, MESSAGES_COLUMN_ID))

    # --- Initial Data Load ---
    print("UI: Page load - running initial data fetch...")
    await asyncio.gather(
        update_sessions_list(client, sessions_container.refresh),
        # Load initial chat state (select session will handle messages)
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