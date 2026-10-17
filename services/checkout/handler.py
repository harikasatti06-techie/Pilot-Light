"""Demo checkout service. Fails with PaymentTimeout while SSM fail_mode is "on"."""
import json
import os
import time

import boto3

ssm = boto3.client("ssm")
cw = boto3.client("cloudwatch")
PARAM = os.environ["FAIL_MODE_PARAM"]
_cache = {"v": "off", "t": 0.0}


def fail_mode() -> str:
    if time.time() - _cache["t"] > 2:  # re-read every 2s
        _cache["v"] = ssm.get_parameter(Name=PARAM)["Parameter"]["Value"]
        _cache["t"] = time.time()
    return _cache["v"]


def handler(event, context):
    if fail_mode() == "on":
        print("ERROR PaymentTimeout: upstream payment provider timed out after 3000ms")
        cw.put_metric_data(Namespace="PilotLight", MetricData=[{
            "MetricName": "CheckoutErrors", "Value": 1, "Unit": "Count",
            "StorageResolution": 1}])  # high-res so the alarm fires in seconds
        return {"statusCode": 502, "body": json.dumps({"error": "PaymentTimeout"})}
    return {"statusCode": 200, "body": json.dumps({"ok": True})}
