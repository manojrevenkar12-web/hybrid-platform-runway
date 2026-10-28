# Plan-only tests with mocked providers: no credentials, no cost. They pin the decisions that
# must not drift.
mock_provider "aws" {}
mock_provider "proxmox" {}

run "security_decisions" {
  command = plan

  assert {
    condition = alltrue([for v in aws_vpn_connection.site : (
      v.tunnel1_ike_versions = = toset(["ikev2"]) && v.tunnel2_ike_versions == toset(["ikev2"]) &&
      contains(v.tunnel1_phase1_dh_group_numbers, 20) && v.static_routes_only
    )])
    error_message = "every tunnel is IKEv2 with DH group 20 and static routes"
  }
  assert {
    condition     = length(aws_vpn_connection_route.site) == 3
    error_message = "one route per site CIDR"
  }
  assert {
    condition     = aws_s3_bucket.backup.object_lock_enabled && aws_s3_bucket_object_lock_configuration.backup.rule[0].default_retention[0].mode == "COMPLIANCE"
    error_message = "offsite backups are immutable (Object Lock, compliance mode)"
  }
  assert {
    condition     = aws_s3_bucket_public_access_block.backup.block_public_acls && aws_s3_bucket_public_access_block.backup.restrict_public_buckets
    error_message = "the backup bucket is never public"
  }
  assert {
    condition     = !strcontains(aws_iam_policy.pbs.policy, "DeleteObject") && !strcontains(aws_iam_policy.pbs.policy, "PutBucket")
    error_message = "the backup server cannot delete backups or change the bucket"
  }
  assert {
    condition     = length(setintersection(toset(proxmox_virtual_environment_role.runway.privileges), toset(["Sys.Modify", "Permissions.Modify", "Realm.Allocate", "User.Modify"]))) == 0
    error_message = "runway may manage VMs, not the cluster or its users"
  }
  assert {
    condition     = proxmox_virtual_environment_user_token.runway.privileges_separation
    error_message = "the token carries only the privileges granted to it"
  }
  assert {
    condition     = length(proxmox_virtual_environment_hardware_mapping_pci.gpu_a100.map) == 2
    error_message = "both GPU nodes are in the mapping"
  }
}

run "short_retention_is_rejected" {
  command = plan
  variables {
    backup_retention_days = 7
  }
  expect_failures = [var.backup_retention_days]
}
