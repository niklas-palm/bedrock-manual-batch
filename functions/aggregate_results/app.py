import json
import os
import boto3
import csv
from io import StringIO
from aws_lambda_powertools import Logger

logger = Logger()

dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")
table = dynamodb.Table(os.environ["RESULTS_TABLE"])
result_bucket = os.environ["RESULT_BUCKET"]


def lambda_handler(event, context):
    try:
        execution_id = event["execution_id"]
        job_prefix = event["job_prefix"]

        logger.info(f"Starting aggregation for execution_id: {execution_id}")
        logger.info(f"Using DynamoDB table: {os.environ['RESULTS_TABLE']}")

        # Query all results for this job
        results = []
        last_evaluated_key = None

        try:
            while True:
                query_params = {
                    "KeyConditionExpression": "execution_id = :jp",
                    "ExpressionAttributeValues": {":jp": execution_id},
                }

                if last_evaluated_key:
                    query_params["ExclusiveStartKey"] = last_evaluated_key

                logger.info(
                    f"Querying DynamoDB with params: {json.dumps(query_params, default=str)}"
                )

                response = table.query(**query_params)

                batch_items = response.get("Items", [])
                logger.info(f"Found {len(batch_items)} items in this query batch")
                if batch_items:
                    logger.info(
                        f"Sample item: {json.dumps(batch_items[0], default=str)}"
                    )

                results.extend(batch_items)

                last_evaluated_key = response.get("LastEvaluatedKey")
                if not last_evaluated_key:
                    break

        except Exception as e:
            logger.error(f"Error querying DynamoDB: {str(e)}")
            raise

        logger.info(f"Total items found: {len(results)}")

        if not results:
            logger.warning("No results found in DynamoDB!")
            return {
                "statusCode": 200,
                "body": f"No results found for execution_id: {execution_id}",
            }

        # Sort by prompt_id
        results.sort(key=lambda x: x["prompt_id"])

        # Create CSV
        output = StringIO()
        writer = csv.DictWriter(
            output, fieldnames=["prompt_id", "prompt", "completion"]
        )
        writer.writeheader()

        for item in results:
            writer.writerow(
                {
                    "prompt_id": item["prompt_id"],
                    "prompt": item["prompt"],
                    "completion": item["completion"],
                }
            )

        csv_content = output.getvalue()

        # Upload to S3
        s3_key = f"{job_prefix}/output/results.csv"
        logger.info(f"Uploading to S3: bucket={result_bucket}, key={s3_key}")

        s3.put_object(
            Bucket=result_bucket,
            Key=s3_key,
            Body=csv_content,
        )

        logger.info(f"Successfully aggregated results for execution_id: {execution_id}")
        return {
            "statusCode": 200,
            "body": f"Results aggregated for execution_id: {execution_id}",
        }

    except Exception as e:
        logger.error(f"Error aggregating results: {str(e)}")
        logger.error(f"Event received: {json.dumps(event, default=str)}")
        raise
