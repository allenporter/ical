"""Character sets used inused in rfc5545.

This file defines the character sets used by pyparsing to tokenize
input files, intended to be used by the contentlines parsing code.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import cast

from pyparsing import unicode_set
from pyparsing.unicode import UnicodeRangeList, pyparsing_unicode

from .emoji import EMOJI

_LOGGER = logging.getLogger(__name__)


WSP = [" ", "\t"]


class CharRange(unicode_set):
    """A base class that returns all characters in a range."""

    @classmethod
    def all(cls) -> list[str]:
        """Return all characters from the range."""
        return cast(list[str], cls._chars_for_ranges)


class Control(CharRange):
    """All the controls excet HTAB."""

    _ranges: UnicodeRangeList = [
        (0x00, 0x08),
        (0x0A, 0x1F),
        (0x7F,),
    ]


class BasicMultilingualPlane(CharRange):
    """Unicode set for the Basic Multilingual Plane."""

    _ranges: UnicodeRangeList = [
        (0x0020, 0xFFFF),
    ]


NON_US_ASCII =  unicode_set.identchars + "".join(EMOJI)

# Characters that should be encoded in quotes
UNSAFE_CHAR_RE = re.compile(r"[,:;]")


class SafeChar(CharRange):
    """Any character except CONTROL, DQUOTE, ";", ":", ","."""

    _ranges: UnicodeRangeList = [
        (0x21,),  # Control charts before 0x21. 0x22 is "
        (0x23, 0x2B),  # 0x2C is ,
        (0x2D, 0x39),  # 0x3A is : and 0x3B is ;
        (0x3C, 0x7E),  # 0x7E is DEL (control)
    ]


SAFE_CHAR = "".join(WSP + SafeChar.all()) + NON_US_ASCII


class ValueChar(CharRange):
    """Any textual character."""

    _ranges: UnicodeRangeList = [
        (0x21, 0x7E),
    ]


VALUE_CHAR = "".join(
    WSP + ValueChar.all() + BasicMultilingualPlane.all()
) + NON_US_ASCII
