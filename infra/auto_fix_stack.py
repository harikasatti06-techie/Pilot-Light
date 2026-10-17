"""CDK stack for the Pilot Light Auto-Fix pipeline.

Creates DynamoDB tables, Secrets Manager secrets, CodeBuild project,
Lambda functions, API Gateway webhook endpoint, and EventBridge rule.
"""

from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    BundlingOptions,
    aws_lambda as _lambda,
    aws_dynamodb as dynamodb,
    aws_codebuild as codebuild,
    aws_iam as iam,
    aws_events as events,
    aws_events_targets as targets,
    aws_apigateway as apigw,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct


class AutoFixStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs):
        super().__init__(scope, id, **kwargs)

        # ---------------------------------------------------------------------
        # DynamoDB Tables
        # ---------------------------------------------------------------------
        tasks_table = dynamodb.Table(
            self,
            "TasksTable",
            table_name="pilotlight-tasks",
            partition_key=dynamodb.Attribute(
                name="incident_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="task_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Reference existing tables created elsewhere (incidents, timeline).
        # Use from_table_name so we can grant permissions without owning them.
        incidents_table = dynamodb.Table.from_table_name(
            self, "IncidentsTableRef", "pilotlight-incidents"
        )
        timeline_table = dynamodb.Table.from_table_name(
            self, "TimelineTableRef", "pilotlight-timeline"
        )

        # ---------------------------------------------------------------------
        # Secrets Manager
        # ---------------------------------------------------------------------
        github_secret = secretsmanager.Secret(
            self,
            "GitHubTokenSecret",
            secret_name="pilotlight/github-token",
            description="GitHub PAT for Pilot Light auto-fix agent",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"token":"CHANGE_ME"}',
                generate_string_key="placeholder",
            ),
        )

        box_secret = secretsmanager.Secret(
            self,
            "BoxCredsSecret",
            secret_name="pilotlight/box-creds",
            description="Box CCG credentials for Pilot Light",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"client_id":"","client_secret":"","enterprise_id":""}',
                generate_string_key="placeholder",
            ),
        )

        # ---------------------------------------------------------------------
        # CodeBuild Project
        # ---------------------------------------------------------------------
        build_project = codebuild.Project(
            self,
            "AgentProject",
            project_name="pilotlight-agent",
            timeout=Duration.minutes(15),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                compute_type=codebuild.ComputeType.MEDIUM,
            ),
            build_spec=codebuild.BuildSpec.from_source_filename(
                "pilotlight/auto_fix/buildspec.yml"
            ),
            source=codebuild.Source.no_source(
                build_spec=codebuild.BuildSpec.from_object(
                    {
                        "version": "0.2",
                        "phases": {
                            "install": {
                                "runtime-versions": {"python": "3.12"},
                                "commands": [
                                    "echo 'Cloning repo...'",
                                    "git clone https://$GITHUB_TOKEN@github.com/$GITHUB_REPO.git repo",
                                    "cd repo && pip install -r requirements.txt",
                                ],
                            },
                            "build": {
                                "commands": [
                                    "cd repo",
                                    "python -m pilotlight.auto_fix.agent",
                                ],
                            },
                        },
                    }
                )
            ),
            environment_variables={
                "GITHUB_TOKEN": codebuild.BuildEnvironmentVariable(
                    value=github_secret.secret_name,
                    type=codebuild.BuildEnvironmentVariableType.SECRETS_MANAGER,
                ),
                "BOX_CLIENT_ID": codebuild.BuildEnvironmentVariable(
                    value=f"{box_secret.secret_name}:client_id",
                    type=codebuild.BuildEnvironmentVariableType.SECRETS_MANAGER,
                ),
                "BOX_CLIENT_SECRET": codebuild.BuildEnvironmentVariable(
                    value=f"{box_secret.secret_name}:client_secret",
                    type=codebuild.BuildEnvironmentVariableType.SECRETS_MANAGER,
                ),
                "BOX_ENTERPRISE_ID": codebuild.BuildEnvironmentVariable(
                    value=f"{box_secret.secret_name}:enterprise_id",
                    type=codebuild.BuildEnvironmentVariableType.SECRETS_MANAGER,
                ),
            },
        )

        # CodeBuild IAM permissions
        build_project.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=["*"],
            )
        )
        tasks_table.grant_read_write_data(build_project)
        timeline_table.grant_read_write_data(build_project)
        github_secret.grant_read(build_project)
        box_secret.grant_read(build_project)

        # ---------------------------------------------------------------------
        # Shared Lambda bundling options
        # ---------------------------------------------------------------------
        lambda_code = _lambda.Code.from_asset(
            "..",  # project root (infra/ is one level down)
            bundling=BundlingOptions(
                image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                command=[
                    "bash",
                    "-c",
                    "pip install box-sdk-gen python-dotenv -t /asset-output "
                    "&& cp -r pilotlight /asset-output/",
                ],
            ),
        )

        # Common environment variables for all Lambdas
        common_env = {
            "TASKS_TABLE": tasks_table.table_name,
            "INCIDENTS_TABLE": incidents_table.table_name,
            "TIMELINE_TABLE": timeline_table.table_name,
            "CODEBUILD_PROJECT": build_project.project_name,
            "GITHUB_SECRET_NAME": github_secret.secret_name,
            "BOX_SECRET_NAME": box_secret.secret_name,
            "AWS_REGION_NAME": "us-east-1",
        }

        # ---------------------------------------------------------------------
        # Lambda: Intake
        # ---------------------------------------------------------------------
        intake_fn = _lambda.Function(
            self,
            "IntakeFn",
            function_name="pilotlight-intake",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="pilotlight.auto_fix.intake.handler",
            code=lambda_code,
            timeout=Duration.minutes(5),
            memory_size=512,
            environment=common_env,
        )

        # ---------------------------------------------------------------------
        # Lambda: Dispatcher
        # ---------------------------------------------------------------------
        dispatcher_fn = _lambda.Function(
            self,
            "DispatcherFn",
            function_name="pilotlight-dispatcher",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="pilotlight.auto_fix.dispatcher.handler",
            code=lambda_code,
            timeout=Duration.minutes(1),
            memory_size=256,
            environment=common_env,
        )

        # ---------------------------------------------------------------------
        # Lambda: Wrapup
        # ---------------------------------------------------------------------
        wrapup_fn = _lambda.Function(
            self,
            "WrapupFn",
            function_name="pilotlight-wrapup",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="pilotlight.auto_fix.wrapup.handler",
            code=lambda_code,
            timeout=Duration.minutes(5),
            memory_size=256,
            environment=common_env,
        )

        # ---------------------------------------------------------------------
        # Lambda IAM Permissions
        # ---------------------------------------------------------------------

        # Intake: DynamoDB (incidents, tasks, timeline), invoke dispatcher,
        #         Bedrock fallback, secrets
        tasks_table.grant_read_write_data(intake_fn)
        incidents_table.grant_read_write_data(intake_fn)
        timeline_table.grant_read_write_data(intake_fn)
        dispatcher_fn.grant_invoke(intake_fn)
        intake_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=["*"],
            )
        )
        github_secret.grant_read(intake_fn)
        box_secret.grant_read(intake_fn)

        # Dispatcher: DynamoDB (tasks, incidents), CodeBuild start
        tasks_table.grant_read_write_data(dispatcher_fn)
        incidents_table.grant_read_write_data(dispatcher_fn)
        dispatcher_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["codebuild:StartBuild"],
                resources=[build_project.project_arn],
            )
        )

        # Wrapup: DynamoDB (tasks, incidents, timeline), secrets
        tasks_table.grant_read_write_data(wrapup_fn)
        incidents_table.grant_read_write_data(wrapup_fn)
        timeline_table.grant_read_write_data(wrapup_fn)
        github_secret.grant_read(wrapup_fn)
        box_secret.grant_read(wrapup_fn)

        # ---------------------------------------------------------------------
        # API Gateway: Box webhook endpoint
        # ---------------------------------------------------------------------
        api = apigw.RestApi(
            self,
            "WebhookApi",
            rest_api_name="pilotlight-webhook-api",
            description="Public endpoint for Box webhook notifications",
        )

        webhook_resource = api.root.add_resource("webhook")
        webhook_resource.add_method(
            "POST",
            apigw.LambdaIntegration(intake_fn),
            authorization_type=apigw.AuthorizationType.NONE,
        )

        # ---------------------------------------------------------------------
        # EventBridge: CodeBuild completion -> wrapup Lambda
        # ---------------------------------------------------------------------
        codebuild_complete_rule = events.Rule(
            self,
            "CodeBuildCompleteRule",
            rule_name="pilotlight-codebuild-complete",
            event_pattern=events.EventPattern(
                source=["aws.codebuild"],
                detail_type=["CodeBuild Build State Change"],
                detail={
                    "project-name": [build_project.project_name],
                    "build-status": ["SUCCEEDED", "FAILED"],
                },
            ),
        )
        codebuild_complete_rule.add_target(targets.LambdaFunction(wrapup_fn))

        # ---------------------------------------------------------------------
        # Outputs
        # ---------------------------------------------------------------------
        CfnOutput(
            self,
            "WebhookUrl",
            value=f"{api.url}webhook",
            description="Box webhook callback URL",
        )
        CfnOutput(
            self,
            "CodeBuildProject",
            value=build_project.project_name,
            description="CodeBuild project for auto-fix agent",
        )
        CfnOutput(
            self,
            "TasksTableName",
            value=tasks_table.table_name,
            description="DynamoDB table for auto-fix tasks",
        )
