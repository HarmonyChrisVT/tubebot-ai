#!/bin/bash
set -e

export PORT="${PORT:-8080}"
echo "Starting TubeBot AI on port ${PORT}…"

envsubst '${PORT}' < /etc/nginx/conf.d/default.conf.template > /etc/nginx/conf.d/default.conf

echo "Starting API server…"
cd /app/python
uvicorn main:app --host 0.0.0.0 --port 8000 &

echo "Waiting for API server…"
for i in $(seq 1 30); do
    if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
        echo "API server ready."
        break
    fi
    sleep 1
done

echo "Starting web server…"
nginx -g "daemon off;" &

echo "TubeBot AI is running!"
wait
