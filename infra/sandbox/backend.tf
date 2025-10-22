terraform {
  required_version = ">= 1.0.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "> 7.0.0"
    }
  }
  backend "gcs" {
    bucket = "principia-infrastructure-dev-tfstate-zca4g"
    prefix = "terraform/state"
  }
}