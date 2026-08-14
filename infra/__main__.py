"""Pulumi entrypoint: wires network -> storage -> database -> compute.

Run locally against LocalStack:
    pulumi stack select local   # or: pulumi stack init local
    pulumi up

Same code targets real AWS with a `prod` stack (no LocalStack endpoint overrides).
"""

import pulumi
from compute import build_compute
from database import build_database
from network import build_network
from storage import build_storage
from vpn import build_vpn

config = pulumi.Config()
db_password = config.get_secret("dbPassword") or pulumi.Output.secret("merchantreview-dev-only")

network = build_network()
bucket = build_storage()
db = build_database(network["private_subnets"], network["db_sg"], db_password)
compute = build_compute(
    network=network,
    db=db["postgres"],
    redis=db["redis"],
    bucket=bucket,
    image=config.get("appImage") or "merchant-review-web:local",
    env={"GEMINI_API_KEY": config.get("geminiApiKey") or ""},
)
vpn = build_vpn(network["vpc"])

pulumi.export("bucket_name", bucket.bucket)
pulumi.export("db_endpoint", db["postgres"].endpoint)
pulumi.export("redis_endpoint", db["redis"].cache_nodes[0].address)
pulumi.export("alb_dns_name", compute["alb"].dns_name)
pulumi.export("ecs_cluster", compute["cluster"].name)
pulumi.export("vpn_connection_id", vpn["vpn_connection"].id)
pulumi.export("vpn_gateway_id", vpn["vpn_gateway"].id)
pulumi.export("office_cgw_id", vpn["customer_gateway"].id)
pulumi.export("app_sg_id", network["app_sg"].id)
pulumi.export("db_sg_id", network["db_sg"].id)
pulumi.export("public_route_table_id", network["public_route_table"].id)
pulumi.export("igw_id", network["igw"].id)
pulumi.export("target_group_arn", compute["target_group"].arn)
