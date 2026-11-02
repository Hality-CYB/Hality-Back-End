output "app_public_ip" {
  description = "IP publico fixo do servidor da aplicacao (apontar o DNS para ele)."
  value       = aws_eip.app.public_ip
}

output "app_instance_id" {
  description = "Use com: aws ssm start-session --target <id>"
  value       = aws_instance.app.id
}

output "ai_instance_id" {
  description = "Use com: aws ec2-instance-connect ssh --connection-type eice --os-user ec2-user --instance-id <id>"
  value       = aws_instance.ai.id
}

output "ai_image_s3_uri" {
  description = "Onde enviar o hality-ai.tar; a maquina do modelo baixa e sobe sozinha."
  value       = "s3://${aws_s3_bucket.assets.bucket}/${local.ai_image_key}"
}

output "hality_ai_url" {
  description = "Valor de HALITY_AI_URL no .env da API (rede privada da VPC)."
  value       = "http://${aws_instance.ai.private_ip}:8000"
}

output "assets_bucket" {
  description = "Bucket privado de imagens e backups."
  value       = aws_s3_bucket.assets.bucket
}
