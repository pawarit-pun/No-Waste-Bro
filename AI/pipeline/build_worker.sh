#!/usr/bin/env bash
# Build + push image ของ AI pipeline worker ขึ้น ECR แล้วพิมพ์ ImageUri สำหรับ sam deploy
#
# ใช้งาน (จากที่ไหนก็ได้):  ./AI/pipeline/build_worker.sh
# ต้องมี: Docker ที่เปิดอยู่, aws configure แล้ว
# env ที่เปลี่ยนได้: AWS_REGION (ap-southeast-1), REPO_NAME (no-waste-bro-ai-worker), IMAGE_TAG (เวลาปัจจุบัน)
set -euo pipefail

cd "$(dirname "$0")/.."            # AI/
REGION="${AWS_REGION:-ap-southeast-1}"
REPO_NAME="${REPO_NAME:-no-waste-bro-ai-worker}"
IMAGE_TAG="${IMAGE_TAG:-$(date +%Y%m%d-%H%M%S)}"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
IMAGE_URI="${REGISTRY}/${REPO_NAME}:${IMAGE_TAG}"

echo "→ ECR repository ${REPO_NAME} (${REGION})"
aws ecr describe-repositories --repository-names "${REPO_NAME}" --region "${REGION}" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "${REPO_NAME}" --region "${REGION}" \
       --image-scanning-configuration scanOnPush=false >/dev/null

echo "→ docker login"
aws ecr get-login-password --region "${REGION}" | docker login --username AWS --password-stdin "${REGISTRY}"

echo "→ build (linux/arm64) + เทรน Forecaster ใน image"
# --provenance=false: Lambda รับเฉพาะ image manifest แบบเดี่ยว
docker buildx build --platform linux/arm64 --provenance=false \
  -f pipeline/Dockerfile -t "${IMAGE_URI}" --push .

echo "${IMAGE_URI}" > pipeline/.last_image_uri   # sam deploy ทุกครั้งต้องส่ง WorkerImageUri (อ่านจากไฟล์นี้)

echo
echo "✓ pushed: ${IMAGE_URI}  (บันทึกไว้ที่ AI/pipeline/.last_image_uri)"
echo "  deploy (จากโฟลเดอร์ No-Waste-Bro): cd server && ./scripts/build_lambda.sh && sam deploy --parameter-overrides \\"
echo "            SupabaseServiceRoleKey=\"\$(grep '^SUPABASE_SERVICE_ROLE_KEY=' .env | cut -d= -f2-)\" \\"
echo "            WorkerImageUri=\"\$(cat ../AI/pipeline/.last_image_uri)\""
