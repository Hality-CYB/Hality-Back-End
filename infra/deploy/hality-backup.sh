#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly bucket="hality-staging-assets-503341763467"
readonly region="us-east-2"
readonly tmpdir=$(mktemp -d /tmp/hality-backup.XXXXXXXX)
trap 'rm -rf -- "$tmpdir"' EXIT
dump="$tmpdir/database.dump"
key="backups/postgres/$(date -u +%Y/%m/%dT%H%M%SZ)-$(cat /proc/sys/kernel/random/uuid).dump"

docker exec hality-db-1 sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$dump"
test -s "$dump"
docker exec -i hality-db-1 pg_restore --list < "$dump" > /dev/null
aws s3 cp "$dump" "s3://$bucket/$key" --region "$region" --sse AES256 --only-show-errors
local_size=$(wc -c < "$dump")
remote_size=$(aws s3api head-object --bucket "$bucket" --key "$key" --region "$region" --query ContentLength --output text)
test "$local_size" -eq "$remote_size"
printf 'Backup salvo: s3://%s/%s (%s bytes)\n' "$bucket" "$key" "$local_size"
