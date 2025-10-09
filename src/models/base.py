from pydantic import BaseModel, ConfigDict


def to_camel(snake_str: str) -> str:
    components = snake_str.split("_")
    return components[0] + "".join(x.title() for x in components[1:])


class CamelCaseModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
