"""Simple CloudWatch Metrics helpers for emitting custom metrics."""
import boto3

from .config import AWS_REGION

cloudwatch = boto3.client("cloudwatch", region_name=AWS_REGION)


def put_metric(namespace: str, name: str, value: float = 1.0, unit: str = "Count", dimensions: dict | None = None) -> None:
    """Emit a single metric data point to CloudWatch."""
    metric_data = {
        "MetricName": name,
        "Value": value,
        "Unit": unit,
    }
    if dimensions:
        metric_data["Dimensions"] = [{"Name": k, "Value": v} for k, v in dimensions.items()]

    try:
        cloudwatch.put_metric_data(Namespace=namespace, MetricData=[metric_data])
    except Exception as e:
        # Never crash the service over metrics
        print(f"[metrics] failed to emit {namespace}/{name}: {e}")
