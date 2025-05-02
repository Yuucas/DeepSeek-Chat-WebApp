from nicegui import ui, app, Client
from email_validator import validate_email, EmailNotValidError

# Use relative imports
from .. import api_client
from ..pageRoutes import pageRoutes


async def handle_signup(client: Client):

    if await api_client.api_get_current_user(): ui.navigate.to(pageRoutes.MAIN_PATH); return

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
                         ui.navigate.to(pageRoutes.MAIN_PATH)
                     else: error_label.set_text("Signup ok, auto-login failed."); ui.navigate.to(pageRoutes.LOGIN_PATH)
                     
            except ValueError as e: error_label.set_text(str(e))
            except Exception as e: print(f"UI Signup Error: {e}"); error_label.set_text("Error.")

        ui.button("Sign Up", on_click=handle_signup_click, color='#40040b').classes('w-full mt-4')
        ui.button("Login", on_click=lambda: ui.navigate.to(pageRoutes.LOGIN_PATH), color='#40040b').classes('w-full mt-2')