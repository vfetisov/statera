resource "yandex_vpc_subnet" "statera" {
  name           = "statera-subnet"
  description    = "Subnet for Statera project"
  zone           = var.zone
  v4_cidr_blocks = [var.subnet_cidr]
  network_id     = var.network_id
}

resource "yandex_vpc_security_group" "postgres" {
  name        = "statera-postgres-sg"
  description = "Security group for Statera PostgreSQL"
  network_id  = var.network_id

  egress {
    protocol       = "ANY"
    description    = "Allow all outbound IPv4 traffic"
    v4_cidr_blocks = ["0.0.0.0/0"]
    from_port      = -1
    to_port        = -1
  }

  ingress {
    description    = "Allow PostgreSQL from Statera servers"
    protocol       = "TCP"
    port           = 6432
    v4_cidr_blocks = var.postgres_allowed_cidrs
  }
}
