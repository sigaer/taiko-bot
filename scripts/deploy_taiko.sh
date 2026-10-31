#!/usr/bin/env bash
# Switch only a previously verified installed release. Never copy business data.
set -euo pipefail
[[ $# == 2 || ( $# == 3 && "$3" == screen ) ]] || { echo 'Usage: deploy_taiko.sh VERSION LEGACY_NB_PID_OR_0 [screen]' >&2; exit 2; }
version="$1"
legacy_pid="$2"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && "$legacy_pid" =~ ^[0-9]+$ ]] || exit 2
exec 9>/run/lock/taiko-deploy.lock
flock -n 9 || exit 75
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
release="/opt/taiko-bot/releases/$version"
"$release/bin/python" -I -c 'import importlib.metadata as m,sys; assert m.version("taiko-bot")==sys.argv[1]; import taiko_bot,taiko_store,runtime_memory; assert all("site-packages" in x.__file__ for x in (taiko_bot,taiko_store,runtime_memory))' "$version"
"$release/bin/pip" check
launch_mode="${3:-systemd}"
mode_file=/home/sigaer/taiko/runtime/bot-launch-mode
if [[ $# == 2 && -f "$mode_file" ]]; then launch_mode="$(<"$mode_file")"; fi
[[ "$launch_mode" == systemd || "$launch_mode" == screen ]] || { echo 'Unknown Bot launch mode' >&2; exit 1; }
if [[ "$launch_mode" == screen ]]; then
  /usr/bin/python3 "$root/scripts/taiko_screen.py" stop
fi
if [[ "$legacy_pid" != 0 ]]; then
  [[ "$(readlink -f "/proc/$legacy_pid/cwd")" == /home/sigaer/taiko ]] || exit 1
  [[ "$(tr '\0' ' ' <"/proc/$legacy_pid/cmdline")" == *'/usr/local/bin/nb run '* ]] || exit 1
  mapfile -t children < <(pgrep -P "$legacy_pid" || true)
  [[ ${#children[@]} == 1 ]] || { echo 'Unexpected legacy process tree' >&2; exit 1; }
  [[ "$(tr '\0' ' ' <"/proc/${children[0]}/cmdline")" == *'python bot.py '* ]] || exit 1
  screen -S taiko -p 0 -X stuff $'\003'
  for _ in $(seq 1 45); do
    if ! kill -0 "$legacy_pid" 2>/dev/null && ! kill -0 "${children[0]}" 2>/dev/null; then break; fi
    sleep 1
  done
  ! kill -0 "$legacy_pid" 2>/dev/null
  ! kill -0 "${children[0]}" 2>/dev/null
fi
ln -s "$release" /opt/taiko-bot/current.next
mv -T /opt/taiko-bot/current.next /opt/taiko-bot/current
install -m 644 "$root/deploy/services/taiko-bot.service" /etc/systemd/system/
install -m 644 "$root/deploy/services/taiko-public-api.service" /etc/systemd/system/
install -m 644 "$root/deploy/services/taiko-sync-dispatch.service" /etc/systemd/system/taiko-sync-receiver.service
# Supersede the existing recovery interpreter override with the release pointer.
install -d -m 755 /etc/systemd/system/taiko-sync-receiver.service.d
install -m 644 "$root/deploy/services/taiko-sync-runtime.conf" /etc/systemd/system/taiko-sync-receiver.service.d/zz-publication-runtime.conf
install -m 644 "$root/deploy/offline/taiko-song-update.service" /etc/systemd/system/
install -m 644 "$root/deploy/services/taiko-storage-maintenance.service" /etc/systemd/system/
install -m 644 "$root/deploy/offline/taiko_admin_backup.cron" /etc/cron.d/taiko-admin-backup
systemctl daemon-reload
for service in taiko-public-api taiko-sync-receiver taiko-song-update; do
  systemctl restart "$service"
  systemctl is-active --quiet "$service"
done
if [[ "$launch_mode" == screen ]]; then
  /usr/bin/python3 "$root/scripts/taiko_screen.py" start
else
  systemctl enable taiko-bot
  systemctl restart taiko-bot
fi
for _ in $(seq 1 45); do
  if curl -fsS --max-time 2 http://127.0.0.1:37564/internal/bot-pool >/dev/null; then
    echo "Taiko $version active from $release"
    exit 0
  fi
  sleep 1
done
echo 'Taiko did not become healthy; stopped without fallback' >&2
exit 1
