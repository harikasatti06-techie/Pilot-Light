"""Load environment variables and expose as constants."""

import os
from dotenv import load_dotenv

load_dotenv()

# AWS
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# DynamoDB tables
TIMELINE_TABLE = os.getenv("TIMELINE_TABLE", "pilotlight-timeline")
INCIDENTS_TABLE = os.getenv("INCIDENTS_TABLE", "pilotlight-incidents")
TASKS_TABLE = os.getenv("TASKS_TABLE", "pilotlight-tasks")

# SSM / CloudWatch
FAIL_MODE_PARAM = os.getenv("FAIL_MODE_PARAM", "/pilotlight/checkout/fail_mode")
CHECKOUT_LOG_GROUP = os.getenv("CHECKOUT_LOG_GROUP", "/aws/lambda/pilotlight-checkout")
ALARM_NAME = os.getenv("ALARM_NAME", "pilotlight-checkout-5xx")

# Box
BOX_CLIENT_ID = os.getenv("BOX_CLIENT_ID", "")
BOX_CLIENT_SECRET = os.getenv("BOX_CLIENT_SECRET", "")
BOX_ENTERPRISE_ID = os.getenv("BOX_ENTERPRISE_ID", "")
BOX_RUNBOOKS_FOLDER_ID = os.getenv("BOX_RUNBOOKS_FOLDER_ID", "")
BOX_INCIDENTS_FOLDER_ID = os.getenv("BOX_INCIDENTS_FOLDER_ID", "")
BOX_REVIEWER_LOGIN = os.getenv("BOX_REVIEWER_LOGIN", "")

# Bedrock
SONIC_MODEL_ID = os.getenv("SONIC_MODEL_ID", "amazon.nova-2-sonic-v1:0")
TEXT_MODEL_ID = os.getenv(
    "TEXT_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0"
)

# Telephony
VOICE_SERVER_URL = os.getenv("VOICE_SERVER_URL", "")
ONCALL_PHONE = os.getenv("ONCALL_PHONE", "")

# GitHub (for auto-fix CR creation)
GITHUB_REPO = os.getenv("GITHUB_REPO", "")  # e.g. "harikasatti06-techie/Pilot-Light"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# CodeBuild
CODEBUILD_PROJECT = os.getenv("CODEBUILD_PROJECT", "pilotlight-agent")

# Confidence threshold for auto-fix decisions
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.6"))

# Auto-fix dispatcher
DISPATCHER_FUNCTION_NAME = os.getenv("DISPATCHER_FUNCTION_NAME", "pilotlight-dispatcher")
