"""Optional healthcheck for an ingestion worker running in loop mode."""

from worker_ingestion.config import IngestionConfig
from worker_ingestion.runtime import heartbeat_is_fresh


def main() -> None:
    config = IngestionConfig()
    raise SystemExit(
        0
        if heartbeat_is_fresh(
            config.heartbeat_path,
            max_age_seconds=config.heartbeat_max_age_seconds,
        )
        else 1
    )


if __name__ == "__main__":
    main()
