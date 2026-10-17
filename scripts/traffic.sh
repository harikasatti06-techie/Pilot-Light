#!/usr/bin/env bash
# Steady checkout traffic. Run for the whole demo. Prints one char per request: . ok, X error.
source "$(dirname "$0")/_env.sh"
URL="${API_URL:-$(api_url)}/checkout"
echo "Sending traffic to $URL (Ctrl-C to stop)"
while true; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "$URL")
  [ "$code" = "200" ] && printf "." || printf "X"
  sleep 0.3
done
