"""A pyparsing text parser for rfc5545 files.

This is a very simple parser that converts lines in an iCalendar file into a an object
structure with necessary relationships to interpret the meaning of the contentlines and
how the parts break down into properties and parameters. This library does not attempt
to interpret the meaning of the properties or types themselves.

For example, given a content line of:

  DUE;VALUE=DATE:20070501

This library would create a ParseResults object with this structure:

  {
    'name': 'DUE',
    'value': '20070501'
    'params': [{
            'param_name': 'VALUE',
            'param_value': 'DATE',
    }]
  }

Note: This specific example may be a bit confusing because one of the property parameters is named
"VALUE" which refers to the value type.
"""

import logging
import threading
from functools import cache
from typing import cast
from typing import Iterable

from pyparsing import (
    Combine,
    Group,
    Or,
    ParserElement,
    ParseResults,
    QuotedString,
    Word,
    ZeroOrMore,
    alphanums,
    alphas,
    nums,
)

from .const import (
    PARSE_NAME,
    PARSE_PARAM_NAME,
    PARSE_PARAM_VALUE,
    PARSE_PARAMS,
    PARSE_VALUE,
)
from .unicode import SAFE_CHAR, VALUE_CHAR

_LOGGER = logging.getLogger(__name__)


@cache
def _create_parser() -> ParserElement:
    """Create rfc5545 parser."""
    iana_token = Word(alphanums + "-")
    vendor_id = Word(alphanums)
    x_name = Combine("X-" + ZeroOrMore(vendor_id + "-") + alphas + nums + "-")
    name = Or([iana_token, x_name])

    param_name = Or([iana_token, x_name])
    # rfc5545 Q-SAFE-CHAR is any character except CONTROL and DQUOTE which is
    # close enough to the pyparsing provided parser element
    param_text = Word(SAFE_CHAR) | ""
    quoted_string = QuotedString('"')

    param_value = Or([param_text, quoted_string])
    # There are multiple levels of property parameter grouping since there can
    # either be repreated property parameters with the same name or property
    # s parameters with repeated values. A two level structure is used to grab
    # both, which is then flattened when consuming the result.
    param = Group(
        param_name.set_results_name(PARSE_PARAM_NAME)
        + "="
        + param_value.set_results_name(PARSE_PARAM_VALUE, list_all_matches=True)
        + ZeroOrMore(
            "," + param_value.set_results_name(PARSE_PARAM_VALUE, list_all_matches=True)
        )
    ).set_results_name(PARSE_PARAMS, list_all_matches=True)

    contentline = (
        name.set_results_name(PARSE_NAME)
        + Group(ZeroOrMore(";" + param)).set_results_name(
            PARSE_PARAMS, list_all_matches=True
        )
        + ":"
        + Word(VALUE_CHAR)[0, 1].set_results_name(PARSE_VALUE)
    )
    contentline.set_whitespace_chars("")
    if _LOGGER.isEnabledFor(logging.DEBUG):
        contentline.set_debug(flag=True)
    return cast(ParserElement, contentline)


_parser_lock = threading.Lock()


def parse_contentlines(lines: Iterable[str]) -> list[ParseResults]:
    """Parse a set of unfolded lines into parse results.

    Note, this method is not threadsafe and may be called from only one method at a time.
    """
    with _parser_lock:
        parser = _create_parser()
        return [parser.parse_string(line, parse_all=True) for line in lines if line]
