# --- S3: imagens de diagnostico, midias de conteudo e backups (privado, criptografado, versionado) ---
resource "aws_s3_bucket" "assets" {
  # O sufixo com o id da conta garante nome global unico.
  bucket = "${var.project}-${var.env}-assets-${data.aws_caller_identity.current.account_id}"
  tags   = { Name = "${var.project}-${var.env}-assets" }
}

resource "aws_s3_bucket_public_access_block" "assets" {
  bucket                  = aws_s3_bucket.assets.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "assets" {
  bucket = aws_s3_bucket.assets.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "assets" {
  bucket = aws_s3_bucket.assets.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "assets" {
  bucket = aws_s3_bucket.assets.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Versoes antigas e uploads incompletos nao ficam acumulando custo
resource "aws_s3_bucket_lifecycle_configuration" "assets" {
  bucket = aws_s3_bucket.assets.id

  rule {
    id     = "limpeza"
    status = "Enabled"
    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  # Objetos de backup tem chave unica. Versoes antigas sao eliminadas no
  # primeiro dia permitido apos se tornarem nao correntes.
  rule {
    id     = "backups-postgres-retencao"
    status = "Enabled"
    filter { prefix = "backups/postgres/" }

    expiration { days = 30 }
    noncurrent_version_expiration { noncurrent_days = 1 }
  }

  rule {
    id     = "backups-postgres-marcadores"
    status = "Enabled"
    filter { prefix = "backups/postgres/" }

    expiration { expired_object_delete_marker = true }
  }

  # Upload direto do navegador: o arquivo chega em uploads/ e a API o move para
  # diagnosticos/ ou conteudos/ ao confirmar. O que nao for confirmado expira
  # em 1 dia, entao nenhuma foto de saude abandonada fica no bucket.
  rule {
    id     = "uploads-abandonados"
    status = "Enabled"
    filter { prefix = "uploads/" }

    expiration { days = 1 }
    noncurrent_version_expiration { noncurrent_days = 1 }
  }

  rule {
    id     = "uploads-marcadores"
    status = "Enabled"
    filter { prefix = "uploads/" }

    expiration { expired_object_delete_marker = true }
  }

  depends_on = [aws_s3_bucket_versioning.assets]
}

# O navegador envia direto ao bucket com POST (presigned POST). A leitura passa
# por <img>/<video> seguindo o redirect da API, sem precisar de CORS.
resource "aws_s3_bucket_cors_configuration" "assets" {
  bucket = aws_s3_bucket.assets.id

  cors_rule {
    allowed_methods = ["POST"]
    allowed_origins = var.app_origins
    allowed_headers = ["*"]
    max_age_seconds = 3000
  }
}

resource "aws_s3_bucket_policy" "assets" {
  bucket = aws_s3_bucket.assets.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "SomenteTLS"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.assets.arn, "${aws_s3_bucket.assets.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })

  depends_on = [aws_s3_bucket_public_access_block.assets]
}
