# Naming decisions

The vocabulary this codebase uses, so two names never mean the same thing.
Terms come from the project plan's domain model and glossary. Add a row
whenever a review settles a term; never rename against this file.

## Vocabulary

| Use | Not | Why |
|---|---|---|
| medicine | drug, medication | The project plan and the `medicines` table use "medicine" |
| `exc` | `err`, `e`, `ex`, `error` | A caught or handled exception. It is Python's and Starlette's own name for one, and it leaves `error` free for error bodies and Pydantic's error dicts (R-002) |

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
