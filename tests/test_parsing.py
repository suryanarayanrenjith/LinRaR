"""Parsing what the command line tools print, across tool versions.

These need no tools installed: they feed recorded output straight to the
parsers. That matters because tool *versions* differ between distributions —
unrar 7 labels the comment block where unrar 6 printed it bare, and a machine
with only one of them installed cannot catch the other's shape.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from linrar.core.backends.rar import RarBackend, _clean_comment
from linrar.core.models import ArchiveFormat
from linrar.core.process import LineAssembler, parse_file_line, parse_percent

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ok  {name}")
    else: FAIL += 1; print(f"FAIL  {name}  {extra}")

# ---------------------------------------------------------------- comments

print("== comment block")
# unrar 6.x: the comment is printed on its own, before the Archive: header.
UNRAR6 = """A test comment

Archive: /tmp/t.rar
Details: RAR 5

        Name: a.txt
        Type: File
        Size: 12
 Packed size: 12
"""
# unrar 7.x: the same, with a heading above it.
UNRAR7 = """Archive comment:
A test comment

Archive: /tmp/t.rar
Details: RAR 5

        Name: a.txt
        Type: File
        Size: 12
 Packed size: 12
"""
NO_COMMENT = """
Archive: /tmp/t.rar
Details: RAR 5

        Name: a.txt
        Type: File
        Size: 12
 Packed size: 12
"""

for label, output in (("unrar 6", UNRAR6), ("unrar 7", UNRAR7)):
    info = RarBackend._parse_listing(output, "/tmp/t.rar")
    check(f"{label}: comment read without its heading",
          info.comment == "A test comment", repr(info.comment))
    check(f"{label}: entries still parsed",
          [e.name for e in info.entries] == ["a.txt"],
          [e.name for e in info.entries])
    check(f"{label}: format detected", info.format is ArchiveFormat.RAR5)

info = RarBackend._parse_listing(NO_COMMENT, "/tmp/t.rar")
check("no comment stays empty", info.comment == "", repr(info.comment))

MULTILINE = """Archive comment:
line one
line two

Archive: /tmp/t.rar
Details: RAR 5
"""
check("multi-line comment kept whole",
      RarBackend._parse_listing(MULTILINE, "/tmp/t.rar").comment
      == "line one\nline two",
      repr(RarBackend._parse_listing(MULTILINE, "/tmp/t.rar").comment))

check("a heading alone means no comment", _clean_comment("Archive comment:") == "")
check("blank lines trimmed", _clean_comment("\n\n  hello  \n\n") == "hello")
check("a comment that mentions the word survives",
      _clean_comment("see the archive comment: below") ==
      "see the archive comment: below")
# Only unrar's exact heading is dropped: someone's own "Comment:" line is text.
check("a user's own Comment: line is kept",
      _clean_comment("Comment:\nmine") == "Comment:\nmine",
      repr(_clean_comment("Comment:\nmine")))

# ---------------------------------------------------------------- progress

print("== rar's terminal output")
assembler = LineAssembler()
# rar rewrites the percentage in place with backspaces, never a newline.
events = assembler.feed("Adding    big.bin      1%\b\b\b 42%\b\b\b\b100%\n")
final = [line for line, done in events if done]
check("backspaces replayed", final and final[-1].endswith("100%"), final)
check("percent read from the rendered line", parse_percent(final[-1]) == 100)
check("carriage return restarts the line",
      [l for l, d in LineAssembler().feed("stale\rfresh\n") if d] == ["fresh"])
check("file line parsed",
      parse_file_line("Adding    photos/a.jpg") == ("Adding", "photos/a.jpg"),
      parse_file_line("Adding    photos/a.jpg"))
check("extracting parsed too",
      parse_file_line("Extracting  sub/deep.txt     OK")[1] == "sub/deep.txt")
check("plain text is not a file line", parse_file_line("All OK") is None)
check("no percentage in plain text", parse_percent("All OK") is None)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
