#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
unit_dir="${script_dir}/systemd"
project_dir="$(cd -- "${script_dir}/.." && pwd)"
user_unit_dir="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"

mkdir -p "${user_unit_dir}"
systemctl --user stop shkandal-ingestion.timer shkandal-ml-worker.timer || true
systemctl --user stop shkandal-ingestion.service shkandal-ml-worker.service || true
"${script_dir}/remove-orphaned-worker-oneoffs"
docker rm -f shkandal-scheduled-worker-ingestion shkandal-scheduled-worker-ml \
    >/dev/null 2>&1 || true

install_service() {
    local service_name="$1"
    local source_path="${unit_dir}/${service_name}"
    local destination_path="${user_unit_dir}/${service_name}"

    sed \
        -e "s|WorkingDirectory=/opt/shkandal|WorkingDirectory=${project_dir}|" \
        -e '/^Wants=network-online.target$/d' \
        -e '/^After=network-online.target docker.service$/d' \
        -e '/^Requires=docker.service$/d' \
        "${source_path}" > "${destination_path}"
}

install_service shkandal-ingestion.service
install -m 0644 "${unit_dir}/shkandal-ingestion.timer" "${user_unit_dir}/"
install_service shkandal-ml-worker.service
install -m 0644 "${unit_dir}/shkandal-ml-worker.timer" "${user_unit_dir}/"

systemctl --user daemon-reload
systemctl --user enable --now shkandal-ingestion.timer shkandal-ml-worker.timer
systemctl --user list-timers "shkandal-*"
