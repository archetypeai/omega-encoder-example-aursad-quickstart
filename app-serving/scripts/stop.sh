#!/bin/sh
# Stop everything this app starts and verify its ports are free. The serving
# bridge ends its serving session and deployment on SIGTERM, which can take a
# while when the platform is slow: it gets up to 60 s.
# npm starts the bridge and replayer with `--app=aursad-serving`, which is what is
# matched: other demos' bridges and replayers can share these script names.
HERE=$(cd "$(dirname "$0")/.." && pwd)
pkill -TERM -f "serving-bridge.js --app=aursad-serving" 2>/dev/null
i=0
while [ $i -lt 60 ]; do
	i=$((i + 1))
	pgrep -f "serving-bridge.js --app=aursad-serving" >/dev/null 2>&1 || break
	sleep 1
done
pkill -f "mosquitto -c $HERE/mosquitto/mosquitto.conf" 2>/dev/null
pkill -f "replayer.js --app=aursad-serving" 2>/dev/null
pkill -f "vite dev --port 5183" 2>/dev/null
sleep 1
busy=0
for p in 1893 9011 5183; do
	if lsof -nP -iTCP:$p -sTCP:LISTEN >/dev/null 2>&1; then
		echo "port $p still held by: $(lsof -nP -iTCP:$p -sTCP:LISTEN | awk 'NR==2{print $1" (pid "$2")"}')"
		busy=1
	fi
done
[ $busy -eq 0 ] && echo "all ports free (1893 · 9011 · 5183)"
if [ -f "$HERE/../out/app_serving_state.json" ]; then
	echo "out/app_serving_state.json is still there: the bridge didn't end everything. Start the app again (the bridge ends what it left) or run python scripts/cleanup.py"
fi
