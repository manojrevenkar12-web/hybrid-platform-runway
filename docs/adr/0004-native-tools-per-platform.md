# 0004: Each platform with the tool its operators already use

Status: accepted

- **Terraform** for AWS and for Proxmox cluster configuration (bpg/proxmox: pools, PCI mappings,
  roles and tokens) and for the VMs runway generates. One state per wave keeps blast radius small.
- **Bicep** for the Azure hub: Azure-native, no state file, linted with the Bicep analyzers.
- **Ansible** for what happens inside operating systems and on Proxmox nodes (networking), tested
  with Molecule on the two distributions in use (RHEL-family and Debian).
- **Argo CD** for what runs on OpenShift and Kubernetes; **GitLab CI** builds, scans and promotes by
  changing Git, never by running kubectl against a cluster.

Manual configuration is a bug: drift between generated code and Proxmox is reported per VM and field.
