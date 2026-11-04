locals {
  github_repositories = {
    back  = { name = "Hality-Back-End", id = "1334668248" }
    front = { name = "Hality-Front-End", id = "1334667880" }
  }
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

resource "aws_iam_role" "github_deploy" {
  for_each = local.github_repositories
  name     = "${var.project}-${var.env}-github-deploy-${each.key}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = { StringEquals = {
        "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        "token.actions.githubusercontent.com:sub" = "repo:Hality-CYB@317138798/${each.value.name}@${each.value.id}:ref:refs/heads/main"
      } }
    }]
  })
}

resource "aws_ssm_document" "deploy" {
  for_each        = local.github_repositories
  name            = "${var.project}-${var.env}-deploy-${each.key}"
  document_type   = "Command"
  document_format = "JSON"
  content = jsonencode({
    schemaVersion = "2.2"
    description   = "Publica um commit validado da main na instancia da aplicacao"
    parameters = {
      Commit = { type = "String", allowedPattern = "^[0-9a-f]{40}$" }
    }
    mainSteps = [{
      action = "aws:runShellScript"
      name   = "deploy"
      inputs = { timeoutSeconds = "2400", runCommand = ["/usr/local/sbin/hality-deploy ${each.key} {{ Commit }}"] }
    }]
  })
}

resource "aws_iam_role_policy" "github_deploy" {
  for_each = local.github_repositories
  name     = "deploy"
  role     = aws_iam_role.github_deploy[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["ssm:SendCommand"], Resource = [aws_ssm_document.deploy[each.key].arn, aws_instance.app.arn] },
      { Effect = "Allow", Action = ["ssm:GetCommandInvocation"], Resource = "*" }
    ]
  })
}

output "github_deploy_role_arns" {
  value = { for k, role in aws_iam_role.github_deploy : k => role.arn }
}
