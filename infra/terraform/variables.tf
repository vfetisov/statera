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
