from pathlib import Path
import yaml
import logging.config


def setup_logging():
    with open(Path(__file__).parent / "logging-config.yaml", "r") as f:
        config = yaml.safe_load(f.read())
        logging.config.dictConfig(config)


setup_logging()
import json
import os
import traceback

import torch
import time
import datetime
from rmq import constants, rmq_connection, rmq_producer, schemas
from class_service import s3_util
from class_service.model import Multiclass, MulticlassConfig, get_class_codes
from config import get_settings


settings = get_settings()

logger = logging.getLogger(__name__)

# TODO: fetch config file from db server to support multiple models at production

config = MulticlassConfig()
models_dir = Path(__file__).parent.parent / "data" / "models"
class_model = Multiclass.from_pretrained(models_dir, config)


def process_message(message_body: schemas.ReqBody, task_id):
    s3_path = message_body.s3_path
    text = message_body.text
    if not text:
        # 1. download text file from s3 to local
        if not s3_path:
            logger.error("s3_path and text are both empty!")
            return {
                "text": "",
                "codes": "[]",
            }
        text = s3_util.download_s3_text_file(s3_path, task_id)

    result_labels, _ = get_class_codes(text, class_model)

    output_data = {
        "codes": result_labels,
    }

    return output_data


def start_main():
    basic_message_sender = rmq_connection.BasicMessageSender(
        settings.RMQ_BROKER_ID,
        settings.RMQ_USERNAME,
        settings.RMQ_PASSWORD,
        settings.RMQ_AWS_REGION,
    )

    basic_message_sender.channel.queue_declare(
        queue=settings.IP_QUEUE_NAME, durable=True
    )

    def callback(ch, method, properties, body):
        logger.info(f"Message received {body=}")
        try:
            message: schemas.MessageSchema = schemas.MessageSchema.parse_obj(
                json.loads(body)
            )
        except Exception as e:
            logger.exception(f"Wrong message format: {e}")
            # retry is handled on platform, therefore we just acknowlege this msg
            basic_message_sender.channel.basic_ack(
                delivery_tag=method.delivery_tag
            )
            return
        try:
            # notify processing to RMQ server
            res = schemas.ResponseSchema(
                job_status=constants.PROCESSING,
                task_id=message.task_id,
                job_id=message.job_id,
            )
            rmq_producer.send_status_and_data(res)
            start_time_utc = str(
                datetime.datetime.now(tz=datetime.timezone.utc)
            )
            # process message
            logger.info(
                f"Start processing task: {message.task_id}, {start_time_utc=}"
            )
            start_proc_time = time.perf_counter()
            output_data = process_message(message.req_body, message.task_id)
            proc_time = time.perf_counter() - start_proc_time
            complete_time_utc = str(
                datetime.datetime.now(tz=datetime.timezone.utc)
            )
            logger.info(
                f"Finish processing task: {message.task_id},"
                f" {complete_time_utc=}"
            )
            logger.info(
                f"Processing time of task: {message.task_id}, {proc_time=}"
            )
            res = schemas.ResponseSchema(
                job_status=constants.COMPLETED,
                task_id=message.task_id,
                job_id=message.job_id,
                output_data=output_data,
                processing_time_started=start_time_utc,
                processing_time_completed=complete_time_utc,
            )
            rmq_producer.send_status_and_data(res)
            logger.info(
                f"Responded to platform task: {message.task_id}, {output_data=}"
            )
        except Exception as e:
            # notify fail status to server
            logger.exception(f"Exception in processing message {e}")
            failure_log = traceback.format_exc()
            res = schemas.ResponseSchema(
                job_status=constants.FAILED,
                task_id=message.task_id,
                job_id=message.job_id,
                failure_info=failure_log,
            )
            rmq_producer.send_status_and_data(res)

        # TODO: Retry Mechanism either service side or platform side
        basic_message_sender.channel.basic_ack(delivery_tag=method.delivery_tag)

    basic_message_sender.channel.basic_qos(prefetch_count=1)
    basic_message_sender.channel.basic_consume(
        queue=settings.IP_QUEUE_NAME,
        on_message_callback=callback,
        auto_ack=False,
    )
    logger.info("Waiting for message")
    basic_message_sender.channel.start_consuming()


if __name__ == "__main__":
    logger.info(f"Start service: {settings.MODULE_NAME}")
    torch.set_num_threads(settings.NUM_THREADS)
    logger.info(
        "Setting service to use parallelization with"
        f" {settings.NUM_THREADS} cores"
    )

    try:
        start_main()
    except KeyboardInterrupt:
        print("Interrupted")
        try:
            import sys

            sys.exit(0)
        except SystemExit:
            os._exit(0)
