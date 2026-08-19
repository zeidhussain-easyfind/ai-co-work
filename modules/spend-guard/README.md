# efps-spend-guard

**Module:** spend-guard
**Owner:** EasyFind Property Solutions
**Status:** Active
**Region:** ap-south-1 (Mumbai) / us-east-1 (billing alarms only)

---

## What This Module Does

spend-guard is a cost protection automation. It watches your AWS estimated charges
and the moment they hit $4, two things happen simultaneously:

1. You get an email at zeidzakirhussain@gmail.com
2. All running services are stopped immediately — EC2, RDS, and Lambda

Every spend event (any amount, even $0.01) is logged to CloudWatch so there
is a full audit trail of every dollar spent.

Services stay stopped until you manually say otherwise. Nothing restarts automatically.

---

## How It Works — A to Z

```
1. CloudWatch monitors AWS/Billing EstimatedCharges continuously.

2. On every spend event (any amount):
   - The alarm state reason is logged to CloudWatch
   - This gives a full audit trail of all spend

3. When estimated charges hit $4:
   - CloudWatch alarm (efps-spend-guard-4usd-alert) fires
   - Publishes to efps-spend-guard-billing-topic (us-east-1)

4. The billing SNS topic does two things simultaneously:
   a. Sends an email alert to zeidzakirhussain@gmail.com
   b. Triggers the Lambda function (efps-spend-guard-fn)

5. The Lambda function runs three actions in sequence:
   a. Stops all running EC2 instances
   b. Stops all available RDS instances and Aurora clusters
   c. Sets reserved concurrency to 0 on all Lambda functions (throttle to zero)
      - Skips itself so it can finish running

6. The daily budget (efps-spend-guard-daily-budget) also fires at $4
   as a secondary safety net via efps-spend-guard-topic (ap-south-1).

7. The monthly budget (efps-spend-guard-monthly-budget) has a Budget Action
   that attaches an IAM deny policy — blocks services from being restarted.

8. Everything is logged to CloudWatch:
   /aws/lambda/efps-spend-guard-fn
```

---

## AWS Resources

| Resource | Name | Region |
|----------|------|--------|
| Lambda function | `efps-spend-guard-fn` | ap-south-1 |
| SNS topic (hard stop) | `efps-spend-guard-topic` | ap-south-1 |
| SNS topic (billing alarms) | `efps-spend-guard-billing-topic` | us-east-1 |
| Lambda IAM role | `efps-spend-guard-lambda-role` | global |
| Budgets IAM role | `efps-spend-guard-budgets-role` | global |
| IAM deny policy | `efps-spend-guard-deny-policy` | global |
| Daily budget | `efps-spend-guard-daily-budget` | us-east-1 |
| Monthly budget | `efps-spend-guard-monthly-budget` | us-east-1 |
| CloudWatch alarm | `efps-spend-guard-4usd-alert` | us-east-1 |

---

## Thresholds

| Amount | What Happens |
|--------|-------------|
| Any spend | Logged to CloudWatch with alarm name and amount |
| $4 | Email to zeidzakirhussain@gmail.com + hard stop all services |

---

## IAM Permissions

### efps-spend-guard-lambda-role
Assumed by the Lambda function. Defined in `iam/lambda-role-policy.json`.

| Permission | Why |
|------------|-----|
| ec2:DescribeInstances, ec2:StopInstances | Find and stop running EC2 instances |
| rds:DescribeDBInstances/Clusters, rds:StopDBInstance/Cluster | Find and stop RDS databases |
| lambda:ListFunctions, lambda:PutFunctionConcurrency | Throttle all Lambda functions to zero |
| logs:CreateLogGroup/Stream, logs:PutLogEvents | Write logs to CloudWatch |

### efps-spend-guard-budgets-role
Assumed by AWS Budgets for the Budget Action.

| Permission | Why |
|------------|-----|
| sns:Publish | Send trigger to efps-spend-guard-topic |

### efps-spend-guard-deny-policy
Applied by Budget Action when monthly spend exceeds $4.
Blocks EC2, RDS, Lambda from being restarted until manually detached.

---

## Secrets

This module has no secrets. It uses IAM roles exclusively.

Secrets Manager path reserved for future use: `efps/spend-guard/*`

---

## Logs and Debugging

All actions logged to CloudWatch at `/aws/lambda/efps-spend-guard-fn`.

Log line prefixes:
- `[spend-guard]` — trigger, spend amount, and summary
- `[EC2]` — EC2 stop actions
- `[RDS]` — RDS stop actions
- `[Lambda]` — Lambda throttle actions

To debug any issue:
1. AWS Console > CloudWatch > Log Groups
2. Open `/aws/lambda/efps-spend-guard-fn`
3. Find the relevant invocation and read top-to-bottom

---

## How to Re-enable Services After a Hard Stop

Services will NOT restart on their own. Zeid must manually re-enable.

**1. Remove IAM deny policy (if Budget Action fired):**
```
AWS Console > IAM > Roles > efps-spend-guard-lambda-role > Detach efps-spend-guard-deny-policy
```

**2. Start EC2 instances:**
```
AWS Console > EC2 > Instances > Select > Start
```

**3. Start RDS instances:**
```
AWS Console > RDS > Databases > Select > Start
Note: RDS auto-restarts after 7 days even if stopped.
```

**4. Remove Lambda throttle (do this for each function):**
```
AWS Console > Lambda > {function} > Configuration > Concurrency > Remove reserved concurrency
```

---

## How to Fully Disable spend-guard

Delete or disable the budgets and CloudWatch alarm in AWS console.
The Lambda and SNS topics will remain but will never be triggered.

---

## File Structure

```
modules/spend-guard/
├── lambda/
│   └── lambda_function.py        # Lambda source code
├── iam/
│   ├── lambda-role-policy.json   # Lambda execution role permissions
│   └── deny-policy.json          # Deny policy applied on budget breach
├── .env.example                  # Environment variable keys (no values)
└── README.md                     # This file
```
