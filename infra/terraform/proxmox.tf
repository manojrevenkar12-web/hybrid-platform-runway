# Proxmox VE cluster-level configuration: pools, the GPU mapping, and a least-privilege identity
# for runway. VMs themselves are generated per wave by `runway generate`.

locals {
  pools = ["hq-core", "hq-business", "hq-lab", "factory-core", "factory-business", "gpu"]
  # what runway needs to create, import, start, stop and destroy VMs, and nothing more
  runway_privileges = [
    "Datastore.AllocateSpace", "Datastore.Audit",
    "Mapping.Use",
    "Pool.Audit",
    "SDN.Use",
    "Sys.Audit",
    "VM.Allocate", "VM.Audit", "VM.Config.CDROM", "VM.Config.CPU", "VM.Config.Cloudinit", "VM.Config.Disk",
    "VM.Config.HWType", "VM.Config.Memory", "VM.Config.Network", "VM.Config.Options", "VM.Monitor", "VM.PowerMgmt",
  ]
}

resource "proxmox_virtual_environment_pool" "site" {
  for_each = toset(local.pools)
  pool_id  = each.key
  comment  = "Managed by Terraform"
}

resource "proxmox_virtual_environment_hardware_mapping_pci" "gpu_a100" {
  name    = "gpu-a100"
  comment = "A100 cards for ML training; runway places passthrough VMs on these nodes"
  map = [for d in var.gpu_devices : {
    id   = d.id
    node = d.node
    path = d.path
  }]
}

resource "proxmox_virtual_environment_role" "runway" {
  role_id    = "RunwayMigrator"
  privileges = local.runway_privileges
}

resource "proxmox_virtual_environment_user" "runway" {
  user_id = "runway@pve"
  comment = "Migration service; API token only, no password login"
  enabled = true
}

resource "proxmox_virtual_environment_user_token" "runway" {
  user_id               = proxmox_virtual_environment_user.runway.user_id
  token_name            = "migrate"
  comment               = "Expires with the migration programme"
  expiration_date       = "2027-12-31T00:00:00Z"
  privileges_separation = true
}

resource "proxmox_virtual_environment_acl" "runway_token" {
  token_id  = proxmox_virtual_environment_user_token.runway.id
  role_id   = proxmox_virtual_environment_role.runway.role_id
  path      = "/"
  propagate = true
}

resource "proxmox_virtual_environment_acl" "runway_user" {
  user_id   = proxmox_virtual_environment_user.runway.user_id
  role_id   = proxmox_virtual_environment_role.runway.role_id
  path      = "/"
  propagate = true
}
