locals {
  ai_image_key = "deploy/hality-ai.tar"

  # Prepara docker, compose e swap no boot da aplicacao.
  user_data = <<-BASH
    #!/bin/bash
    set -e
    dnf install -y docker
    systemctl enable --now docker
    usermod -aG docker ec2-user

    mkdir -p /usr/local/lib/docker/cli-plugins
    curl -fSL https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 \
      -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

    dd if=/dev/zero of=/swapfile bs=1M count=2048
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile swap swap defaults 0 0' >> /etc/fstab
  BASH

  # Maquina do modelo nao tem internet: docker vem dos repositorios do AL2023 e
  # a imagem vem do bucket, os dois pelo endpoint S3. O servico tenta de novo a
  # cada minuto ate o hality-ai.tar existir no bucket, e sobe o container em
  # todo boot.
  ai_user_data = <<-BASH
    #!/bin/bash
    set -e
    dnf install -y docker
    systemctl enable --now docker

    dd if=/dev/zero of=/swapfile bs=1M count=2048
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile swap swap defaults 0 0' >> /etc/fstab

    cat > /usr/local/bin/hality-ai-start.sh <<'SCRIPT'
    #!/bin/bash
    set -euo pipefail
    if ! docker image inspect hality-ai:latest >/dev/null 2>&1; then
      aws s3 cp --region ${var.aws_region} \
        s3://${aws_s3_bucket.assets.bucket}/${local.ai_image_key} /tmp/hality-ai.tar
      docker load -i /tmp/hality-ai.tar
      rm -f /tmp/hality-ai.tar
    fi
    docker rm -f hality-ai >/dev/null 2>&1 || true
    docker run -d --name hality-ai --restart unless-stopped -p 8000:8000 hality-ai:latest
    SCRIPT
    chmod +x /usr/local/bin/hality-ai-start.sh

    cat > /etc/systemd/system/hality-ai.service <<'UNIT'
    [Unit]
    Description=Modelo hality-ai
    After=docker.service
    Requires=docker.service

    [Service]
    Type=oneshot
    RemainAfterExit=yes
    ExecStart=/usr/local/bin/hality-ai-start.sh
    Restart=on-failure
    RestartSec=60

    [Install]
    WantedBy=multi-user.target
    UNIT
    systemctl daemon-reload
    systemctl enable --now --no-block hality-ai.service
  BASH
}

# --- IAM: role da EC2 da aplicacao com acesso a S3 e ao SSM ---
resource "aws_iam_role" "ec2" {
  name = "${var.project}-${var.env}-ec2-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

# Session Manager (acesso sem depender de SSH)
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Acesso ao bucket do projeto (imagens de diagnostico e backups)
resource "aws_iam_role_policy" "s3" {
  name = "${var.project}-${var.env}-s3-access"
  role = aws_iam_role.ec2.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.assets.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.assets.arn
      },
    ]
  })
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${var.project}-${var.env}-ec2-profile"
  role = aws_iam_role.ec2.name
}

# --- IAM: role da EC2 do modelo (so le a propria imagem no bucket) ---
resource "aws_iam_role" "ai" {
  name = "${var.project}-${var.env}-ai-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "ai_s3" {
  name = "${var.project}-${var.env}-ai-s3-read"
  role = aws_iam_role.ai.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = "${aws_s3_bucket.assets.arn}/${local.ai_image_key}"
    }]
  })
}

resource "aws_iam_instance_profile" "ai" {
  name = "${var.project}-${var.env}-ai-profile"
  role = aws_iam_role.ai.name
}

# --- EC2 publica: api, identity-worker e postgres (docker compose) ---
resource "aws_instance" "app" {
  ami                    = nonsensitive(data.aws_ssm_parameter.al2023.value)
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.ec2.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name
  key_name               = var.key_pair_name != "" ? var.key_pair_name : null
  user_data              = local.user_data

  metadata_options {
    http_tokens = "required" # IMDSv2
  }

  # Guarda o Postgres com dado de saude: disco criptografado.
  root_block_device {
    volume_size = 20
    volume_type = "gp3"
    encrypted   = true
  }

  lifecycle {
    ignore_changes  = [ami, user_data]
    prevent_destroy = true
  }

  tags = { Name = "${var.project}-${var.env}-app" }
}

# IP fixo: sobrevive a stop/start e mantem o DNS da aplicacao valido
resource "aws_eip" "app" {
  instance = aws_instance.app.id
  domain   = "vpc"
  tags     = { Name = "${var.project}-${var.env}-eip" }
}

# --- EC2 privada do modelo hality-ai (acessada so pela aplicacao, porta 8000) ---
resource "aws_instance" "ai" {
  ami                         = nonsensitive(data.aws_ssm_parameter.al2023.value)
  instance_type               = var.ai_instance_type
  subnet_id                   = aws_subnet.private.id
  associate_public_ip_address = false
  vpc_security_group_ids      = [aws_security_group.ai.id]
  iam_instance_profile        = aws_iam_instance_profile.ai.name
  user_data                   = local.ai_user_data

  metadata_options {
    http_tokens = "required" # IMDSv2
  }

  # SO + swap + hality-ai.tar (~650 MB) + imagem carregada (~2,6 GB)
  root_block_device {
    volume_size = 12
    volume_type = "gp3"
    encrypted   = true
  }

  lifecycle {
    ignore_changes = [ami, user_data]
  }

  tags = { Name = "${var.project}-${var.env}-ai" }
}
