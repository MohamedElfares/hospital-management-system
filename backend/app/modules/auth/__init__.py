"""Auth module: sign-in, sessions, sign-out, and password changes.

It holds the ``refresh_tokens`` table and the ``/auth`` endpoints of
IAM-2: sign-in, refresh, sign-out, the signed-in user, and the password
change. Its service also turns each request's access token back into an
active user, for the dependencies in ``app/api/deps.py``, and holds the
gate that refuses a user who must still replace a temporary password.
Accounts live in the users module: this module uses its model and
schemas and calls its service, never its repository, so the account
rules stay in one place.
"""
