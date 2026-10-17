#!/usr/bin/env python3
"""CDK app entry point for Pilot Light Auto-Fix pipeline."""

import aws_cdk as cdk
from auto_fix_stack import AutoFixStack

app = cdk.App()
AutoFixStack(app, "PilotLightAutoFix", env=cdk.Environment(region="us-east-1"))
app.synth()
