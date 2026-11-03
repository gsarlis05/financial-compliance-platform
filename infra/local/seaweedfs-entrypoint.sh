#!/bin/sh
# Writes the SeaweedFS S3 identity file from environment variables, then starts the server.
# Local development only.
set -eu
: "${S3_ACCESS_KEY:?S3_ACCESS_KEY is required}"
: "${S3_SECRET_KEY:?S3_SECRET_KEY is required}"
printf '{"identities":[{"name":"dev","credentials":[{"accessKey":"%s","secretKey":"%s"}],"actions":["Admin","Read","Write","List","Tagging"]}]}' \
  "$S3_ACCESS_KEY" "$S3_SECRET_KEY" > /tmp/s3.json
exec weed server -dir=/data -s3 -s3.port=8333 -s3.config=/tmp/s3.json -master.volumeSizeLimitMB=256
