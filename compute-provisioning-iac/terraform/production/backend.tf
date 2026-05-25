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
    bucket = "arkhai-io-prod-tfstate-07e7d167"
    prefix = "terraform/state"
  }
}