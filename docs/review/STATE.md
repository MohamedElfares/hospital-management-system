# Review state

One row per reviewed file. `/review new` compares each file against the
commit recorded here and reviews only what changed since.

Keep rows sorted by path. Delete the row when the file is deleted. A file
with no row has never been reviewed and is always in scope.

| File | Reviewed at commit | Date | Run |
|---|---|---|---|
| `backend/app/core/__init__.py` | `d5dc7cd` | 2026-11-04 | 1 |
| `backend/app/core/config.py` | `2127a70` | 2026-11-04 | 1 |
| `backend/app/core/errors.py` | `d5dc7cd` | 2026-11-04 | 1 |
| `backend/app/core/logging.py` | `2127a70` | 2026-11-04 | 1 |
