"""Constants for ical parsing library."""

# Related to rfc5545 text parsing
FOLD = r"\r?\n[ |\t]"
FOLD_LEN = 75
FOLD_INDENT = " "
WSP = [" ", "\t"]
ATTR_BEGIN = "BEGIN"
ATTR_END = "END"

ATTR_BEGIN_LOWER = "begin"
ATTR_END_LOWER = "end"
