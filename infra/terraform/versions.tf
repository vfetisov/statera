terraform {
  required_version = ">= 1.8"

  required_providers {
    yandex = {
      source  = "yandex-cloud/yandex"
      version = "~> 0.140"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.6"
    }
  }
}
