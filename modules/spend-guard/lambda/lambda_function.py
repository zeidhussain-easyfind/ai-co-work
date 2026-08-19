"""
efps-spend-guard-fn
-------------------
Triggered by SNS when daily AWS spend exceeds $5.
Actions:
  - Stops all running EC2 instances
  - Stops all available RDS instances and Aurora clusters
  - Throttles all Lambda functions to 0 concurrency (except itself)

All actions are logged to CloudWatch for easy debugging.
"""

import boto3
import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = "ap-south-1"
THIS_FUNCTION = "efps-spend-guard-fn"

ec2 = boto3.client("ec2", region_name=REGION)
rds = boto3.client("rds", region_name=REGION)
lambda_client = boto3.client("lambda", region_name=REGION)


def stop_ec2_instances():
    response = ec2.describe_instances(
        Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
    )
    instance_ids = [
        instance["InstanceId"]
        for reservation in response["Reservations"]
        for instance in reservation["Instances"]
    ]
    if instance_ids:
        ec2.stop_instances(InstanceIds=instance_ids)
        logger.info(f"[EC2] Stopped instances: {instance_ids}")
    else:
        logger.info("[EC2] No running instances found.")
    return instance_ids


def stop_rds_instances():
    stopped = []

    for db in rds.describe_db_instances()["DBInstances"]:
        if db["DBInstanceStatus"] == "available":
            try:
                rds.stop_db_instance(DBInstanceIdentifier=db["DBInstanceIdentifier"])
                logger.info(f"[RDS] Stopped instance: {db['DBInstanceIdentifier']}")
                stopped.append(db["DBInstanceIdentifier"])
            except Exception as e:
                logger.error(f"[RDS] Could not stop {db['DBInstanceIdentifier']}: {e}")

    for cluster in rds.describe_db_clusters()["DBClusters"]:
        if cluster["Status"] == "available":
            try:
                rds.stop_db_cluster(DBClusterIdentifier=cluster["DBClusterIdentifier"])
                logger.info(f"[RDS] Stopped cluster: {cluster['DBClusterIdentifier']}")
                stopped.append(cluster["DBClusterIdentifier"])
            except Exception as e:
                logger.error(f"[RDS] Could not stop cluster {cluster['DBClusterIdentifier']}: {e}")

    return stopped


def throttle_lambda_functions():
    throttled = []

    for fn in lambda_client.list_functions()["Functions"]:
        fn_name = fn["FunctionName"]
        if fn_name == THIS_FUNCTION:
            continue  # never throttle itself
        try:
            lambda_client.put_function_concurrency(
                FunctionName=fn_name,
                ReservedConcurrentExecutions=0
            )
            logger.info(f"[Lambda] Throttled: {fn_name}")
            throttled.append(fn_name)
        except Exception as e:
            logger.error(f"[Lambda] Could not throttle {fn_name}: {e}")

    return throttled


def lambda_handler(event, context):
    logger.info(f"[spend-guard] Triggered. Raw event: {json.dumps(event)}")

    results = {
        "ec2_stopped": [],
        "rds_stopped": [],
        "lambda_throttled": []
    }

    try:
        results["ec2_stopped"] = stop_ec2_instances()
    except Exception as e:
        logger.error(f"[EC2] Unexpected error: {e}")

    try:
        results["rds_stopped"] = stop_rds_instances()
    except Exception as e:
        logger.error(f"[RDS] Unexpected error: {e}")

    try:
        results["lambda_throttled"] = throttle_lambda_functions()
    except Exception as e:
        logger.error(f"[Lambda] Unexpected error: {e}")

    logger.info(f"[spend-guard] Complete. Summary: {json.dumps(results)}")
    return results
