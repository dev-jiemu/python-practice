from typing import List, Optional
from pydantic import BaseModel, Field

class Segment(BaseModel):
    idx: int
    start_time: float = Field(alias="startTime")
    end_time: float = Field(alias="endTime")
    sentence: str

    class Config:
        populate_by_name = True



class TranscribeResponse(BaseModel):
    text: str
    segments: Optional[List[Segment]] = None

    class Config:
        populate_by_name = True