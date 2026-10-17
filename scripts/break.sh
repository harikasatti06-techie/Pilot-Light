#!/usr/bin/env bash
source "$(dirname "$0")/_env.sh"
aws ssm put-parameter --name "$PARAM" --value on --overwrite >/dev/null && echo "fail_mode = on"
