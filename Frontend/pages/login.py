from nicegui import ui, app, Client
from .. import api_client
from ..pageRoutes import pageRoutes





async def handle_login(client: Client):

    if await api_client.api_get_current_user(): ui.navigate.to(pageRoutes.MAIN_PATH); return


    # --- State variable to track password visibility ---
    password_state = {'visible': False}


    with ui.card().classes('absolute-center md:w-2/4 lg:w-1/3 mx-auto text-white'):

        ui.label("Login").classes('text-3xl self-center mb-7')

        email_input = ui.input("Email").props('type="email" outlined autocomplete="email"').classes('w-full')

        password_input = ui.input("Password") \
            .props('type="password" outlined autocomplete="current-password"') \
            .classes('w-full')

        error_label = ui.label().classes('text-red-500 mt-2 self-center h-6')

        # --- Define the toggle function ---
        def toggle_password_visibility():
            password_state['visible'] = not password_state['visible'] # Toggle the state
            new_type = 'text' if password_state['visible'] else 'password'
            new_icon = 'visibility' if password_state['visible'] else 'visibility_off'
            # Update input props
            password_input.props(f'type={new_type}')
            # Update button props - make sure toggle_button is defined before calling this
            if toggle_button: # Check if button exists (it will after creation)
                toggle_button.props(f'icon={new_icon}')

        # --- Add the toggle button to the input's append slot ---
        with password_input.add_slot('append'):
            # Define toggle_button here so the toggle_password_visibility function can access it
            toggle_button = ui.button(icon='visibility_off',
                                      on_click=toggle_password_visibility) \
                              .props('flat round dense') \
                              .tooltip('Show/hide password')

        async def handle_login_click():
            error_label.set_text("")
            email, password = email_input.value, password_input.value
            if not email or not password: error_label.set_text("Enter email/password."); return
            user_info = await api_client.api_login(email, password)
            if user_info and user_info.get("user_id"):
                if "chat" in client.storage: del client.storage["chat"]
                print(f"UI: Logged in: {user_info.get('email')}")
                ui.navigate.to(pageRoutes.MAIN_PATH)
            else: error_label.set_text("Invalid email or password.")

        ui.button("Login", on_click=handle_login_click, color='#40040b').classes('w-full mt-4')
        
        ui.button("Sign up", on_click=lambda: ui.navigate.to(pageRoutes.SIGNUP_PATH), color='#40040b').classes('w-full mt-2')