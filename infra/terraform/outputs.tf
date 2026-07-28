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

output "postgresql_cluster_id" {
  description = "ID of the Managed PostgreSQL cluster"
  value       = yandex_mdb_postgresql_cluster.statera.id
}

output "postgresql_host_fqdn" {
  description = "FQDN of the PostgreSQL host"
  value       = yandex_mdb_postgresql_cluster.statera.host[0].fqdn
}

output "postgresql_port" {
  description = "PostgreSQL port"
  value       = 6432
}

output "postgresql_database" {
  description = "PostgreSQL database name"
  value       = "statera"
}

output "postgresql_user" {
  description = "PostgreSQL user name"
  value       = "statera"
}

output "postgresql_password" {
  description = "PostgreSQL user password"
  value       = random_password.postgres.result
  sensitive   = true
}
