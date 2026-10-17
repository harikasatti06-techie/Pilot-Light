"""Vercel entry point (FastAPI zero-config): serves the operator dashboard.

Vercel reserves AWS_* environment variable names and sets AWS_REGION to the function's own
region, so the dashboard's read-only keys arrive as PL_AWS_* and are mapped here before boto3 loads.
"""
import os
import sys

if os.environ.get("PL_AWS_ACCESS_KEY_ID"):
    os.environ["AWS_ACCESS_KEY_ID"] = os.environ["PL_AWS_ACCESS_KEY_ID"]
    os.environ["AWS_SECRET_ACCESS_KEY"] = os.environ.get("PL_AWS_SECRET_ACCESS_KEY", "")
    os.environ.pop("AWS_SESSION_TOKEN", None)
os.environ.pop("AWS_PROFILE", None)
os.environ["AWS_REGION"] = os.environ["AWS_DEFAULT_REGION"] = os.environ.get("PL_AWS_REGION", "us-east-2")
# Fail CloudWatch reads fast instead of probing instance metadata when no keys are set
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dashboard.app import app  # noqa: E402,F401
