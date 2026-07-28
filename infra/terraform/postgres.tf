resource "random_password" "postgres" {
  length  = 24
  special = false
}

resource "yandex_mdb_postgresql_cluster" "statera" {
  name                = "statera-postgresql"
  environment         = "PRODUCTION"
  network_id          = var.network_id
  security_group_ids  = [yandex_vpc_security_group.postgres.id]
  deletion_protection = false

  config {
    version = "17"
    resources {
      resource_preset_id = "s3-c2-m8"
      disk_type_id       = "network-ssd"
      disk_size          = 10
    }
  }

  host {
    zone             = var.zone
    subnet_id        = yandex_vpc_subnet.statera.id
    assign_public_ip = true
  }
}

resource "yandex_mdb_postgresql_user" "statera" {
  cluster_id = yandex_mdb_postgresql_cluster.statera.id
  name       = "statera"
  password   = random_password.postgres.result
}

resource "yandex_mdb_postgresql_database" "statera" {
  cluster_id = yandex_mdb_postgresql_cluster.statera.id
  name       = "statera"
  owner      = "statera"
}
