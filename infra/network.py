"""VPC, subnets, and security groups shared by every other stack module."""

import pulumi_aws as aws

PROJECT = "merchant-review"


def build_network() -> dict:
    vpc = aws.ec2.Vpc(
        f"{PROJECT}-vpc",
        cidr_block="10.20.0.0/16",
        enable_dns_hostnames=True,
        enable_dns_support=True,
        tags={"Name": f"{PROJECT}-vpc"},
    )

    igw = aws.ec2.InternetGateway(f"{PROJECT}-igw", vpc_id=vpc.id)

    public_route_table = aws.ec2.RouteTable(
        f"{PROJECT}-public-rt",
        vpc_id=vpc.id,
        routes=[
            aws.ec2.RouteTableRouteArgs(
                cidr_block="0.0.0.0/0",
                gateway_id=igw.id,
            )
        ],
    )

    azs = ["us-east-1a", "us-east-1b"]
    public_subnets = []
    private_subnets = []

    for i, az in enumerate(azs):
        pub = aws.ec2.Subnet(
            f"{PROJECT}-public-{i}",
            vpc_id=vpc.id,
            cidr_block=f"10.20.{i}.0/24",
            availability_zone=az,
            map_public_ip_on_launch=True,
            tags={"Name": f"{PROJECT}-public-{i}"},
        )
        aws.ec2.RouteTableAssociation(
            f"{PROJECT}-public-rta-{i}", subnet_id=pub.id, route_table_id=public_route_table.id
        )
        public_subnets.append(pub)

        priv = aws.ec2.Subnet(
            f"{PROJECT}-private-{i}",
            vpc_id=vpc.id,
            cidr_block=f"10.20.{i + 10}.0/24",
            availability_zone=az,
            tags={"Name": f"{PROJECT}-private-{i}"},
        )
        private_subnets.append(priv)

    app_sg = aws.ec2.SecurityGroup(
        f"{PROJECT}-app-sg",
        vpc_id=vpc.id,
        description="ECS tasks: allow inbound HTTP from the ALB, all egress",
        ingress=[
            aws.ec2.SecurityGroupIngressArgs(
                protocol="tcp", from_port=8000, to_port=8000, cidr_blocks=["0.0.0.0/0"]
            )
        ],
        egress=[
            aws.ec2.SecurityGroupEgressArgs(
                protocol="-1", from_port=0, to_port=0, cidr_blocks=["0.0.0.0/0"]
            )
        ],
    )

    db_sg = aws.ec2.SecurityGroup(
        f"{PROJECT}-db-sg",
        vpc_id=vpc.id,
        description="RDS + ElastiCache: allow inbound from app tasks only",
        ingress=[
            aws.ec2.SecurityGroupIngressArgs(
                protocol="tcp", from_port=5432, to_port=5432, security_groups=[app_sg.id]
            ),
            aws.ec2.SecurityGroupIngressArgs(
                protocol="tcp", from_port=6379, to_port=6379, security_groups=[app_sg.id]
            ),
        ],
        egress=[
            aws.ec2.SecurityGroupEgressArgs(
                protocol="-1", from_port=0, to_port=0, cidr_blocks=["0.0.0.0/0"]
            )
        ],
    )

    return {
        "vpc": vpc,
        "igw": igw,
        "public_route_table": public_route_table,
        "public_subnets": public_subnets,
        "private_subnets": private_subnets,
        "app_sg": app_sg,
        "db_sg": db_sg,
    }
