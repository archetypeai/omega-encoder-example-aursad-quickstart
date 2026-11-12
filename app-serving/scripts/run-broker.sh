#!/bin/sh
# Local broker for the Omega AURSAD monitor (app-serving/): TCP for the serving bridge and replayer, WebSockets
# for the browser. Config in mosquitto/mosquitto.conf.
set -e
HERE=$(cd "$(dirname "$0")/.." && pwd)
# Homebrew installs mosquitto to sbin, which is often not on PATH.
for d in /opt/homebrew/sbin /usr/local/sbin; do
	[ -x "$d/mosquitto" ] && PATH="$PATH:$d"
done
command -v mosquitto >/dev/null 2>&1 || {
	echo "mosquitto not found. Install it: brew install mosquitto" >&2
	exit 1
}
for p in 1893 9011; do
	if lsof -nP -iTCP:$p -sTCP:LISTEN >/dev/null 2>&1; then
		holder=$(lsof -nP -iTCP:$p -sTCP:LISTEN 2>/dev/null | awk 'NR==2{print $1" (pid "$2")"}')
		echo "port $p is already held by $holder — 'npm run stop' clears it." >&2
		exit 1
	fi
done
exec mosquitto -c "$HERE/mosquitto/mosquitto.conf"
