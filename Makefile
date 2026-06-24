.PHONY: dev-demo reset-demo demo-down ingest ml install-systemd install-user-systemd timers user-timers logs-ingest logs-ml

dev-demo:
	./scripts/run_demo.sh

reset-demo:
	./scripts/reset_demo.sh

demo-down:
	docker compose -p shkandal-demo -f docker-compose.demo.yaml down --remove-orphans

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
