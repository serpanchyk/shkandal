"""Backend process entrypoint."""

import uvicorn

from shkandal_backend.app import create_app
from shkandal_backend.config import BackendConfig


def main() -> None:
    settings = BackendConfig()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
