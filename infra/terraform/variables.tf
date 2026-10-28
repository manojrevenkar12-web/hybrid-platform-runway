variable "aws_region" {
  type    = string
  default = "eu-central-1"
}

variable "vpc_cidr" {
  type    = string
  default = "10.60.0.0/16"
}

variable "availability_zones" {
  type    = list(string)
  default = ["eu-central-1a", "eu-central-1b"]
}

# On-premises sites that reach AWS over IPsec. CIDRs must not overlap the VPC.
variable "sites" {
  type = map(object({
    public_ip = string
    cidrs     = list(string)
  }))
  default = {
    hq      = { public_ip = "203.0.113.10", cidrs = ["10.10.0.0/16", "10.110.0.0/16"] }
    factory = { public_ip = "203.0.113.20", cidrs = ["10.20.0.0/16"] }
  }
  validation {
    condition     = alltrue([for s in values(var.sites) : can(cidrhost("${s.public_ip}/32", 0))])
    error_message = "every site needs a public IPv4 address"
  }
}

variable "backup_retention_days" {
  type        = number
  default     = 35
  description = "Object Lock (compliance mode) on the offsite copy of the Proxmox backups: nobody, root included, can delete them sooner."
  validation {
    condition     = var.backup_retention_days >= 14
    error_message = "keep offsite backups at least 14 days"
  }
}

variable "proxmox_endpoint" {
  type    = string
  default = "https://pve-hq.example:8006/"
}

variable "proxmox_api_token" {
  type      = string
  sensitive = true
  default   = "terraform@pve!ci=00000000-0000-0000-0000-000000000000"
}

# GPU nodes and the PCI addresses of their cards, for the passthrough mapping runway places VMs on.
variable "gpu_devices" {
  type = list(object({
    node = string
    path = string
    id   = string
  }))
  default = [
    { node = "pve-gpu-01", path = "0000:41:00.0", id = "10de:20b5" },
    { node = "pve-gpu-02", path = "0000:41:00.0", id = "10de:20b5" },
  ]
}
