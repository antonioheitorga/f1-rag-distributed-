# versions.tf — versões do Terraform e dos providers usados.
#
# Pinar versões evita surpresas quando outra pessoa (ou outra máquina)
# rodar `terraform init`. Sem isso, o Terraform baixa a última versão
# do provider AWS, que pode ter breaking changes.

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}
