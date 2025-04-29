from nicegui import ui, app, Client
from .. import api_client
from ..pageRoutes import pageRoutes


async def handle_login(client: Client):

    if await api_client.api_get_current_user(): ui.navigate.to(pageRoutes.MAIN_PATH); return

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