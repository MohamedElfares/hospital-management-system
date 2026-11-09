"""Users module: user accounts, and later staff profiles and administration.

Today it holds the ``users`` table and the account rules that the
``create-admin`` command and the ``auth`` module rely on: creating an
account, the password length rule, and looking an account up by email or
id. The staff administration endpoints (IAM-5) will add a router, and
staff profiles arrive in Milestone 1.3. Other modules call this module's
service, never its repository, so the account rules stay in one place.
"""
