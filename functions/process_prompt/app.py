import json
import os
import boto3
import time
from botocore.exceptions import ClientError
from aws_lambda_powertools import Logger

logger = Logger()

bedrock_client = boto3.client("bedrock-runtime")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["RESULTS_TABLE"])

MODEL_ID = "us.anthropic.claude-3-5-sonnet-20241022-v2:0"


def lambda_handler(event, context):
    logger.info(event)
    try:
        data = event["data"]
        execution_id = data["execution_id"]
        row_data = data["csv_row"]
        prompt_id = row_data["prompt_id"]
        prompt = row_data["prompt"]

        try:
            model_payload = get_prompt_payload(prompt)
            bedrock_response = invoke_model(model_payload)
            completion = get_completion_from_response(bedrock_response)
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code in [
                "ThrottlingException",
                "ServiceQuotaExceededException",
                "TooManyRequestsException",
                "InternalServerException",
                "ServiceUnavailableException",
            ]:
                logger.warning(
                    f"Retriable error occurred: {error_code} for prompt_id: {prompt_id}"
                )
                raise
            elif error_code == "ValidationException":
                logger.error(f"Validation error for prompt_id {prompt_id}: {str(e)}")
                raise
            else:
                logger.error(
                    f"Unexpected AWS error for prompt_id {prompt_id}: {error_code} - {str(e)}"
                )
                raise

        ttl = int(time.time()) + (
            2 * 24 * 60 * 60
        )  # Ensure item is deleted after 2 days

        table.put_item(
            Item={
                "execution_id": execution_id,
                "prompt_id": prompt_id,
                "prompt": prompt,
                "completion": completion,
                "ttl": ttl,
            }
        )

        logger.info(
            f"Successfully processed execution_id: {execution_id}, prompt_id: {prompt_id}"
        )
        return {
            "statusCode": 200,
            "body": f"Processed execution_id: {execution_id}, prompt_id: {prompt_id}",
        }

    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}")
        raise


def get_prompt_payload(prompt):
    messages = [{"type": "text", "text": prompt}]

    request = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": messages}],
        "temperature": 0,
    }

    return json.dumps(request)


def invoke_model(payload):
    response = bedrock_client.invoke_model(
        body=payload,
        modelId=MODEL_ID,
    )
    return json.loads(response.get("body").read())


def get_completion_from_response(response):
    return response["content"][0]["text"]
