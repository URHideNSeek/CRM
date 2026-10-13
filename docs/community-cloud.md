# Streamlit Community Cloud

Deploy the private URHideNSeek/CRM repository, branch main, entry point
community/streamlit_app.py, using Python 3.12. This directory installs only Streamlit.

In Advanced settings > Secrets, enter a unique password (at least 16 characters):

```toml
APP_PASSWORD = "replace-with-your-own-long-unique-password"
```

Never commit the real password or contact exports to the repository.
The app fails closed if this secret is missing or too short. Authentication happens
before CRM records, imports, or downloads are accessible. Sign out clears all session data.

In app Settings > Sharing, select Only specific people can view this app and add
approved viewers. Keep the GitHub repository private. Community Cloud currently
supports one private app per workspace; verify the limit before deployment.

This is a session-only prototype: download a backup before signing out or closing
the session. Restore backups or upload the UR chat import in Backup & restore.
It does not automatically ingest chats or write to the shared company CRM.
Persistent PostgreSQL storage and chat synchronization require the full app/backend.
