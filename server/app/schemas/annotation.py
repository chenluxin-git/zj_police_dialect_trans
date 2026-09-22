"""T10 标注请求模型"""
from pydantic import BaseModel


class AnnotationCreate(BaseModel):
    file_id: int
    translation: str
