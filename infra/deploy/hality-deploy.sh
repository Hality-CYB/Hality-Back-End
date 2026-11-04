#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

component=${1:?componente obrigatorio}
commit=${2:?commit obrigatorio}
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || { echo 'Commit invalido' >&2; exit 1; }
case "$component" in
  back) repository='Hality-Back-End'; image='hality-api:prod' ;;
  front) repository='Hality-Front-End'; image='hality-front:prod' ;;
  *) echo 'Componente invalido' >&2; exit 1 ;;
esac

exec 9>/var/lock/hality-deploy.lock
flock -w 1800 9 || { echo 'Tempo limite aguardando outro deploy' >&2; exit 1; }
url="https://github.com/Hality-CYB/$repository.git"
check_main() {
  local head
  head=$(git ls-remote "$url" refs/heads/main | cut -f1)
  [[ "$head" == "$commit" ]] || { echo 'Commit nao corresponde mais a main' >&2; exit 1; }
}
check_main
/usr/local/sbin/hality-backup
workdir=$(mktemp -d /tmp/hality-deploy.XXXXXXXX)
trap 'rm -rf -- "$workdir"' EXIT
git clone --quiet --no-checkout "$url" "$workdir/source"
git -C "$workdir/source" checkout --quiet --detach "$commit"

candidate="${image%:*}:$commit"
if [[ "$component" == front ]]; then
  docker build --build-arg NEXT_PUBLIC_API_URL=https://hality-cyb.duckdns.org -t "$candidate" "$workdir/source"
else
  docker build -t "$candidate" "$workdir/source"
fi
check_main
docker tag "$candidate" "$image"
cd /home/ec2-user/hality
if [[ "$component" == back ]]; then
  docker compose up -d --no-deps --no-build --force-recreate api
  api_ready=false
  for attempt in $(seq 1 36); do
    if curl --fail --silent --max-time 5 --output /dev/null https://hality-cyb.duckdns.org/api/v1/health/db; then
      api_ready=true
      break
    fi
    sleep 5
  done
  [[ "$api_ready" == true ]] || { echo 'API indisponivel; worker nao foi atualizado' >&2; exit 1; }
  docker compose up -d --no-deps --no-build --force-recreate identity-worker
else
  docker compose up -d --no-deps --no-build --force-recreate front
fi

for attempt in $(seq 1 36); do
  if curl --fail --silent --max-time 5 --output /dev/null https://hality-cyb.duckdns.org/api/v1/health/db &&
     curl --fail --silent --max-time 5 --output /dev/null https://hality-cyb.duckdns.org/; then
    if [[ "$component" == back ]]; then
      test "$(docker inspect --format '{{.Image}}' hality-api-1)" = "$(docker inspect --format '{{.Image}}' hality-identity-worker-1)"
      test "$(docker inspect --format '{{.State.Running}}' hality-identity-worker-1)" = true
    fi
    printf 'Deploy validado: %s %s\n' "$component" "$commit"
    exit 0
  fi
  sleep 5
done
echo 'Validacao de saude falhou; intervencao manual necessaria' >&2
exit 1
