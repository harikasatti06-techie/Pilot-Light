#!/usr/bin/env bash
# Current flag, alarm state, and the latest incident with its timeline
source "$(dirname "$0")/_env.sh"
echo "fail_mode: $(aws ssm get-parameter --name "$PARAM" --query Parameter.Value --output text)"
echo "alarm:     $(aws cloudwatch describe-alarms --alarm-names "$ALARM" --query 'MetricAlarms[0].StateValue' --output text)"
IID=$(aws dynamodb scan --table-name pilotlight-incidents --projection-expression "incident_id,started_at" \
  --query "reverse(sort_by(Items,&started_at.S))[0].incident_id.S" --output text)
echo "latest:    $IID"
[ "$IID" != "None" ] && aws dynamodb query --table-name pilotlight-timeline \
  --key-condition-expression "incident_id = :i" --expression-attribute-values "{\":i\":{\"S\":\"$IID\"}}" \
  --query "Items[].[ts.S,type.S,text.S]" --output text
