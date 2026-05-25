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
    bucket = "ww-migration-arkhai-tfstate-e9fbb654"
    prefix = "terraform/state"
  }
}