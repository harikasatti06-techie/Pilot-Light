"""Environment configuration shared by Lambdas, scripts, and the voice server."""
import os

try:  # python-dotenv is not installed in Lambda; env vars come from the function config there
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

FAIL_MODE_PARAM = os.getenv("FAIL_MODE_PARAM", "/pilotlight/checkout/fail_mode")
TIMELINE_TABLE = os.getenv("TIMELINE_TABLE", "pilotlight-timeline")
INCIDENTS_TABLE = os.getenv("INCIDENTS_TABLE", "pilotlight-incidents")
CHECKOUT_LOG_GROUP = os.getenv("CHECKOUT_LOG_GROUP", "/aws/lambda/pilotlight-checkout")
ALARM_NAME = os.getenv("ALARM_NAME", "pilotlight-checkout-5xx")

BOX_CLIENT_ID = os.getenv("BOX_CLIENT_ID", "")
BOX_CLIENT_SECRET = os.getenv("BOX_CLIENT_SECRET", "")
BOX_ENTERPRISE_ID = os.getenv("BOX_ENTERPRISE_ID", "")
BOX_RUNBOOKS_FOLDER_ID = os.getenv("BOX_RUNBOOKS_FOLDER_ID", "")
BOX_INCIDENTS_FOLDER_ID = os.getenv("BOX_INCIDENTS_FOLDER_ID", "")
BOX_REVIEWER_LOGIN = os.getenv("BOX_REVIEWER_LOGIN", "")

SONIC_MODEL_ID = os.getenv("SONIC_MODEL_ID", "amazon.nova-2-sonic-v1:0")
TEXT_MODEL_ID = os.getenv("TEXT_MODEL_ID", "")

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
ONCALL_PHONE = os.getenv("ONCALL_PHONE", "")
PAGE_PHONE = os.getenv("PAGE_PHONE", "")

VOICE_SERVER_URL = os.getenv("VOICE_SERVER_URL", "").rstrip("/")
