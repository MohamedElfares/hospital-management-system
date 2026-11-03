# Naming decisions

The vocabulary this codebase uses, so two names never mean the same thing.
Terms come from the project plan's domain model and glossary. Add a row
whenever a review settles a term; never rename against this file.

## Vocabulary

| Use | Not | Why |
|---|---|---|
| medicine | drug, medication | The project plan and the `medicines` table use "medicine" |

## Shape rules

These apply everywhere and are enforced by review, not by a linter.

- Booleans start with `is_`, `has_`, or `can_`.
- Collections are plural; single items singular.
- Repository methods: `get_<thing>_by_<field>` returns one or `None`, `list_<things>` returns many, plus `create_`, `update_`, `delete_`, `exists_`.
- Service methods name the use case: `book_appointment`, not `process`.
- No type names in variable names, and no `data`, `info`, `tmp`, or `result` when a specific word exists.
- Abbreviations only when the plan's glossary defines them (MRN, FEFO).
- Tests: `test_<action>_<condition>_<expected>`.
