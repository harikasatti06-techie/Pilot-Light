# Shared by the demo scripts
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1
PARAM=/pilotlight/checkout/fail_mode
ALARM=pilotlight-checkout-5xx
api_url() {
  aws cloudformation describe-stacks --stack-name PilotLight \
    --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text
}
