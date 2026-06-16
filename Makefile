.PHONY: ingest ml install-systemd install-user-systemd timers user-timers logs-ingest logs-ml

ingest:
	docker compose --profile jobs run --rm worker-ingestion

ml:
	docker compose --profile jobs run --rm worker-ml

install-systemd:
	./ops/install-systemd.sh

install-user-systemd:
	./ops/install-user-systemd.sh

timers:
	systemctl list-timers "shkandal-*"

user-timers:
	systemctl --user list-timers "shkandal-*"

logs-ingest:
	journalctl -u shkandal-ingestion.service -f

logs-ml:
	journalctl -u shkandal-ml-worker.service -f
