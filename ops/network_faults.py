"""
Tier 3 fault-injection registry: real networking, in the Pulumi/AWS layer
(verified against LocalStack).

Unlike Tiers 1-2, these faults don't touch Django models or Docker containers —
they simulate **infrastructure drift**: someone hand-edits a real AWS resource
(security group, route table, load balancer target group) directly via the
console or CLI, bypassing Pulumi entirely. The infrastructure now disagrees with
the code that's supposed to define it. This is one of the most common real
categories of infra incident, and the fix is a genuine skill: recognize drift,
then either reconcile it by re-running `pulumi up` (which restores the
Pulumi-defined state) or patch it directly and understand why that's the
worse choice long-term (it works until the next `pulumi up` silently reverts
your manual patch, which is itself a lesson worth having explicitly).

Every check_resolved function queries the *actual* AWS API state (via
LocalStack), never Pulumi's own state file — the point is verifying reality,
the same as Tiers 1-2.
"""
from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import boto3

from ops.models import Ticket

INFRA_DIR = Path(__file__).resolve().parent.parent / "infra"
LOCALSTACK_ENDPOINT = "http://localhost:4566"


def _client(service: str):
    return boto3.client(
        service,
        endpoint_url=LOCALSTACK_ENDPOINT,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )


def _pulumi_output(key: str) -> str:
    result = subprocess.run(
        ["pulumi", "stack", "output", key, "--non-interactive"],
        cwd=INFRA_DIR,
        capture_output=True,
        text=True,
        env={**os.environ, "PULUMI_CONFIG_PASSPHRASE": ""},
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Couldn't read Pulumi output {key!r} — has `pulumi up` been run in {INFRA_DIR}? "
            f"{result.stderr.strip()}"
        )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# 1. Security group drift — the DB security group's ingress rule allowing the
#    app tier to reach Postgres gets revoked directly via the AWS API.
# ---------------------------------------------------------------------------

def _inject_sg_drift() -> dict:
    ec2 = _client("ec2")
    db_sg_id = _pulumi_output("db_sg_id")
    app_sg_id = _pulumi_output("app_sg_id")
    ec2.revoke_security_group_ingress(
        GroupId=db_sg_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 5432,
                "ToPort": 5432,
                "UserIdGroupPairs": [{"GroupId": app_sg_id}],
            }
        ],
    )
    return {}


def _check_sg_drift(ticket: Ticket) -> bool:
    ec2 = _client("ec2")
    db_sg_id = _pulumi_output("db_sg_id")
    app_sg_id = _pulumi_output("app_sg_id")
    sg = ec2.describe_security_groups(GroupIds=[db_sg_id])["SecurityGroups"][0]
    for perm in sg.get("IpPermissions", []):
        if perm.get("FromPort") == 5432 and perm.get("ToPort") == 5432:
            if any(pair.get("GroupId") == app_sg_id for pair in perm.get("UserIdGroupPairs", [])):
                return True
    return False


# ---------------------------------------------------------------------------
# 2. Route table drift — the public subnets' default route to the internet
#    gateway gets deleted directly.
# ---------------------------------------------------------------------------

def _inject_route_drift() -> dict:
    ec2 = _client("ec2")
    rtb_id = _pulumi_output("public_route_table_id")
    ec2.delete_route(RouteTableId=rtb_id, DestinationCidrBlock="0.0.0.0/0")
    return {}


def _check_route_drift(ticket: Ticket) -> bool:
    ec2 = _client("ec2")
    rtb_id = _pulumi_output("public_route_table_id")
    igw_id = _pulumi_output("igw_id")
    rtb = ec2.describe_route_tables(RouteTableIds=[rtb_id])["RouteTables"][0]
    for route in rtb.get("Routes", []):
        if route.get("DestinationCidrBlock") == "0.0.0.0/0" and route.get("GatewayId") == igw_id:
            return True
    return False


# ---------------------------------------------------------------------------
# 3. Load balancer target group drift — the health check path gets changed to
#    something the app doesn't actually serve, simulating a "quick console
#    tweak" that would make every ECS task look permanently unhealthy.
# ---------------------------------------------------------------------------

EXPECTED_HEALTH_CHECK_PATH = "/healthz/"


def _inject_health_check_drift() -> dict:
    elbv2 = _client("elbv2")
    tg_arn = _pulumi_output("target_group_arn")
    elbv2.modify_target_group(TargetGroupArn=tg_arn, HealthCheckPath="/wrong-path-does-not-exist/")
    return {}


def _check_health_check_drift(ticket: Ticket) -> bool:
    elbv2 = _client("elbv2")
    tg_arn = _pulumi_output("target_group_arn")
    tg = elbv2.describe_target_groups(TargetGroupArns=[tg_arn])["TargetGroups"][0]
    return tg.get("HealthCheckPath") == EXPECTED_HEALTH_CHECK_PATH


# ---------------------------------------------------------------------------
# 4. VPN connection deleted out-of-band — the whole site-to-site tunnel to the
#    branch office gets torn down directly, as if someone assumed it was
#    unused and deleted it in the console. Pulumi's own state still thinks it
#    should exist, which is exactly the scenario `pulumi up` is meant to catch
#    and reconcile.
# ---------------------------------------------------------------------------

def _inject_vpn_deleted() -> dict:
    ec2 = _client("ec2")
    vpn_id = _pulumi_output("vpn_connection_id")
    ec2.delete_vpn_connection(VpnConnectionId=vpn_id)
    return {}


