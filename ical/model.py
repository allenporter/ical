"""Library for pydantic models used for rfc5545 parsing."""

from pydantic import BaseModel, root_validator

from .validators import parse_extra_fields, parse_property_fields


class ComponentModel(BaseModel):
    """Abstract class for rfc5545 component model."""

    _parse_extra_fields = root_validator(pre=True, allow_reuse=True)(parse_extra_fields)
    _parse_property_fields = root_validator(pre=True, allow_reuse=True)(
        parse_property_fields
    )
