# Tests with mocked providers: no credentials, no cost, nothing created. `apply` against mocks
# fills in computed values (ARNs, policies) so the assertions can read them.
mock_provider "aws" {
  # the AWS provider checks ARN formats, so the mocks hand out well-formed ones
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:eu-central-1:123456789012:log-group:/hybrid/vpc-flow" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/hybrid-vpc-flow-logs" }
  }
  mock_resource "aws_kms_key" {
    defaults = { arn = "arn:aws:kms:eu-central-1:123456789012:key/11111111-2222-3333-4444-555555555555" }
  }
  mock_resource "aws_s3_bucket" {
    defaults = { arn = "arn:aws:s3:::pve-offsite-test", id = "pve-offsite-test", bucket = "pve-offsite-test" }
  }
  mock_resource "aws_iam_policy" {
    defaults = { arn = "arn:aws:iam::123456789012:policy/pve-offsite-sync" }
  }
}
mock_provider "proxmox" {}

run "security_decisions" {
  command = apply

  assert {
    condition     = alltrue([for v in aws_vpn_connection.site : contains(v.tunnel1_ike_versions, "ikev2") && length(v.tunnel1_ike_versions) == 1 && contains(v.tunnel2_ike_versions, "ikev2") && length(v.tunnel2_ike_versions) == 1 && contains(v.tunnel1_phase1_dh_group_numbers, 20) && v.static_routes_only])
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
