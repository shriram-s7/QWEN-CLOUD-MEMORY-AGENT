"""
Alibaba Cloud OSS (Object Storage Service) integration.

This is the PROOF-OF-DEPLOYMENT file referenced in the Devpost submission:
it demonstrates the backend using genuine Alibaba Cloud services/APIs
(oss2 SDK) to persist the agent's memory database off-instance, so memory
survives redeploys / instance restarts on Alibaba Cloud ECS or Function
Compute.

Env vars required (set these on the Alibaba Cloud instance / FC service):
  ALIBABA_ACCESS_KEY_ID
  ALIBABA_ACCESS_KEY_SECRET
  ALIBABA_OSS_ENDPOINT       e.g. https://oss-ap-southeast-1.aliyuncs.com
  ALIBABA_OSS_BUCKET         e.g. memoryagent-backups
"""

import os
import oss2

MEMORY_DB_PATH = os.environ.get("MEMORY_DB_PATH", "memory.db")
OSS_OBJECT_KEY = "backups/memory.db"


def _get_bucket() -> oss2.Bucket:
    access_key_id = os.environ["ALIBABA_ACCESS_KEY_ID"]
    access_key_secret = os.environ["ALIBABA_ACCESS_KEY_SECRET"]
    endpoint = os.environ["ALIBABA_OSS_ENDPOINT"]
    bucket_name = os.environ["ALIBABA_OSS_BUCKET"]

    auth = oss2.Auth(access_key_id, access_key_secret)
    return oss2.Bucket(auth, endpoint, bucket_name)


def backup_memory_db() -> str:
    """Upload the local SQLite memory store to Alibaba Cloud OSS."""
    bucket = _get_bucket()
    bucket.put_object_from_file(OSS_OBJECT_KEY, MEMORY_DB_PATH)
    return f"Backed up {MEMORY_DB_PATH} to oss://{bucket.bucket_name}/{OSS_OBJECT_KEY}"


def restore_memory_db() -> str:
    """Restore the SQLite memory store from Alibaba Cloud OSS on cold start."""
    bucket = _get_bucket()
    if bucket.object_exists(OSS_OBJECT_KEY):
        bucket.get_object_to_file(OSS_OBJECT_KEY, MEMORY_DB_PATH)
        return f"Restored {MEMORY_DB_PATH} from oss://{bucket.bucket_name}/{OSS_OBJECT_KEY}"
    return "No existing backup found in OSS; starting with a fresh memory store."


if __name__ == "__main__":
    print(restore_memory_db())
    print(backup_memory_db())
