# AI pipeline worker (AWS Lambda, container image, arm64)
# build จากโฟลเดอร์ AI (context = AI/):  ./pipeline/build_worker.sh
FROM --platform=linux/arm64 public.ecr.aws/lambda/python:3.12

# LightGBM ต้องใช้ OpenMP runtime
RUN dnf install -y libgomp && dnf clean all

COPY pipeline/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# โค้ดของทั้ง 3 ส่วน (ไม่เอา .venv / output / .env ดู .dockerignore)
COPY risk_forecaster      ${LAMBDA_TASK_ROOT}/risk_forecaster
COPY food_waste_optimizer ${LAMBDA_TASK_ROOT}/food_waste_optimizer
COPY llm-task-agent       ${LAMBDA_TASK_ROOT}/llm-task-agent
COPY pipeline/worker.py   ${LAMBDA_TASK_ROOT}/worker.py

# เทรน Forecaster ใน image (models/*.pkl ไม่เข้า git และต้องตรงกับเวอร์ชัน library ใน image)
# ใช้ cutoff จาก models/risk_thresholds.json ที่ commit ไว้ (ไม่รัน calibrate_risk.py)
WORKDIR ${LAMBDA_TASK_ROOT}/risk_forecaster
RUN python train_forecaster.py

WORKDIR ${LAMBDA_TASK_ROOT}
ENV AI_DIR=${LAMBDA_TASK_ROOT} \
    WORK_DIR=/tmp/pipeline \
    PYTHONUNBUFFERED=1

CMD ["worker.lambda_handler"]
