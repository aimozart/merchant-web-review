"""S3 bucket for web-presence snapshots (screenshots, scraped HTML, LLM analysis JSON)."""

import pulumi_aws as aws

PROJECT = "merchant-review"


def build_storage() -> aws.s3.BucketV2:
    bucket = aws.s3.BucketV2(f"{PROJECT}-snapshots", bucket="merchant-review-snapshots")

    aws.s3.BucketVersioningV2(
        f"{PROJECT}-snapshots-versioning",
        bucket=bucket.id,
        versioning_configuration=aws.s3.BucketVersioningV2VersioningConfigurationArgs(
            status="Enabled"
        ),
    )

    aws.s3.BucketLifecycleConfigurationV2(
        f"{PROJECT}-snapshots-lifecycle",
        bucket=bucket.id,
        rules=[
            aws.s3.BucketLifecycleConfigurationV2RuleArgs(
                id="expire-old-snapshot-versions",
                status="Enabled",
                noncurrent_version_expiration=aws.s3.BucketLifecycleConfigurationV2RuleNoncurrentVersionExpirationArgs(
                    noncurrent_days=90
                ),
            )
        ],
    )

    return bucket
