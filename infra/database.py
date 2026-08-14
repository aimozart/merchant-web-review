"""RDS Postgres for application data + ElastiCache Redis for the Celery broker/cache."""

import pulumi
import pulumi_aws as aws

PROJECT = "merchant-review"


def build_database(private_subnets, db_sg, db_password: pulumi.Output) -> dict:
    db_subnet_group = aws.rds.SubnetGroup(
        f"{PROJECT}-db-subnets",
        subnet_ids=[s.id for s in private_subnets],
    )

    postgres = aws.rds.Instance(
        f"{PROJECT}-postgres",
        engine="postgres",
        engine_version="16",
        instance_class="db.t3.micro",
        allocated_storage=20,
        db_name="merchantreview",
        username="merchantreview",
        password=db_password,
        db_subnet_group_name=db_subnet_group.name,
        vpc_security_group_ids=[db_sg.id],
        skip_final_snapshot=True,
        publicly_accessible=False,
    )

    cache_subnet_group = aws.elasticache.SubnetGroup(
        f"{PROJECT}-cache-subnets",
        subnet_ids=[s.id for s in private_subnets],
    )

    redis = aws.elasticache.Cluster(
        f"{PROJECT}-redis",
        engine="redis",
        engine_version="7.0",
        node_type="cache.t3.micro",
        num_cache_nodes=1,
        subnet_group_name=cache_subnet_group.name,
        security_group_ids=[db_sg.id],
    )

    return {"postgres": postgres, "redis": redis}
