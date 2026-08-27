# Agent Instructions — desktop_app/

Must not import repo-root modules (`database.py`, `retriever_v2.py`, etc.)
— this package is bundled separately from the backend via
`windows_installer/build_installer.py` (PyInstaller), and a repo-root
import will break at build time even though it works fine when run from
source. Talk to the backend only over its HTTP API.
