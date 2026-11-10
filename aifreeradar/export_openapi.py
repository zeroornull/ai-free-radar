"""Export the public API schema without loading configuration or starting services."""

from __future__ import annotations

import json
import sys

from fastapi import FastAPI

from .api import APP_VERSION, router


def main() -> None:
    app = FastAPI(
        title="AIFreeRadar",
        version=APP_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.include_router(router)
    json.dump(app.openapi(), sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
