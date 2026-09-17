import os
from functools import lru_cache

from pydantic_settings import BaseSettings

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

SECRETS_PATH = "/k8s/secrets"


def get_env_variable(key, default):
    # get kube secrets
    try:
        # todo - customizable secrets path
        with open(f"{SECRETS_PATH}/{key}") as f:
            token = f.read()
        return token
    except FileNotFoundError:
        pass

    # get env secrets if failed to get kube secrets
    return os.getenv(key, default)


class Settings(BaseSettings):
    # loaded from env
    environment: str = get_env_variable("ENVIRONMENT", "dev")  # modes - dev, prod
    testing: bool = bool(get_env_variable("TESTING", 0))
    NUM_THREADS: int = int(get_env_variable("NUM_THREADS", 1))
    MODULE_NAME: str = get_env_variable("MODULE_NAME", "CLASSIFICATION")

    # RMQ Config
    RABBITMQ_SERVER_URL: str = get_env_variable("RABBITMQ_SERVER_URL", "")
    RMQ_BROKER_ID: str = get_env_variable(
        "RMQ_USERNAME", "b-56184769-5d62-48cf-99e2-fc173f3407fa"
    )
    RMQ_AWS_REGION: str = get_env_variable("RMQ_AWS_REGION", "us-west-1")
    RMQ_USERNAME: str = get_env_variable("RMQ_USERNAME", "platform_producer")
    RMQ_PASSWORD: str = get_env_variable("RMQ_PASSWORD", "platform_producer")

    IP_QUEUE_NAME: str = get_env_variable("IP_QUEUE_NAME", "class_queue")
    RESP_QUEUE_NAME: str = get_env_variable("RESP_QUEUE_NAME", "platform_resp_queue")

    # s3 config
    S3_UPLOAD_BUCKET: str = get_env_variable("S3_UPLOAD_BUCKET", "birch-dev-bucket")
    S3_FOLDER_PATH: str = get_env_variable("S3_FOLDER_PATH", "data/class-service/class")


@lru_cache(maxsize=32)
def get_settings() -> Settings:
    return Settings()
