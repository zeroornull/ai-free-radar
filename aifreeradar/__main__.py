from __future__ import annotations

import uvicorn

from .config import load_config_document
from .web import create_app


def main() -> None:
    _, document, settings = load_config_document()
    uvicorn.run(
        create_app(settings, config_document=document),
        host="127.0.0.1",
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()