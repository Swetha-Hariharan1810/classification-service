from typing import Optional, Dict
from config import get_settings
from pydantic import BaseModel

settings = get_settings()


class ReqBody(BaseModel):
    s3_path: Optional[str] = None
    text: Optional[str] = None


class MessageSchema(BaseModel):
    req_body: ReqBody
    job_id: int
    task_id: int


class ResponseSchema(BaseModel):
    job_status: str
    job_id: int
    task_id: int
    module: Optional[str] = settings.MODULE_NAME
    failure_info: Optional[str] = None
    processing_time_started: Optional[str] = None
    processing_time_completed: Optional[str] = None
    output_data: Optional[Dict] = None
