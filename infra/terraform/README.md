# Statera — Terraform

This directory contains Terraform configuration for deploying infrastructure to **Yandex Cloud**.

## Prerequisites

- [Terraform](https://www.terraform.io/downloads) >= 1.8
- A Yandex Cloud billing account
- A Yandex Cloud Service Account with the required roles

## Installing Terraform

1. Download Terraform from the [official website](https://www.terraform.io/downloads).
2. Extract the binary and add it to your `PATH`.
3. Verify the installation:

   ```bash
   terraform version
   ```

## Creating a Service Account

1. Open the [Yandex Cloud Console](https://console.cloud.yandex.com).
2. Navigate to **IAM & Access Control → Service Accounts**.
3. Click **Create Service Account**, give it a name, and assign the required roles.
4. After creation, select the service account and click **Create API Key** → **Create Authorized Key**.
5. Download the JSON key file.

## Placing the SA Key Locally

Place the downloaded JSON key file in this directory (or another secure location) and note the path.

For example:

```bash
cp ~/Downloads/service-account-key.json ./key.json
```

## Copying `terraform.tfvars.example`

```bash
cp terraform.tfvars.example terraform.tfvars
```

Then edit `terraform.tfvars` and fill in your actual values:

- `cloud_id` — your Yandex Cloud ID
- `folder_id` — your Yandex Cloud Folder ID
- `zone` — the default availability zone (e.g., `ru-central1-a`)
- `service_account_key_file` — path to the downloaded JSON key file

## Initialising Terraform

```bash
terraform init
```

## Validating the Configuration

```bash
terraform validate
```

## Network Resources

The configuration creates the following network resources:

- **VPC Network** (`statera-network`) — the base VPC for the Statera project.
- **Subnet** (`statera-subnet`) — a single subnet in the zone defined by `var.zone` with the CIDR block from `var.subnet_cidr` (default: `10.10.0.0/24`).
- **Security Group** (`statera-postgres-sg`) — a security group for PostgreSQL with a default egress rule allowing all outbound IPv4 traffic. Inbound PostgreSQL rules will be added later.

## Previewing Infrastructure Changes

```bash
terraform plan
```
