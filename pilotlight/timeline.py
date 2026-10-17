"""DynamoDB timeline helpers."""

import boto3
import datetime
from .config import TIMELINE_TABLE

table = boto3.resource("dynamodb").Table(TIMELINE_TABLE)


def add(incident_id: str, type_: str, text: str):
    ts = datetime.datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
    table.put_item(Item={
        "incident_id": incident_id,
        "ts": ts,
        "type": type_,
        "text": text,
    })


def list_all(incident_id: str):
    r = table.query(
        KeyConditionExpression="incident_id = :i",
        ExpressionAttributeValues={":i": incident_id},
    )
    return r["Items"]
