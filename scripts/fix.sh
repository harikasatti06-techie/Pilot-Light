#!/usr/bin/env bash
# Manual reset between rehearsals
source "$(dirname "$0")/_env.sh"
aws ssm put-parameter --name "$PARAM" --value off --overwrite >/dev/null && echo "fail_mode = off"
