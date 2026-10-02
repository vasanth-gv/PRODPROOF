terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = "ap-south-1"
}

variable "vpc_id" {
  type = string
}

resource "aws_security_group" "prodproof_phase6_test" {
  name        = "prodproof-phase6-test"
  description = "PRODPROOF Phase 6 Terraform analysis test"
  vpc_id      = var.vpc_id

  ingress {
    description = "Intentional test rule for PRODPROOF risk detection"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/16"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}