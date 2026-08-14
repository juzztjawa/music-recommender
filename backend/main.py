"""Dev entry point. Run from `backend/`: `uv run main.py`.

Lives here, not inside `app/`, so it can never be run as a standalone script
from within its own package — that breaks `app`'s internal imports (Python
only puts the script's own directory on `sys.path`, not its parent, so the
`app` package becomes invisible to itself). `uvicorn.run("app.app:app", ...)`
below imports `app` properly instead.
"""

import uvicorn

from app.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.app:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )
