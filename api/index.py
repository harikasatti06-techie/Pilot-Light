"""Vercel entry point: serves the operator dashboard as a Python function."""
import os
import sys

# No AWS credentials on Vercel: fail CloudWatch reads fast instead of probing instance metadata
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard.app import app  # noqa: E402,F401
