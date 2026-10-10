"""Remove people's names from call texts: inPA titles and descriptions sometimes name a
research grant's tutor or scientific lead, or the official signing the call. The call stays
useful without them, and the official page keeps the full text."""
import re

W = r"(?:[A-ZÀ-Ý][a-zà-ÿ'’]+|[A-ZÀ-Ý]{2,}(?=[\s,.;:)–-]|$))"  # Name or NAME
T = r"[A-ZÀ-Ý][a-zà-ÿ'’]+"  # Name only
PART = r"(?:de|De|di|Di|del|Del|della|Della|La|Lo|D'|D’)"
NAME = rf"{W}(?:\s+(?:{PART}\s*)?{W}){{1,3}}"
TNAME = rf"{T}(?:\s+(?:{PART}\s*)?{T}){{1,3}}"
HON = r"(?i:dott\.(?:ssa)?|dott\.?ssa|dr\.(?:ssa)?|prof\.(?:ssa)?|prof\.?ssa|ing\.|arch\.|avv\.|geom\.|sig\.(?:ra)?)"
ROLE = (r"(?:[Rr]esponsabile [Ss]cientific[oa]|RESPONSABILE SCIENTIFICO|[Tt]utor|TUTOR|P\.\s?I\.|[Pp]rincipal [Ii]nvestigator"
        r"|[Ss]upervisore|[Rr]eferente [Ss]cientific[oa]|[Rr]esponsabile del (?:procedimento|progetto)|RUP)")
# an honorific makes any capitalised words a name; a role alone only Title Case ones ("TUTOR DIDATTICO" stays)
RX = re.compile(rf"\b(?:((?:{ROLE}[\s:,–-]*)?{HON}\s+){NAME}|({ROLE}[\s:,–-]+){TNAME})")
OMIT = "[nome omesso]"


def redact(text):
    return RX.sub(lambda m: (m.group(1) or m.group(2)).rstrip() + " " + OMIT, text) if text else text
