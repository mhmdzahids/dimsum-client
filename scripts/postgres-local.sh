#!/usr/bin/env bash
set -euo pipefail
# Uses the user-local PostgreSQL runtime installed for this workspace.
pg_root="${DIMSUM_PG_ROOT:-$HOME/.local/share/dimsum-postgresql}"
pg_bin="$pg_root/runtime/usr/lib/postgresql/18/bin"
export LD_LIBRARY_PATH="$pg_root/runtime/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
mkdir -p "$pg_root/socket"
chmod 700 "$pg_root/socket"
case "${1:-status}" in
  start) "$pg_bin/pg_ctl" -D "$pg_root/data" -l "$pg_root/data/server.log" -o "-k $pg_root/socket -p 55432 -c listen_addresses=''" start ;;
  stop) "$pg_bin/pg_ctl" -D "$pg_root/data" stop ;;
  status) "$pg_bin/pg_ctl" -D "$pg_root/data" status ;;
  *) echo 'Usage: scripts/postgres-local.sh start|stop|status'; exit 2 ;;
esac
