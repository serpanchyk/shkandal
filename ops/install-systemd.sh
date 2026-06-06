#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
unit_dir="${script_dir}/systemd"

sudo install -m 0644 "${unit_dir}/shkandal-ingestion.service" /etc/systemd/system/
sudo install -m 0644 "${unit_dir}/shkandal-ingestion.timer" /etc/systemd/system/
sudo install -m 0644 "${unit_dir}/shkandal-ml-worker.service" /etc/systemd/system/
sudo install -m 0644 "${unit_dir}/shkandal-ml-worker.timer" /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now shkandal-ingestion.timer shkandal-ml-worker.timer
systemctl list-timers "shkandal-*"
