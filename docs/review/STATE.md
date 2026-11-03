# Review state

One row per reviewed file. `/review new` compares each file against the
commit recorded here and reviews only what changed since.

Keep rows sorted by path. Delete the row when the file is deleted. A file
with no row has never been reviewed and is always in scope.

| File | Reviewed at commit | Date | Run |
|---|---|---|---|
| backend/app/core/security.py | 1a2b3c4 | 2026-11-02 | 1 |
