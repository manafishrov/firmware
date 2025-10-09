from pydantic import BaseModel, ConfigDict
from ..utils import to_camel


class CamelCaseModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
