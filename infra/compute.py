"""ECS Fargate cluster running the Django web service behind an ALB, plus a
Celery worker service and a Celery Beat service sharing the same task image.
"""

import json

import pulumi
import pulumi_aws as aws

PROJECT = "merchant-review"


def build_compute(network: dict, db, redis, bucket, image: str, env: dict) -> dict:
    cluster = aws.ecs.Cluster(f"{PROJECT}-cluster")

    log_group = aws.cloudwatch.LogGroup(f"{PROJECT}-logs", retention_in_days=14)

    exec_role = aws.iam.Role(
        f"{PROJECT}-task-exec-role",
        assume_role_policy=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }
                ],
            }
        ),
    )
    aws.iam.RolePolicyAttachment(
        f"{PROJECT}-task-exec-policy",
        role=exec_role.name,
        policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
    )

    task_role = aws.iam.Role(
        f"{PROJECT}-task-role",
        assume_role_policy=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }
                ],
            }
        ),
    )
    aws.iam.RolePolicy(
        f"{PROJECT}-task-s3-policy",
        role=task_role.id,
        policy=bucket.arn.apply(
            lambda arn: json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
                            "Resource": [arn, f"{arn}/*"],
                        }
                    ],
                }
            )
        ),
    )

    def make_task_def(name: str, command: list[str] | None) -> aws.ecs.TaskDefinition:
        container = pulumi.Output.all(
            db.address, redis.cache_nodes[0].address, bucket.bucket, log_group.name
        ).apply(
            lambda args: json.dumps(
                [
                    {
                        "name": name,
                        "image": image,
                        "essential": True,
                        "environment": [
                            {"name": "POSTGRES_HOST", "value": args[0]},
                            {"name": "POSTGRES_PORT", "value": "5432"},
                            {"name": "POSTGRES_DB", "value": "merchantreview"},
                            {"name": "POSTGRES_USER", "value": "merchantreview"},
                            {"name": "REDIS_URL", "value": f"redis://{args[1]}:6379/0"},
                            {"name": "SNAPSHOT_BUCKET", "value": args[2]},
                            {"name": "DJANGO_DEBUG", "value": "False"},
                            *[{"name": k, "value": v} for k, v in env.items()],
                        ],
                        **({"command": command} if command else {}),
                        **(
                            {"portMappings": [{"containerPort": 8000, "protocol": "tcp"}]}
                            if name == "web"
                            else {}
                        ),
                        "logConfiguration": {
                            "logDriver": "awslogs",
                            "options": {
                                "awslogs-group": args[3],
                                "awslogs-region": "us-east-1",
                                "awslogs-stream-prefix": name,
                            },
                        },
                    }
                ]
            )
        )
        return aws.ecs.TaskDefinition(
            f"{PROJECT}-{name}-task",
            family=f"{PROJECT}-{name}",
            cpu="256",
            memory="512",
            network_mode="awsvpc",
            requires_compatibilities=["FARGATE"],
            execution_role_arn=exec_role.arn,
            task_role_arn=task_role.arn,
            container_definitions=container,
        )

    web_task = make_task_def("web", ["gunicorn", "merchantreview.wsgi:application", "-b", "0.0.0.0:8000"])
    worker_task = make_task_def("celery-worker", ["celery", "-A", "merchantreview", "worker", "-l", "info"])
    beat_task = make_task_def("celery-beat", ["celery", "-A", "merchantreview", "beat", "-l", "info"])

    alb = aws.lb.LoadBalancer(
        f"{PROJECT}-alb",
        load_balancer_type="application",
        security_groups=[network["app_sg"].id],
        subnets=[s.id for s in network["public_subnets"]],
    )

    target_group = aws.lb.TargetGroup(
        f"{PROJECT}-tg",
        port=8000,
        protocol="HTTP",
        vpc_id=network["vpc"].id,
        target_type="ip",
        health_check=aws.lb.TargetGroupHealthCheckArgs(path="/healthz/", interval=30),
    )

    listener = aws.lb.Listener(
        f"{PROJECT}-listener",
        load_balancer_arn=alb.arn,
        port=80,
        protocol="HTTP",
        default_actions=[
            aws.lb.ListenerDefaultActionArgs(type="forward", target_group_arn=target_group.arn)
        ],
    )

    web_service = aws.ecs.Service(
        f"{PROJECT}-web-service",
        cluster=cluster.arn,
        task_definition=web_task.arn,
        desired_count=1,
        launch_type="FARGATE",
        network_configuration=aws.ecs.ServiceNetworkConfigurationArgs(
            subnets=[s.id for s in network["public_subnets"]],
            security_groups=[network["app_sg"].id],
            assign_public_ip=True,
        ),
        load_balancers=[
            aws.ecs.ServiceLoadBalancerArgs(
                target_group_arn=target_group.arn, container_name="web", container_port=8000
            )
        ],
        opts=pulumi.ResourceOptions(depends_on=[listener]),
    )

    worker_service = aws.ecs.Service(
        f"{PROJECT}-worker-service",
        cluster=cluster.arn,
        task_definition=worker_task.arn,
        desired_count=1,
        launch_type="FARGATE",
        network_configuration=aws.ecs.ServiceNetworkConfigurationArgs(
            subnets=[s.id for s in network["public_subnets"]],
            security_groups=[network["app_sg"].id],
            assign_public_ip=True,
        ),
    )

    beat_service = aws.ecs.Service(
        f"{PROJECT}-beat-service",
        cluster=cluster.arn,
        task_definition=beat_task.arn,
        desired_count=1,
        launch_type="FARGATE",
        network_configuration=aws.ecs.ServiceNetworkConfigurationArgs(
            subnets=[s.id for s in network["public_subnets"]],
            security_groups=[network["app_sg"].id],
            assign_public_ip=True,
        ),
    )

    return {
        "cluster": cluster,
        "alb": alb,
        "target_group": target_group,
        "web_service": web_service,
        "worker_service": worker_service,
        "beat_service": beat_service,
    }
