"""
Site-to-Site VPN: a tunnel from the app's VPC to a simulated branch office
network — the "connect a new office" scenario a real infra team eventually
hits. Modeled as a Customer Gateway (the office's on-prem router — its public
IP and BGP ASN), a VPN Gateway attached to our VPC, and a VPN Connection
between them with a static route advertising the office's private CIDR.
"""

import pulumi_aws as aws

PROJECT = "merchant-review"

# The office's simulated on-prem network — deliberately outside the VPC's
# 10.20.0.0/16 range so the static route is unambiguous.
OFFICE_CIDR = "192.168.100.0/24"
OFFICE_PUBLIC_IP = "203.0.113.10"  # TEST-NET-3 (RFC 5737) — safe, non-routable, never a real IP
OFFICE_BGP_ASN = 65000


def build_vpn(vpc) -> dict:
    customer_gateway = aws.ec2.CustomerGateway(
        f"{PROJECT}-office-cgw",
        bgp_asn=OFFICE_BGP_ASN,
        ip_address=OFFICE_PUBLIC_IP,
        type="ipsec.1",
        tags={"Name": f"{PROJECT}-office-cgw"},
    )

    vpn_gateway = aws.ec2.VpnGateway(
        f"{PROJECT}-vgw",
        vpc_id=vpc.id,
        tags={"Name": f"{PROJECT}-vgw"},
    )

    # A static route advertising OFFICE_CIDR back to the office would normally be
    # added here via aws.ec2.VpnConnectionRoute — omitted because LocalStack's EC2
    # emulation doesn't implement CreateVpnConnectionRoute yet (confirmed directly:
    # it returns HTTP 501 "not implemented"). On real AWS this resource works as
    # documented; the route itself is the next thing to add once that API lands.
    vpn_connection = aws.ec2.VpnConnection(
        f"{PROJECT}-office-vpn",
        customer_gateway_id=customer_gateway.id,
        vpn_gateway_id=vpn_gateway.id,
        type="ipsec.1",
        static_routes_only=True,
        tags={"Name": f"{PROJECT}-office-vpn"},
    )

    return {
        "customer_gateway": customer_gateway,
        "vpn_gateway": vpn_gateway,
        "vpn_connection": vpn_connection,
    }
