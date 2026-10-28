output "vpn_tunnels" {
  value = { for k, v in aws_vpn_connection.site : k => [v.tunnel1_address, v.tunnel2_address] }
}

output "backup_bucket" {
  value = aws_s3_bucket.backup.bucket
}
