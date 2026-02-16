import pytest
from typing import Annotated, Any, List, Optional, Union

from ical.types.data_types import get_field_type_info, FieldTypeInfo


def test_basic_types() -> None:
    """Test get_field_type_info with basic types."""
    assert get_field_type_info(int) == FieldTypeInfo(
        annotation=int, is_repeated=False, is_optional=False
    )
    assert get_field_type_info(str) == FieldTypeInfo(
        annotation=str, is_repeated=False, is_optional=False
    )


def test_optional_types() -> None:
    """Test get_field_type_info with optional types."""
    assert get_field_type_info(Optional[int]) == FieldTypeInfo(
        annotation=int, is_repeated=False, is_optional=True
    )
    assert get_field_type_info(Union[str, None]) == FieldTypeInfo(
        annotation=str, is_repeated=False, is_optional=True
    )


def test_list_types() -> None:
    """Test get_field_type_info with list types."""
    assert get_field_type_info(list[int]) == FieldTypeInfo(
        annotation=int, is_repeated=True, is_optional=False
    )
    assert get_field_type_info(List[str]) == FieldTypeInfo(
        annotation=str, is_repeated=True, is_optional=False
    )


def test_annotated_types() -> None:
    """Test get_field_type_info with annotated types."""
    assert get_field_type_info(Annotated[int, "metadata"]) == FieldTypeInfo(
        annotation=int, is_repeated=False, is_optional=False
    )


def test_nested_optional_list() -> None:
    """Test get_field_type_info with Optional[list[...]] and list[Optional[...]]."""
    # Optional around list
    info = get_field_type_info(Optional[list[int]])
    assert info == FieldTypeInfo(annotation=int, is_repeated=True, is_optional=True)

    # List around Optional
    info = get_field_type_info(list[Optional[int]])
    assert info == FieldTypeInfo(annotation=int, is_repeated=True, is_optional=True)


def test_nested_annotated() -> None:
    """Test get_field_type_info with nested Annotated types."""
    assert get_field_type_info(Annotated[Optional[int], "metadata"]) == FieldTypeInfo(
        annotation=int, is_repeated=False, is_optional=True
    )
    assert get_field_type_info(Optional[Annotated[int, "metadata"]]) == FieldTypeInfo(
        annotation=int, is_repeated=False, is_optional=True
    )
    assert get_field_type_info(list[Annotated[int, "metadata"]]) == FieldTypeInfo(
        annotation=int, is_repeated=True, is_optional=False
    )
    assert get_field_type_info(Annotated[list[int], "metadata"]) == FieldTypeInfo(
        annotation=int, is_repeated=True, is_optional=False
    )


def test_complex_nesting() -> None:
    """Test get_field_type_info with complex nesting."""
    type_hint = Annotated[Optional[list[Annotated[int, "inner"]]], "outer"]
    assert get_field_type_info(type_hint) == FieldTypeInfo(
        annotation=int, is_repeated=True, is_optional=True
    )


def test_multi_type_union() -> None:
    """Test get_field_type_info with unions of multiple types."""
    type_hint = Union[int, str]
    # Should keep the Union as the annotation since it can't be unwrapped further to a single type
    assert get_field_type_info(type_hint) == FieldTypeInfo(
        annotation=type_hint, is_repeated=False, is_optional=False
    )

    type_hint_opt = Optional[Union[int, str]]
    assert get_field_type_info(type_hint_opt) == FieldTypeInfo(
        annotation=Union[int, str], is_repeated=False, is_optional=True
    )


def test_unsupported_bare_list() -> None:
    """Test get_field_type_info with a bare List."""
    with pytest.raises(ValueError, match="Unable to determine args of type"):
        get_field_type_info(List)
