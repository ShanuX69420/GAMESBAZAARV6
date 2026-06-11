#!/opt/gamesbazaar/venv/bin/python
"""Nightly PostgreSQL backup -> Cloudflare R2 (db-backups/ prefix, keep 14)."""
import datetime
import os
import subprocess

ENV_PATH = "/opt/gamesbazaar/app/backend/.env"
RETAIN = 14


def load_env(path):
    vals = {}
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        vals[key.strip()] = value.strip()
    return vals


env = load_env(ENV_PATH)
db_name = env.get("DB_NAME", "gamesbazaar")

stamp = datetime.datetime.utcnow().strftime("%Y-%m-%d-%H%M%S")
tmp = f"/tmp/{db_name}-{stamp}.dump"
subprocess.run(["sudo", "-u", "postgres", "pg_dump", "-Fc", "-f", tmp, db_name], check=True)
# Refuse to upload a dump pg_restore cannot read.
subprocess.run(["pg_restore", "--list", tmp], check=True, stdout=subprocess.DEVNULL)
size_mb = os.path.getsize(tmp) / 1e6

import boto3

s3 = boto3.client(
    "s3",
    endpoint_url=env["CLOUDFLARE_R2_ENDPOINT_URL"],
    aws_access_key_id=env["CLOUDFLARE_R2_ACCESS_KEY_ID"],
    aws_secret_access_key=env["CLOUDFLARE_R2_SECRET_ACCESS_KEY"],
)
bucket = env["CLOUDFLARE_R2_BUCKET_NAME"]
key = f"db-backups/{db_name}-{stamp}.dump"
s3.upload_file(tmp, bucket, key)
os.remove(tmp)

objs = sorted(
    s3.list_objects_v2(Bucket=bucket, Prefix="db-backups/").get("Contents", []),
    key=lambda o: o["Key"],
)
for obj in objs[:-RETAIN]:
    s3.delete_object(Bucket=bucket, Key=obj["Key"])

print(f"Uploaded {key} ({size_mb:.1f} MB); {min(len(objs), RETAIN)} backups retained")
