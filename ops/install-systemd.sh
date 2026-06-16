#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
unit_dir="${script_dir}/systemd"
project_dir="$(cd -- "${script_dir}/.." && pwd)"

sudo systemctl stop shkandal-ingestion.timer shkandal-ml-worker.timer || true
sudo systemctl stop shkandal-ingestion.service shkandal-ml-worker.service || true
"${script_dir}/remove-orphaned-worker-oneoffs"
docker rm -f shkandal-scheduled-worker-ingestion shkandal-scheduled-worker-ml \
    >/dev/null 2>&1 || true

install_service() {
    local service_name="$1"
    local source_path="${unit_dir}/${service_name}"
    local rendered_path

    rendered_path="$(mktemp)"
    sed "s|WorkingDirectory=/opt/shkandal|WorkingDirectory=${project_dir}|" \
        "${source_path}" > "${rendered_path}"
    sudo install -m 0644 "${rendered_path}" "/etc/systemd/system/${service_name}"
    rm -f "${rendered_path}"
}

install_service shkandal-ingestion.service
sudo install -m 0644 "${unit_dir}/shkandal-ingestion.timer" /etc/systemd/system/
install_service shkandal-ml-worker.service
sudo install -m 0644 "${unit_dir}/shkandal-ml-worker.timer" /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now shkandal-ingestion.timer shkandal-ml-worker.timer
systemctl list-timers "shkandal-*"
