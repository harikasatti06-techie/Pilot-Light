#!/usr/bin/env python3
import os
from pathlib import Path

import aws_cdk as cdk
from dotenv import load_dotenv

from stack import PilotLightStack

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

app = cdk.App()
PilotLightStack(app, "PilotLight", env=cdk.Environment(
    account=os.getenv("CDK_DEFAULT_ACCOUNT"), region="us-east-1"))
app.synth()
