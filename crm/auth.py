import os

import streamlit as st


def require_user():
    mode = os.getenv("AUTH_MODE", "oidc")
    if mode == "local":
        st.sidebar.caption("Local development • JJ")
        return "local:JJ"
    if mode != "oidc":
        st.error("Invalid authentication configuration.")
        st.stop()
    if not st.user.is_logged_in:
        st.title("Unseen Robotics CRM")
        st.write("Sign in to your company relationship workspace.")
        st.button("Sign in", on_click=st.login)
        st.stop()
    email = st.user.get("email", "").lower()
    allowed = {v.strip().lower() for v in os.getenv("ALLOWED_EMAILS", "").split(",") if v.strip()}
    if not email or email not in allowed or st.user.get("email_verified") is not True:
        st.error("This verified email is not approved for the CRM.")
        st.button("Sign out", on_click=st.logout)
        st.stop()
    st.sidebar.caption(email)
    st.sidebar.button("Sign out", on_click=st.logout)
    return email
