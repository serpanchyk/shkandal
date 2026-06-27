#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
unit_dir="${script_dir}/systemd"
project_dir="$(cd -- "${script_dir}/.." && pwd)"
user_unit_dir="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"

mkdir -p "${user_unit_dir}"

systemctl --user stop shkandal-remote-ingestion.timer || true
systemctl --user stop \
    shkandal-remote-ingestion.service \
    shkandal-remote-ml.service \
    shkandal-remote-db-tunnel.service \
    || true
docker rm -f \
    shkandal-remote-scheduled-worker-ingestion \
    shkandal-remote-scheduled-worker-ml \
    >/dev/null 2>&1 || true

install_service() {
    local service_name="$1"
    local source_path="${unit_dir}/${service_name}"
    local destination_path="${user_unit_dir}/${service_name}"

    sed \
        -e "s|WorkingDirectory=/opt/shkandal|WorkingDirectory=${project_dir}|" \
        -e '/^Wants=network-online.target$/d' \
        -e '/^After=network-online.target$/d' \
        "${source_path}" > "${destination_path}"
}

install_service shkandal-remote-db-tunnel.service
install_service shkandal-remote-ingestion.service
install -m 0644 "${unit_dir}/shkandal-remote-ingestion.timer" "${user_unit_dir}/"
install_service shkandal-remote-ml.service

systemctl --user daemon-reload
systemctl --user enable --now shkandal-remote-db-tunnel.service
systemctl --user enable --now shkandal-remote-ingestion.timer

cat <<'EOF'
Installed remote worker user-systemd units.

Verify:
  systemctl --user status shkandal-remote-db-tunnel.service
  systemctl --user list-timers "shkandal-remote-*"
  journalctl --user -u shkandal-remote-ingestion.service -n 100 --no-pager

Manual ML run:
  systemctl --user start shkandal-remote-ml.service
  journalctl --user -u shkandal-remote-ml.service -f
EOF
