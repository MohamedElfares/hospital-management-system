# Naming decisions

The vocabulary this codebase uses, so two names never mean the same thing.
Terms come from the project plan's domain model and glossary. Add a row
whenever a review settles a term; never rename against this file.

## Vocabulary

| Use | Not | Why |
|---|---|---|
| medicine | drug, medication | The project plan and the `medicines` table use "medicine" |
| `exc` | `err`, `e`, `ex`, `error` | A caught or handled exception. It is Python's and Starlette's own name for one, and it leaves `error` free for error bodies and Pydantic's error dicts (R-002) |
| `login` in code names: `login`, `last_login_at`, `verify_login_password` | `sign_in`, `signin`, `log_in` | The route is `/auth/login` and the use case is `login`, so names follow them. Docstrings, comments, and messages keep the plan's prose words "sign in" and "sign-in" (run 1, stage 3) |
| `hasher` for what computes a hash, such as `_password_hasher` | `hash` for the hasher | A `*_hash` name holds a stored value, like `users.password_hash` and `refresh_tokens.token_hash`. The hasher used to be `_password_hash`, so `_password_hash.verify(password, password_hash)` read as two hashes (run 1, stage 3) |
| `create_<thing>` for a repository function that stores a new row, such as `create_user` | `add` | The repository shape rule lists `create_`, and the name says what is stored. The function only adds the object to the session, and the `INSERT` runs at the next flush, as its docstring says. A service function can share the name, such as the users service's `create_user`, which names the use case; callers write `repository.create_user`, so the two never mix (run 1, stage 5) |
| `data` for a use case's one validated input schema, such as `create_user(session, data: UserCreate)` and `change_password(session, user, data: PasswordChange)`. A changed copy takes a prefix, such as `admin_data` | `user_create`, `user_in`, `payload` | The annotation already names the schema, and each use case takes only one, so the shape rule's "no `data` when a specific word exists" doesn't apply to it. Your choice of my recommendation (run 1, stage 6) |
| `get_<thing>_by_hash` for a lookup by a `*_hash` column, such as `get_refresh_token_by_hash` for `refresh_tokens.token_hash` | `get_by_hash`, `get_refresh_token_by_token_hash` | The shape rule's `get_<thing>_by_<field>`. The thing already says "token", so repeating it in the field adds nothing; the parameter keeps the column's full name, `token_hash` (run 1, stage 7) |
| `revoke_all_<things>_for_<owner>` for a repository function that revokes many rows in one statement, such as `revoke_all_refresh_tokens_for_user` | `revoke_all_for_user`, `update_<things>` | "Revoke" is the plan's word for ending a token (§8.1), and says more than the shape rule's generic `update_`. The name says what is revoked, like `create_refresh_token` and `get_refresh_token_by_hash`, and "all" keeps the security property in the name: every session of that user ends. Your choice of my recommendation (run 1, stage 7) |

## Shape rules

These apply everywhere and are enforced by review, not by a linter.

- Booleans start with `is_`, `has_`, or `can_`.
- Collections are plural; single items singular.
- Repository methods: `get_<thing>_by_<field>` returns one or `None`, `list_<things>` returns many, plus `create_`, `update_`, `delete_`, `exists_`.
- Service methods name the use case: `book_appointment`, not `process`.
- No type names in variable names, and no `data`, `info`, `tmp`, or `result` when a specific word exists.
- Abbreviations only when the plan's glossary defines them (MRN, FEFO).
- A name that mirrors a library's own key keeps the library's spelling, such as `loc` for Pydantic's `error["loc"]` (R-002).
- Tests: `test_<action>_<condition>_<expected>`.
