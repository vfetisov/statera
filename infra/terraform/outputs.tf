output "network_id" {
  description = "Existing VPC network ID used by Statera"
  value       = var.network_id
}

output "subnet_id" {
  description = "ID of the Statera subnet"
  value       = yandex_vpc_subnet.statera.id
}

output "postgres_security_group_id" {
  description = "ID of the security group for PostgreSQL"
  value       = yandex_vpc_security_group.postgres.id
}
