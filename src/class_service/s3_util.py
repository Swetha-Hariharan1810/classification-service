import datetime
import logging
import re
import subprocess
import uuid
from pathlib import Path
from typing import Union

import boto3
import botocore

s3_re = re.compile(r"s3://([^/]*)/(.*)")
s3 = boto3.client("s3")
s3_resource = boto3.resource("s3")
logger = logging.getLogger(__name__)


def download_file(s3_path: str, download_path: Union[Path, str]):
    m = s3_re.match(s3_path)
    if not m:
        raise ValueError(f"{s3_path} is not a valid s3 path!")
    try:
        bucket = m[1]
        obj = m[2]
        s3.download_file(bucket, obj, str(download_path))
    except botocore.exceptions.ClientError as error:
        logger.error(f"boto3 error, use aws-cli instead. {error}")
        subprocess.check_call(["aws", "s3", "cp", s3_path, download_path])


def download_s3_text_file(s3_path, task_id):
    unique_dirname = (
        datetime.datetime.now().strftime("%Y-%m-%d_%H:%M:%S_task")
        + str(task_id)
        + "_"
        + str(uuid.uuid4())[:5]
    )
    dir_path = Path("/tmp/") / unique_dirname
    dir_path.mkdir(exist_ok=True, parents=True)
    text_path = dir_path / "transcript.txt"
    download_file(s3_path, text_path)
    logger.debug(f"Downloaded file {s3_path} to {text_path}")

    return text_path.read_text()


def download_buffer(s3_path: str):
    m = s3_re.match(s3_path)
    if not m:
        raise ValueError(f"{s3_path} is not a valid s3 path!")
    try:
        bucket = m[1]
        obj = m[2]
        return s3_resource.Bucket(bucket).Object(obj).get()["Body"].read()
    except botocore.exceptions.ClientError as error:
        logger.exception(f"boto3 error, use aws-cli instead. {error}")
