variable "aws_region" {
  description = "Região da estimativa (US East - Ohio)."
  type        = string
  default     = "us-east-2"
}

variable "project" {
  description = "Prefixo usado nos nomes e tags dos recursos."
  type        = string
  default     = "hality"
}

variable "env" {
  description = "Ambiente (ex.: staging, prod)."
  type        = string
  default     = "staging"
}

variable "vpc_cidr" {
  description = "Faixa de IPs da VPC do projeto."
  type        = string
  default     = "10.20.0.0/16"
}

variable "public_subnet_cidr" {
  description = "Faixa de IPs da subnet pública onde ficam as EC2."
  type        = string
  default     = "10.20.1.0/24"
}

variable "private_subnet_cidr" {
  description = "Faixa de IPs da subnet privada do modelo (sem IP publico)."
  type        = string
  default     = "10.20.2.0/24"
}

variable "instance_type" {
  description = "Servidor da aplicação, ligado o mês inteiro. A SCP da organização bloqueia a família t3a."
  type        = string
  default     = "t3.small"
}

variable "ai_instance_type" {
  description = "Servidor do modelo hality-ai; a estimativa considera ~30% de uso no mês."
  type        = string
  default     = "t3.medium"
}

variable "key_pair_name" {
  description = "Key pair para SSH. Vazio = só Session Manager."
  type        = string
  default     = ""
}

variable "ssh_ingress_cidrs" {
  description = "Origens liberadas na porta 22. Vazio = SSH fechado."
  type        = list(string)
  default     = []
}

variable "http_ingress_cidrs" {
  description = "Origens liberadas para HTTP/HTTPS no servidor da aplicação."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}
