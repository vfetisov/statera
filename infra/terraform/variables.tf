variable "cloud_id" {
  description = "Yandex Cloud ID"
  type        = string
}

variable "folder_id" {
  description = "Yandex Cloud Folder ID"
  type        = string
}

variable "zone" {
  description = "Yandex Cloud default availability zone"
  type        = string
}

variable "service_account_key_file" {
  description = "Path to the service account JSON key file"
  type        = string
}

variable "subnet_cidr" {
  description = "CIDR block for the Statera subnet"
  type        = string
  default     = "10.10.0.0/24"
}

variable "network_id" {
  description = "Existing Yandex VPC network ID for Statera"
  type        = string
}
