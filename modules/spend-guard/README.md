# efps-spend-guard

**Module:** spend-guard
**Owner:** EasyFind Property Solutions
**Status:** Active
**Region:** ap-south-1 (Mumbai)

---

## What This Module Does

spend-guard is a cost protection automation. It watches your daily AWS spend and
automatically shuts down all running services the moment your bill crosses $5 in a single day.

You also get an email alert at the same time so you know it happened.

Think of it as a circuit breaker for your AWS bill.

---

## How It Works — A to Z

```
1. AWS Budgets monitors your daily spend continuously.

2. When actual daily spend crosses $5 (100% of the $5 daily budget):
   - AWS Budgets publishes a message to the SNS topic (efps-spend-guard-topic)

3. The SNS topic does two things simultaneously:
   a. Sends an email alert to zeidzakirhussain@gmail.com
   b. Triggers the Lambda function (efps-spend-guard-fn)

4. The Lambda function runs three actions in sequence:
   a. Stops all running EC2 instances
   b. Stops all available RDS instances and Aurora clusters
   c. Sets reserved concurrency to 0 on all Lambda functions (throttle to zero)
      - Skips itself so it can finish running

5. In parallel, the monthly budget (efps-spend-guard-monthly-budget) has a
   Budget Action that attaches an IAM deny policy to the Lambda role,
   blocking EC2/RDS/Lambda from being restarted until manually removed.

6. Everything is logged to CloudWatch under:
   /aws/lambda/efps-spend-guard-fn
```

---

## AWS Resources

| Resource | Name | Type |
|----------|------|------|
| Lambda function | `efps-spend-guard-fn` | AWS Lambda |
| SNS topic | `efps-spend-guard-topic` | Amazon SNS |
| Lambda execution role | `efps-spend-guard-lambda-role` | IAM Role |
| Budgets execution role | `efps-spend-guard-budgets-role` | IAM Role |
| IAM deny policy | `efps-spend-guard-deny-policy` | IAM Policy |
| Daily budget | `efps-spend-guard-daily-budget` | AWS Budgets |
| Monthly budget | `efps-spend-guard-monthly-budget` | AWS Budgets |

---

## IAM Permissions

### efps-spend-guard-lambda-role
Assumed by the Lambda function. Permissions defined in `iam/lambda-role-policy.json`.

| Permission | Why |
|------------|-----|
| ec2:DescribeInstances, ec2:StopInstances | To find and stop running EC2 instances |
| rds:DescribeDBInstances/Clusters, rds:StopDBInstance/Cluster | To find and stop RDS databases |
| lambda:ListFunctions, lambda:PutFunctionConcurrency | To throttle all Lambda functions to zero |
| logs:CreateLogGroup/Stream, logs:PutLogEvents | To write logs to CloudWatch |

### efps-spend-guard-budgets-role
Assumed by AWS Budgets to execute the Budget Action.

| Permission | Why |
|------------|-----|
| sns:Publish | To send the trigger message to efps-spend-guard-topic |

### efps-spend-guard-deny-policy
Applied automatically by the Budget Action when monthly spend exceeds $5.
Blocks EC2, RDS, and Lambda from being restarted until manually detached.

---

## Secrets

This module has no secrets. It operates entirely using IAM roles — no API keys,
no tokens, no passwords. AWS handles authentication internally.

Secrets Manager path reserved for future use: `efps/spend-guard/*`

---

## Environment Variables

See `.env.example` for all variables. No secrets are stored in environment variables.
All configuration is either hardcoded as constants in the Lambda or passed via IAM context.

---

## Logs & Debugging

All actions are logged to CloudWatch. To debug any issue:

1. Go to AWS Console > CloudWatch > Log Groups
2. Open `/aws/lambda/efps-spend-guard-fn`
3. Each log line is prefixed with the service it acted on:
   - `[EC2]` — EC2 related actions
   - `[RDS]` — RDS related actions
   - `[Lambda]` — Lambda throttle actions
   - `[spend-guard]` — trigger and summary logs

---

## How to Disable / Re-enable After a Hard Stop

### To re-enable services after a hard stop:

1. Remove the IAM deny policy from the Lambda role (if Budget Action fired):
   ```
   AWS Console > IAM > Roles > efps-spend-guard-lambda-role > Detach efps-spend-guard-deny-policy
   ```

2. Start EC2 instances manually from the EC2 console.

3. Start RDS instances manually from the RDS console.
   Note: RDS auto-restarts after 7 days even if stopped.

4. Remove Lambda throttle (concurrency = 0) for each function:
   ```
   AWS Console > Lambda > {function} > Configuration > Concurrency > Remove reserved concurrency
   ```

### To fully disable spend-guard:

Delete or disable the two budgets in AWS Budgets console. The Lambda and SNS
will remain but will never be triggered.

---

## File Structure

```
modules/spend-guard/
├── lambda/
│   └── lambda_function.py    # Lambda source code
├── iam/
│   ├── lambda-role-policy.json   # Permissions for the Lambda execution role
│   └── deny-policy.json          # Deny policy applied on budget breach
├── .env.example              # Environment variable keys (no values)
└── README.md                 # This file
```
