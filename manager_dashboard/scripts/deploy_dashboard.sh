#!/usr/bin/env bash
# Build Manager Dashboard แล้วอัปโหลดขึ้น S3 + ล้าง cache ของ CloudFront
#
# ใช้งาน (จากที่ไหนก็ได้):  ./manager_dashboard/scripts/deploy_dashboard.sh
# ต้องมี: sam deploy stack นี้แล้ว (มี DashboardBucket / DashboardDistribution), aws configure แล้ว, Node + npm
# env ที่เปลี่ยนได้: STACK_NAME (no-waste-bro-api), AWS_REGION (ap-southeast-1)
set -euo pipefail

cd "$(dirname "$0")/.."            # manager_dashboard/
STACK_NAME="${STACK_NAME:-no-waste-bro-api}"
REGION="${AWS_REGION:-ap-southeast-1}"

output() {
  aws cloudformation describe-stacks --stack-name "${STACK_NAME}" --region "${REGION}" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

echo "→ อ่าน outputs ของ stack ${STACK_NAME} (${REGION})"
BUCKET="$(output DashboardBucketName)"
DIST_ID="$(output DashboardDistributionId)"
URL="$(output DashboardUrl)"
if [[ -z "${BUCKET}" || "${BUCKET}" == "None" || -z "${DIST_ID}" || "${DIST_ID}" == "None" ]]; then
  echo "✗ ไม่พบ DashboardBucketName / DashboardDistributionId: sam deploy template.yaml เวอร์ชันที่มี Dashboard ก่อน" >&2
  exit 1
fi

# VITE_* ถูกฝังลงไฟล์ตอน build: ต้องมี .env ที่ชี้ไป API บน AWS
if [[ ! -f .env ]]; then
  echo "✗ ไม่พบ manager_dashboard/.env (คัดลอกจาก .env.example)" >&2
  exit 1
fi

echo "→ build"
[[ -d node_modules ]] || npm install
npm run build

echo "→ อัปโหลดขึ้น s3://${BUCKET}"
# 1) assets/* ชื่อไฟล์มี hash: cache ได้ 1 ปี (อัปโหลดก่อน index.html เพื่อให้ไฟล์ใหม่พร้อมก่อนหน้าเว็บอ้างถึง)
aws s3 sync dist/assets "s3://${BUCKET}/assets" --region "${REGION}" \
  --cache-control "public,max-age=31536000,immutable"
# 2) index.html และไฟล์อื่นนอก assets: no-cache = browser ถามใหม่ทุกครั้ง deploy แล้วเห็นผลทันที
aws s3 sync dist "s3://${BUCKET}" --region "${REGION}" --delete --exclude "assets/*" \
  --cache-control "no-cache"
# 3) ลบ assets เก่าที่ไม่ใช้แล้ว
aws s3 sync dist/assets "s3://${BUCKET}/assets" --region "${REGION}" --delete \
  --cache-control "public,max-age=31536000,immutable"

echo "→ ล้าง cache ของ CloudFront (${DIST_ID})"
aws cloudfront create-invalidation --distribution-id "${DIST_ID}" --paths "/*" \
  --query "Invalidation.Id" --output text

echo
echo "✓ deploy แล้ว: ${URL}  (invalidation ใช้เวลาประมาณ 1-2 นาที)"
