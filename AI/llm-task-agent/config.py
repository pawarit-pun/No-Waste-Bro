import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    API_BASE_URL: str = os.getenv(
        "API_BASE_URL",
        "https://yu00jk24pk.execute-api.ap-southeast-1.amazonaws.com/api/v1/",
    )

    AWS_REGION: str = os.getenv("AWS_REGION", "ap-southeast-1")

    BEDROCK_KB_ID: str = os.getenv("BEDROCK_KB_ID", "")

    BEDROCK_MODEL_ID: str = os.getenv("BEDROCK_MODEL_ID", "")


settings = Settings()
