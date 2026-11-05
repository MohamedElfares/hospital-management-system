from pathlib import Path

import app


def test_every_folder_of_application_code_is_a_regular_package() -> None:
    """Every folder under ``app/`` that holds Python files has an ``__init__.py``.

    Without one, Python still imports the folder, as a namespace package,
    but coverage.py skips such a folder when it looks for files no test
    ran. An untested module there would be left out of the coverage report
    instead of counting as 0%, so the coverage gate would never see it.
    The check walks the real ``app`` package, so a module folder added
    later, such as ``patients``, is checked too.
    """
    app_root = Path(app.__file__).parent
    folders = [app_root, *(path for path in app_root.rglob("*") if path.is_dir())]

    folders_without_init = [
        folder.relative_to(app_root.parent).as_posix()
        for folder in folders
        if any(folder.glob("*.py")) and not (folder / "__init__.py").is_file()
    ]

    assert folders_without_init == []
