terraform {
  backend "s3" {
    bucket = "alpha-state"
    key    = "orders.tfstate"
  }
}

provider "aws" {
  region = var.region
}

variable "region" {
  default = "eu-west-1"
}

resource "aws_s3_bucket" "cache" {
  bucket = "alpha-orders-cache"
  acl    = "public-read"
}

output "cache_bucket" {
  value = aws_s3_bucket.cache.id
}
