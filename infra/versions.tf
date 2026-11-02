# Infraestrutura Hality na AWS.
#
# Base: estimativa da Calculadora de Preços da AWS de 16/10/2026
# (https://calculator.aws/#/estimate?id=e5b55e71e1ec0933711c06bc5574520ac039c25d),
# ~23,40 USD/mês em US East (Ohio):
#   - EC2 t3a.small, 100% do mês  -> servidor da aplicação (api, identity-worker, postgres)
#     Na prática usamos t3.small: a SCP da organização bloqueia a família t3a.
#   - EC2 t3.medium, ~30% do mês  -> modelo de inferência hality-ai
#   - S3 Standard, ~5 GB          -> imagens de diagnóstico e backups

terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Estado local por enquanto. Antes de mais de uma pessoa aplicar, mover para
  # um backend S3 com lock, por exemplo:
  # backend "s3" {
  #   bucket       = "hality-terraform-state"
  #   key          = "infra/terraform.tfstate"
  #   region       = "us-east-2"
  #   use_lockfile = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.env
      ManagedBy   = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}
