# --- VPC propria com uma subnet publica (sem NAT, para manter o custo) ---
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "${var.project}-${var.env}-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.project}-${var.env}-igw" }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidr
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true
  tags                    = { Name = "${var.project}-${var.env}-public" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${var.project}-${var.env}-public-rt" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# --- Subnet privada do modelo: sem IP publico e sem rota para a internet ---
resource "aws_subnet" "private" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = var.private_subnet_cidr
  availability_zone = data.aws_availability_zones.available.names[0]
  tags              = { Name = "${var.project}-${var.env}-private" }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.project}-${var.env}-private-rt" }
}

resource "aws_route_table_association" "private" {
  subnet_id      = aws_subnet.private.id
  route_table_id = aws_route_table.private.id
}

# S3 pela rede interna (gratis): repositorios do Amazon Linux 2023 e o
# hality-ai.tar do bucket chegam a subnet privada sem NAT.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.public.id, aws_route_table.private.id]
  tags              = { Name = "${var.project}-${var.env}-s3-endpoint" }
}

# SSH na maquina privada sem IP publico (gratis), no lugar dos endpoints do SSM.
resource "aws_ec2_instance_connect_endpoint" "private" {
  subnet_id          = aws_subnet.private.id
  security_group_ids = [aws_security_group.eice.id]
  preserve_client_ip = false
  tags               = { Name = "${var.project}-${var.env}-eice" }
}

# --- Security groups ---
# Aplicacao: HTTP/HTTPS publico; SSH so se ssh_ingress_cidrs for preenchido
resource "aws_security_group" "ec2" {
  name        = "${var.project}-${var.env}-ec2-sg"
  description = "Servidor da aplicacao Hality"
  vpc_id      = aws_vpc.main.id
  tags        = { Name = "${var.project}-${var.env}-ec2-sg" }
}

resource "aws_vpc_security_group_ingress_rule" "ec2_http" {
  for_each          = toset(var.http_ingress_cidrs)
  security_group_id = aws_security_group.ec2.id
  cidr_ipv4         = each.value
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "ec2_https" {
  for_each          = toset(var.http_ingress_cidrs)
  security_group_id = aws_security_group.ec2.id
  cidr_ipv4         = each.value
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "ec2_ssh" {
  for_each          = toset(var.ssh_ingress_cidrs)
  security_group_id = aws_security_group.ec2.id
  cidr_ipv4         = each.value
  from_port         = 22
  to_port           = 22
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "ec2_all" {
  security_group_id = aws_security_group.ec2.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# Modelo hality-ai: porta 8000 so a partir do servidor da aplicacao
resource "aws_security_group" "ai" {
  name        = "${var.project}-${var.env}-ai-sg"
  description = "Modelo hality-ai"
  vpc_id      = aws_vpc.main.id
  tags        = { Name = "${var.project}-${var.env}-ai-sg" }
}

resource "aws_vpc_security_group_ingress_rule" "ai_from_app" {
  security_group_id            = aws_security_group.ai.id
  referenced_security_group_id = aws_security_group.ec2.id
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "ai_ssh" {
  security_group_id            = aws_security_group.ai.id
  referenced_security_group_id = aws_security_group.eice.id
  from_port                    = 22
  to_port                      = 22
  ip_protocol                  = "tcp"
}

# Sem rota para a internet, a saida so alcanca a VPC e o S3 (endpoint).
resource "aws_vpc_security_group_egress_rule" "ai_all" {
  security_group_id = aws_security_group.ai.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# Instance Connect Endpoint: so abre SSH ate a maquina do modelo
resource "aws_security_group" "eice" {
  name        = "${var.project}-${var.env}-eice-sg"
  description = "EC2 Instance Connect Endpoint"
  vpc_id      = aws_vpc.main.id
  tags        = { Name = "${var.project}-${var.env}-eice-sg" }
}

resource "aws_vpc_security_group_egress_rule" "eice_to_ai" {
  security_group_id            = aws_security_group.eice.id
  referenced_security_group_id = aws_security_group.ai.id
  from_port                    = 22
  to_port                      = 22
  ip_protocol                  = "tcp"
}
