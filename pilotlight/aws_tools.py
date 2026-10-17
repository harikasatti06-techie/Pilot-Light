"""AWS-backed agent tools. Every function returns short, speakable text."""
import datetime
import time

import boto3

from . import timeline
from .config import AWS_REGION, CHECKOUT_LOG_GROUP, FAIL_MODE_PARAM

logs = boto3.client("logs", region_name=AWS_REGION)
ssm = boto3.client("ssm", region_name=AWS_REGION)

ALLOWED_ACTIONS = {
    "revert_fail_mode": "Set /pilotlight/checkout/fail_mode to off",
}

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("America/Los_Angeles")
except Exception:  # no tz database available
    LOCAL_TZ = datetime.timezone(datetime.timedelta(hours=-7))


def _spoken_time(dt: datetime.datetime) -> str:
    return dt.astimezone(LOCAL_TZ).strftime("%-I:%M %p")


def query_logs(incident_id: str, minutes: int = 15) -> str:
    end = int(time.time())
    q = logs.start_query(
        logGroupName=CHECKOUT_LOG_GROUP, startTime=end - minutes * 60, endTime=end,
        queryString='filter @message like /ERROR/ | parse @message "ERROR *:" as err '
                    "| stats count(*) as errors by err | sort errors desc | limit 3")
    r = {"status": "Running", "results": []}
    for _ in range(20):
        r = logs.get_query_results(queryId=q["queryId"])
        if r["status"] == "Complete":
            break
        time.sleep(0.5)
    rows = [{f["field"]: f["value"] for f in row} for row in r["results"]]
    total = sum(int(row.get("errors", 0)) for row in rows)
    if total == 0:
        text = f"No errors in the checkout logs in the last {minutes} minutes."
    else:
        top = rows[0].get("err") or "unknown"
        text = f"In the last {minutes} minutes there were {total} errors. The top error is {top} from the checkout handler."
    timeline.add(incident_id, "tool", f"query_logs: {text}")
    return text


def what_changed(incident_id: str, minutes: int = 60) -> str:
    # History is returned oldest first and paginated, so walk every page and keep the last two
    hist, kwargs = [], {"Name": FAIL_MODE_PARAM, "MaxResults": 50}
    while True:
        r = ssm.get_parameter_history(**kwargs)
        hist = (hist + r["Parameters"])[-2:]
        if "NextToken" not in r:
            break
        kwargs["NextToken"] = r["NextToken"]

    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes)
    if len(hist) < 2 or hist[-1]["LastModifiedDate"] < cutoff:
        text = f"No configuration changes found in the last {minutes} minutes."
    else:
        last, prev = hist[-1], hist[-2]
        who = last.get("LastModifiedUser", "unknown").split("/")[-1]
        text = (f"The parameter fail_mode changed from {prev['Value']} to {last['Value']} "
                f"at {_spoken_time(last['LastModifiedDate'])} by {who}.")
    timeline.add(incident_id, "tool", f"what_changed: {text}")
    return text


def execute_remediation(incident_id: str, action: str, confirmed: bool) -> str:
    if action not in ALLOWED_ACTIONS:
        text = "That action is not on the approved list. I can only revert the fail mode flag."
    elif not confirmed:
        text = "Say confirm and I will revert fail mode to off."
    else:
        ssm.put_parameter(Name=FAIL_MODE_PARAM, Value="off", Overwrite=True)
        text = "Done. fail_mode is now off. Errors should drop within about thirty seconds."
        timeline.add(incident_id, "action", f"{action}: {ALLOWED_ACTIONS[action]} (verbally confirmed)")
        return text
    timeline.add(incident_id, "tool", f"execute_remediation({action}, confirmed={confirmed}): {text}")
    return text
