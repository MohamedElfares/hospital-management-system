"""Auth module: sign-in, refresh tokens, sign-out, and password changes.

Holds the ``refresh_tokens`` table and, as IAM-2 continues, the ``/auth``
endpoints that issue and rotate tokens. Users themselves live in the users
module; this module calls its service, never its repository.
"""
