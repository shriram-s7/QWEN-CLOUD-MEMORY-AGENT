"""
Alibaba Cloud Function Compute (FC) entrypoint.

Wraps the FastAPI app so it can run as a serverless HTTP function on
Alibaba Cloud Function Compute, using the standard FC custom-runtime
HTTP trigger contract (the platform proxies HTTP requests directly to
this ASGI app via mangum-style adaptation).

Deploy with the `s` (Serverless Devs) CLI or `fun` CLI pointed at this
directory; see alibaba_deploy/s.yaml for the function definition.
"""

from mangum import Mangum
from app.main import app
from alibaba_deploy.oss_backup import restore_memory_db, backup_memory_db

# Restore persisted memory DB from OSS on cold start
try:
    print(restore_memory_db())
except KeyError:
    print("OSS env vars not set; skipping restore (local/dev mode).")

handler = Mangum(app)


def fc_handler(event, context):
    """Alibaba Cloud FC invokes this as the function entrypoint."""
    response = handler(event, context)
    try:
        backup_memory_db()
    except KeyError:
        pass
    return response
