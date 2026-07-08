"""Tests for ATTACH data types."""

import base64
from pydantic import Field, field_serializer
import pytest

from ical.component import ComponentModel
from ical.exceptions import CalendarParseError
from ical.parsing.component import ParsedComponent
from ical.parsing.property import ParsedProperty, ParsedPropertyParameter
from ical.types import Attachment, Uri
from ical.types.data_types import serialize_field


class FakeModel(ComponentModel):
    """Model under test."""

    attach: list[Attachment] = Field(default_factory=list)

    serialize_fields = field_serializer("*")(serialize_field)  # type: ignore[pydantic-field]


def test_uri_attachment() -> None:
    """Test parsing a simple URI attachment."""
    model = FakeModel.model_validate(
        {
            "attach": [
                ParsedProperty(
                    name="attach",
                    value="http://example.com/public/spec.pdf",
                )
            ]
        }
    )
    assert len(model.attach) == 1
    attachment = model.attach[0]
    assert attachment.uri == "http://example.com/public/spec.pdf"
    assert attachment.content is None
    assert attachment.fmttype is None


def test_uri_attachment_with_fmttype() -> None:
    """Test parsing a URI attachment with format type parameter."""
    model = FakeModel.model_validate(
        {
            "attach": [
                ParsedProperty(
                    name="attach",
                    value="http://example.com/public/spec.postscript",
                    params=[
                        ParsedPropertyParameter(
                            name="FMTTYPE", values=["application/postscript"]
                        )
                    ],
                )
            ]
        }
    )
    assert len(model.attach) == 1
    attachment = model.attach[0]
    assert attachment.uri == "http://example.com/public/spec.postscript"
    assert attachment.content is None
    assert attachment.fmttype == "application/postscript"


def test_binary_attachment() -> None:
    """Test parsing an inline binary attachment."""
    raw_data = b"hello binary world"
    base64_data = base64.b64encode(raw_data).decode("ascii")

    model = FakeModel.model_validate(
        {
            "attach": [
                ParsedProperty(
                    name="attach",
                    value=base64_data,
                    params=[
                        ParsedPropertyParameter(name="VALUE", values=["BINARY"]),
                        ParsedPropertyParameter(name="ENCODING", values=["BASE64"]),
                        ParsedPropertyParameter(name="FMTTYPE", values=["image/png"]),
                    ],
                )
            ]
        }
    )
    assert len(model.attach) == 1
    attachment = model.attach[0]
    assert attachment.uri is None
    assert attachment.content == raw_data
    assert attachment.fmttype == "image/png"
    assert attachment.value_attr == "BINARY"
    assert attachment.encoding == "BASE64"


def test_binary_attachment_with_newlines() -> None:
    """Test parsing an inline binary attachment with newlines/whitespace inside base64."""
    raw_data = b"hello binary world with multi-line base64 content"
    base64_data = base64.b64encode(raw_data).decode("ascii")
    # Insert newlines to simulate folding/whitespace in ICS
    spaced_base64 = "\n ".join(
        base64_data[i : i + 10] for i in range(0, len(base64_data), 10)
    )

    model = FakeModel.model_validate(
        {
            "attach": [
                ParsedProperty(
                    name="attach",
                    value=spaced_base64,
                    params=[
                        ParsedPropertyParameter(name="VALUE", values=["BINARY"]),
                        ParsedPropertyParameter(name="ENCODING", values=["BASE64"]),
                    ],
                )
            ]
        }
    )
    assert len(model.attach) == 1
    attachment = model.attach[0]
    assert attachment.uri is None
    assert attachment.content == raw_data


def test_invalid_binary_base64() -> None:
    """Test that invalid base64 content raises a validation error."""
    with pytest.raises(
        CalendarParseError, match="Failed to decode base64 binary attachment"
    ):
        FakeModel.model_validate(
            {
                "attach": [
                    ParsedProperty(
                        name="attach",
                        # Non-base64 characters that cause decode failure (standard base64 uses ASCII, e.g. control chars/invalid symbols)
                        value="!!!$$$###@@@invalid base64",
                        params=[
                            ParsedPropertyParameter(name="VALUE", values=["BINARY"]),
                            ParsedPropertyParameter(name="ENCODING", values=["BASE64"]),
                        ],
                    )
                ]
            }
        )


def test_encode_uri_attachment() -> None:
    """Test encoding a URI attachment."""
    model = FakeModel(
        attach=[
            Attachment(
                uri=Uri("http://example.com/public/spec.pdf"),
                fmttype="application/pdf",  # type: ignore
            )
        ]
    )
    assert model.__encode_component_root__() == ParsedComponent(
        name="FakeModel",
        properties=[
            ParsedProperty(
                name="attach",
                value="http://example.com/public/spec.pdf",
                params=[
                    ParsedPropertyParameter(name="FMTTYPE", values=["application/pdf"])
                ],
            )
        ],
    )


def test_encode_binary_attachment() -> None:
    """Test encoding a binary attachment."""
    raw_data = b"encoded binary world"
    base64_data = base64.b64encode(raw_data).decode("ascii")

    model = FakeModel(
        attach=[
            Attachment(
                content=raw_data,
                fmttype="image/png",  # type: ignore
            )
        ]
    )
    assert model.__encode_component_root__() == ParsedComponent(
        name="FakeModel",
        properties=[
            ParsedProperty(
                name="attach",
                value=base64_data,
                params=[
                    ParsedPropertyParameter(name="FMTTYPE", values=["image/png"]),
                    ParsedPropertyParameter(name="VALUE", values=["BINARY"]),
                    ParsedPropertyParameter(name="ENCODING", values=["BASE64"]),
                ],
            )
        ],
    )


def test_non_dict_validation() -> None:
    """Test validating a non-dictionary value raises validation error."""
    with pytest.raises(Exception):
        Attachment.model_validate("not a dict")


def test_serialize_content_none() -> None:
    """Test serializing content when it is None."""
    attachment = Attachment(uri=Uri("http://example.com"))
    data = attachment.model_dump()
    assert data["content"] is None


def test_encode_property_bytes() -> None:
    """Test encoding property when content is passed as raw bytes."""
    prop = Attachment.__encode_property__({"content": b"raw bytes"})
    assert prop.value == base64.b64encode(b"raw bytes").decode("ascii")


def test_encode_property_empty() -> None:
    """Test encoding property when both content and uri are None."""
    prop = Attachment.__encode_property__({})
    assert prop.value == ""
