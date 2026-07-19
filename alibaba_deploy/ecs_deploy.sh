#!/usr/bin/env bash
# Fastest path to a running MemoryAgent backend on Alibaba Cloud ECS.
#
# Run this ON the ECS instance (Ubuntu 22.04 recommended) after SSH-ing in.
# Assumes you already created a small ECS instance from the Alibaba Cloud
# console (free-tier eligible instance types are fine for a demo).

set -e

sudo apt-get update -y
sudo apt-get install -y python3-pip python3-venv git

git clone <YOUR_REPO_URL> memoryagent
cd memoryagent

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Required secrets - export before running, or put in /etc/environment
export QWEN_API_KEY="your_qwen_cloud_api_key"
export ALIBABA_ACCESS_KEY_ID="your_access_key_id"
export ALIBABA_ACCESS_KEY_SECRET="your_access_key_secret"
export ALIBABA_OSS_ENDPOINT="https://oss-ap-southeast-1.aliyuncs.com"
export ALIBABA_OSS_BUCKET="memoryagent-backups"

# Run in the foreground for the demo video, or with nohup for persistence
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > server.log 2>&1 &

echo "MemoryAgent backend running on Alibaba Cloud ECS at http://<ECS_PUBLIC_IP>:8000"
echo "Remember to open port 8000 in the ECS Security Group before testing."
