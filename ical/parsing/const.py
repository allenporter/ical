"""Constants for ical parsing library."""

# Related to rfc5545 text parsing
FOLD = r"\r?\n[ |\t]"
FOLD_LEN = 75
FOLD_INDENT = " "
WSP = [" ", "\t"]
ATTR_BEGIN = "BEGIN"
ATTR_END = "END"

# Key/value pairs for the pyparsing result object and related dicts
PARSE_NAME = "name"
PARSE_VALUE = "value"
PARSE_PARAMS = "params"
PARSE_PARAM_NAME = "param_name"
PARSE_PARAM_VALUE = "param_value"