def _check_vpn_deleted(ticket: Ticket) -> bool:
    ec2 = _client("ec2")
    try:
        vpn_id = _pulumi_output("vpn_connection_id")
    except RuntimeError:
        return False
    conns = ec2.describe_vpn_connections(VpnConnectionIds=[vpn_id])["VpnConnections"]
    return bool(conns) and conns[0]["State"] not in ("deleted", "deleting")


@dataclass
class NetworkFaultDefinition:
    key: str
    title: str
    description: str
    priority: str
    category: str
    real_cause: str
    fix_hint: str
    inject: Callable[[], dict]
    check_resolved: Callable[[Ticket], bool]


NETWORK_FAULTS: dict[str, NetworkFaultDefinition] = {
    "sg_drift": NetworkFaultDefinition(
        key="sg_drift",
        title="Database security group looks different from what's in code",
        description=(
            "A teammate mentions they made a 'quick fix' in the AWS console on the database "
            "security group earlier today. Worth confirming it still matches what Pulumi thinks "
            "it manages before this causes a connectivity surprise during the next deploy."
        ),
        priority="high",
        category="infra",
        real_cause=(
            "The ingress rule allowing the app tier's security group to reach Postgres on "
            "5432 was revoked directly via the AWS API, bypassing Pulumi entirely — classic "
            "infrastructure drift."
        ),
        fix_hint=(
            "Compare live state to code: `aws ec2 describe-security-groups` (via awslocal) vs. "
            "`infra/network.py`. `pulumi up` alone may report no changes here — inline security "
            "group rules aren't always re-checked against live state on a plain apply. Run "
            "`pulumi refresh` first (it will show the drift explicitly), then `pulumi up` to "
            "reconcile. (Manually re-adding the rule with `aws ec2 authorize-security-group-"
            "ingress` also passes verification, but doesn't fix the root cause: the environment "
            "is still not sourced from code.)"
        ),
        inject=_inject_sg_drift,
        check_resolved=_check_sg_drift,
    ),
    "route_drift": NetworkFaultDefinition(
        key="route_drift",
        title="ECS tasks in public subnets can't reach the internet",
        description=(
            "Tasks in the public subnets are failing to pull container images and can't reach "
            "any external endpoint, but the subnets, VPC, and internet gateway all still show "
            "as present and attached."
        ),
        priority="critical",
        category="infra",
        real_cause=(
            "The public route table's default route (0.0.0.0/0 -> Internet Gateway) was "
            "deleted directly — the IGW is still attached to the VPC, but nothing routes to it "
            "anymore, which is why 'is the IGW attached?' alone doesn't catch this."
        ),
        fix_hint=(
            "`aws ec2 describe-route-tables` on the public route table — is there a 0.0.0.0/0 "
            "route at all? Re-run `pulumi up` to restore it, or `aws ec2 create-route "
            "--destination-cidr-block 0.0.0.0/0 --gateway-id <igw-id>` directly."
        ),
        inject=_inject_route_drift,
        check_resolved=_check_route_drift,
    ),
    "health_check_drift": NetworkFaultDefinition(
        key="health_check_drift",
        title="ECS service shows tasks cycling as unhealthy",
        description=(
            "New tasks keep starting and getting killed shortly after — the ECS service never "
            "settles at its desired count. The application itself isn't throwing errors in its "
            "own logs."
        ),
        priority="high",
        category="infra",
        real_cause=(
            "The ALB target group's health check path was changed to a path the app doesn't "
            "serve, directly via the AWS API — every task fails its health check and gets "
            "cycled, even though the app itself is completely fine."
        ),
        fix_hint=(
            "`aws elbv2 describe-target-groups` — check `HealthCheckPath` against what the app "
            "actually serves (`/healthz/`). Fix via `pulumi up` or `aws elbv2 "
            "modify-target-group --health-check-path /healthz/`."
        ),
        inject=_inject_health_check_drift,
        check_resolved=_check_health_check_drift,
    ),
    "vpn_deleted": NetworkFaultDefinition(
        key="vpn_deleted",
        title="Branch office reports the site-to-site VPN is completely down",
        description=(
            "The office network team says their tunnel shows no connection at all — not "
            "degraded, just gone. They confirm nothing changed on their end."
        ),
        priority="critical",
        category="infra",
        real_cause=(
            "The VPN Connection was deleted directly via the AWS API, as if someone in the "
            "console assumed it was unused infrastructure and tore it down — Pulumi's own "
            "state still expects it to exist."
        ),
        fix_hint=(
            "`aws ec2 describe-vpn-connections` — confirm it's actually gone, not just "
            "degraded. Since Pulumi's state still declares this resource, `pulumi up` from "
            "`infra/` should detect the drift and recreate it. If Pulumi doesn't pick it up "
            "immediately, `pulumi refresh` first, then `pulumi up`."
        ),
        inject=_inject_vpn_deleted,
        check_resolved=_check_vpn_deleted,
    ),
}


def inject_random_network_fault() -> Ticket:
    import random

    return inject_network_fault(random.choice(list(NETWORK_FAULTS)))


def inject_network_fault(key: str) -> Ticket:
    fault = NETWORK_FAULTS[key]
    ticket = Ticket.objects.create(
        title=fault.title,
        description=fault.description,
        priority=fault.priority,
        category=fault.category,
        source="fault_injection",
        fault_key=fault.key,
    )
    fault.inject()
    return ticket


def verify_network_fix(ticket: Ticket) -> bool:
    from django.utils import timezone

    fault = NETWORK_FAULTS.get(ticket.fault_key)
    if fault is None:
        return False
    resolved = fault.check_resolved(ticket)
    if resolved and ticket.status not in ("resolved", "closed"):
        ticket.status = "resolved"
        ticket.resolved_at = timezone.now()
        ticket.save(update_fields=["status", "resolved_at"])
    return resolved
