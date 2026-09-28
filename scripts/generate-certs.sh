#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cert_dir="$project_dir/certs"
mkdir -p "$cert_dir"

openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout "$cert_dir/ca.key" \
  -out "$cert_dir/ca.crt" \
  -subj "/CN=LLM Guardian Proxy Development CA"

openssl req -newkey rsa:2048 -nodes \
  -keyout "$cert_dir/server.key" \
  -out "$cert_dir/server.csr" \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

printf '%s\n' 'subjectAltName=DNS:localhost,IP:127.0.0.1' 'extendedKeyUsage=serverAuth' > "$cert_dir/server.ext"

openssl x509 -req -days 365 \
  -in "$cert_dir/server.csr" \
  -CA "$cert_dir/ca.crt" \
  -CAkey "$cert_dir/ca.key" \
  -CAcreateserial \
  -out "$cert_dir/server.crt" \
  -extfile "$cert_dir/server.ext"

chmod 600 "$cert_dir/ca.key" "$cert_dir/server.key"
rm -f "$cert_dir/server.csr" "$cert_dir/server.ext" "$cert_dir/ca.srl"
echo "Certificates created in $cert_dir"
