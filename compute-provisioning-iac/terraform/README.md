# Terraform Infrastructure as Code

This repository contains Terraform configurations for managing GCP infrastructure across multiple environments.

## Table of Contents

- [Folder Structure](#folder-structure)
- [Prerequisites](#prerequisites)
- [Terraform Installation and Setup](#terraform-installation-and-setup)
- [Initial Setup with Remote State](#initial-setup-with-remote-state)
- [Normal Operations](#normal-operations)
- [Adding New Modules](#adding-new-modules)
- [Best Practices](#best-practices)

## Folder Structure

```
terraform/
├── common/
│   └── modules/              # Reusable Terraform modules
│       ├── agent_github/
│       ├── agent_storage/
│       ├── ansible_image_storage/
│       ├── artifact_registry/
│       ├── cicd_setup/
│       ├── general_setup/
│       └── ...
├── sandbox/                  # Development environment
│   ├── backend.tf            # Backend configuration (GCS)
│   ├── main.tf               # Main configuration
│   ├── providers.tf          # Provider configuration
│   ├── variables.tf          # Variable definitions
│   ├── terraform.tfvars      # Variable values
│   └── outputs.tf            # Output definitions
├── staging/                  # Staging environment
│   ├── backend.tf
│   ├── main.tf
│   ├── providers.tf
│   ├── variables.tf
│   ├── terraform.tfvars
│   └── outputs.tf
├── terraform.tfvars.template # TFVars template
└── README.md                 # This file
```

### Directory Purposes

- **`terraform/common/modules/`**: Contains reusable Terraform modules that can be shared across environments. Each module is self-contained with its own `main.tf`, `variables.tf`, and `outputs.tf`.

- **`terraform/<environment>/`**: Environment-specific configurations (e.g., `sandbox`, `staging`, `production`). Each environment has its own state file and configuration.

## Prerequisites

- **GCP Account**: Access to a Google Cloud Platform project
- **GCP CLI (`gcloud`)**: Installed and authenticated
- **Terraform**: Version >= 1.0.0
- **Appropriate IAM Permissions**: To create and manage GCP resources

## Setup

### Prerequisites
* Terraform CLI installed
* `gcloud` CLI set up


### 1. Authenticate with GCP

```bash
# Authenticate with your GCP account
gcloud auth application-default login

# Set your project
gcloud config set project YOUR_PROJECT_ID
```

### 2. Configure Environment Variables

Copy the `terraform.tfvars.template` as `terraform.tfvars` into your environment folder and fill up the required variables:

```hcl
gcp_project_name   = "your-project-id"
gcp_project_region = "asia-southeast1"
```

Update the files as needed, make sure to reflect it into the template as well.

## Initial Setup with Remote State

When setting up Terraform for the first time, the GCS bucket for remote state may not exist yet. Follow these steps:

### Step 1: Use Local Backend Initially

1. **Modify `backend.tf`** in your environment folder (e.g., `terraform/sandbox/backend.tf`):

```hcl
terraform {
  required_version = ">= 1.0.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "> 7.0.0"
    }
    github = {
      source  = "integrations/github"
      version = "~> 6.5.0"
    }
  }
  # Temporarily use local backend
  backend "local" {
    path = "terraform.tfstate"
  }
}
```

2. **Initialize Terraform**:

```bash
cd terraform/sandbox  # or your environment
terraform init
```

3. **Create the GCS bucket** for remote state (either manually or via Terraform):

```bash
# Option 1: Using gcloud
gcloud storage buckets create gs://your-project-tfstate-bucket \
  --location=asia-southeast1 \
  --uniform-bucket-level-access

# Option 2: Using Terraform (if you have a bucket resource defined)
terraform plan
terraform apply
```

### Step 2: Migrate to Remote Backend

1. **Update `backend.tf`** to use GCS:

```hcl
terraform {
  required_version = ">= 1.0.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "> 7.0.0"
    }
    github = {
      source  = "integrations/github"
      version = "~> 6.5.0"
    }
  }
  backend "gcs" {
    bucket = "your-project-tfstate-bucket"
    prefix = "terraform/state"
  }
}
```

2. **Re-initialize to migrate state**:

```bash
terraform init -migrate-state
```

When prompted, confirm the migration. Your local state will be uploaded to GCS.

## Normal Operations

### Initialize Terraform

Run this **whenever**:
- You clone the repository for the first time
- You add new modules to `main.tf`
- You update provider versions
- Backend configuration changes

```bash
cd terraform/<environment>
terraform init
```

### Plan Changes

**Always review changes before applying**:

```bash
terraform plan
```

**Save a plan for review**:

```bash
terraform plan -out=dev.plan
```

Review the plan output carefully:
- ✅ Resources to be created (`+`)
- ⚠️ Resources to be modified (`~`)
- ⚠️ Resources to be destroyed (`-`)
- ⚠️ Resources to be replaced (`-/+`)

### Apply Changes

After reviewing the plan:

```bash
# Apply a saved plan
terraform apply dev.plan

# Or apply directly (will prompt for confirmation)
terraform apply
```

### Other Useful Commands

```bash
# Format your Terraform files
terraform fmt -recursive

# Validate configuration
terraform validate

# Show current state
terraform show

# List resources in state
terraform state list

# Import existing resources
terraform import <resource_address> <resource_id>

# Destroy resources (use with caution!)
terraform destroy
```

## Adding New Modules

### Step 1: Create Module in `terraform/common/modules/`

1. **Create a new module directory**:

```bash
mkdir -p terraform/common/modules/my_new_module
```

2. **Create module files**:

```bash
cd terraform/common/modules/my_new_module
touch main.tf variables.tf outputs.tf
```

3. **Define the module** in `main.tf`:

```hcl
# main.tf
resource "google_storage_bucket" "example" {
  name          = var.bucket_name
  location      = var.gcp_project_region
  project       = var.gcp_project_name
  force_destroy = false
}
```

4. **Define variables** in `variables.tf`:

```hcl
# variables.tf
variable "gcp_project_name" {
  type        = string
  description = "Google Cloud Project ID"
}

variable "gcp_project_region" {
  type        = string
  description = "GCP region"
}

variable "bucket_name" {
  type        = string
  description = "Name of the storage bucket"
}
```

5. **Define outputs** in `outputs.tf`:

```hcl
# outputs.tf
output "bucket_name" {
  value       = google_storage_bucket.example.name
  description = "Name of the created bucket"
}

output "bucket_url" {
  value       = google_storage_bucket.example.url
  description = "URL of the created bucket"
}
```

### Step 2: Reference Module in Environment

1. **Add module reference** in `terraform/<environment>/main.tf`:

```hcl
module "my_new_module" {
  source             = "../common/modules/my_new_module"
  gcp_project_name   = var.gcp_project_name
  gcp_project_region = var.gcp_project_region
  bucket_name        = "my-unique-bucket-name"
  
  # Optional: Add dependencies
  depends_on = [
    module.general_setup,
  ]
}
```

2. **Initialize Terraform** to download the new module:

```bash
cd terraform/<environment>
terraform init
```

3. **Plan and review changes**:

```bash
terraform plan
```

4. **Apply changes**:

```bash
terraform apply
```

### Step 3: Use Module Outputs (Optional)

If other resources need outputs from your module:

```hcl
# In main.tf
resource "google_storage_bucket_object" "example" {
  name   = "example.txt"
  bucket = module.my_new_module.bucket_name
  content = "Hello World"
}
```

## Best Practices

### 1. **Always Review Plans**
Never run `terraform apply` without reviewing the plan first. Unexpected changes can be costly or destructive.

### 2. **Use Remote State**
Always use remote state (GCS) for team collaboration and state locking.

### 3. **Version Control**
- Commit `.tf` files and `terraform.tfvars` (if no secrets)
- **Never commit** `.tfstate` files or `.terraform/` directories
- Add to `.gitignore`:
  ```
  .terraform/
  *.tfstate
  *.tfstate.backup
  *.tfplan
  .terraformrc
  terraform.rc
  ```

### 4. **Module Best Practices**
- Keep modules focused and reusable
- Document variables with clear descriptions
- Use meaningful output names
- Version your modules if stored externally

### 5. **Naming Conventions**
- Use consistent naming for resources
- Include environment in resource names where appropriate
- Use descriptive module names

### 6. **State Management**
```bash
# List resources in state
terraform state list

# Remove resource from state (doesn't destroy the actual resource)
terraform state rm <resource_address>

# Import existing resource into state
terraform import <resource_address> <resource_id>
```

### 7. **Workspace Usage** (Alternative to Multiple Environments)
```bash
# List workspaces
terraform workspace list

# Create workspace
terraform workspace new staging

# Switch workspace
terraform workspace select staging
```

## Troubleshooting

### State Lock Errors
If you encounter state lock errors:
```bash
# Force unlock (use with caution!)
terraform force-unlock <lock_id>
```

### Provider Issues
```bash
# Upgrade providers
terraform init -upgrade

# Reconfigure backend
terraform init -reconfigure
```

### Import Existing Resources
```bash
# Example: Import a GCS bucket
terraform import google_storage_bucket.example bucket-name

# Example: Import artifact registry
terraform import module.my_registry.google_artifact_registry_repository.repo \
  projects/PROJECT_ID/locations/REGION/repositories/REPO_ID
```

## Support

For issues or questions:
1. Check Terraform documentation: https://www.terraform.io/docs
2. Check GCP provider docs: https://registry.terraform.io/providers/hashicorp/google/latest/docs
3. Review plan output carefully
4. Check GCP Console for resource state

---

**Last Updated**: February 2026
