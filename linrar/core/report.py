"""Archive report generation: WinRAR's Tools > Generate report."""

from __future__ import annotations

import csv
import html
import io
import os
from datetime import datetime
from typing import Iterable

from .models import ArchiveInfo, format_size, format_size_short


def _rows(info: ArchiveInfo, include_folders: bool) -> Iterable[list[str]]:
    for entry in sorted(info.entries, key=lambda e: e.name.lower()):
        if entry.is_dir and not include_folders:
            continue
        yield [
            entry.name,
            "" if entry.is_dir else str(entry.size),
            "" if entry.is_dir else str(entry.packed_size),
            "" if entry.is_dir else f"{entry.ratio}%",
            entry.mtime.strftime("%Y-%m-%d %H:%M:%S") if entry.mtime else "",
            entry.crc,
            entry.attributes,
            "Yes" if entry.encrypted else "",
        ]


HEADERS = [
    "Name", "Size", "Packed", "Ratio", "Modified", "CRC32", "Attributes",
    "Encrypted",
]


def as_text(info: ArchiveInfo, include_folders: bool = True) -> str:
    """A fixed-width listing, closest to WinRAR's plain report."""
    rows = list(_rows(info, include_folders))
    widths = [len(h) for h in HEADERS]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    out = io.StringIO()
    out.write(f"Archive report: {info.path}\n")
    out.write(f"Generated:      {datetime.now():%Y-%m-%d %H:%M:%S}\n")
    out.write(f"Format:         {info.format.label}\n")
    if info.detail_line:
        out.write(f"Details:        {info.detail_line}\n")
    out.write(f"Files:          {info.file_count}\n")
    out.write(f"Folders:        {info.folder_count}\n")
    out.write(f"Total size:     {format_size(info.total_size)} bytes\n")
    out.write(f"Packed size:    {format_size(info.total_packed)} bytes\n")
    out.write(f"Ratio:          {info.ratio}%\n")
    if info.comment:
        out.write(f"\nComment:\n{info.comment}\n")
    out.write("\n")

    line = "  ".join(header.ljust(widths[i]) for i, header in enumerate(HEADERS))
    out.write(line.rstrip() + "\n")
    out.write("-" * len(line.rstrip()) + "\n")
    for row in rows:
        out.write(
            "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip()
            + "\n"
        )
    return out.getvalue()


def as_csv(info: ArchiveInfo, include_folders: bool = True) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(HEADERS)
    for row in _rows(info, include_folders):
        writer.writerow(row)
    return out.getvalue()


def as_html(info: ArchiveInfo, include_folders: bool = True) -> str:
    esc = html.escape
    rows = list(_rows(info, include_folders))
    body = "\n".join(
        "<tr>"
        + "".join(
            f'<td class="{"num" if i in (1, 2, 3) else ""}">{esc(cell)}</td>'
            for i, cell in enumerate(row)
        )
        + "</tr>"
        for row in rows
    )
    headers = "".join(f"<th>{esc(h)}</th>" for h in HEADERS)
    comment = (
        f"<h2>Comment</h2><pre>{esc(info.comment)}</pre>" if info.comment else ""
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>Archive report: {esc(os.path.basename(info.path))}</title>
<style>
 body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #222; }}
 h1 {{ font-size: 1.3rem; }}
 table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; }}
 th, td {{ border: 1px solid #ccc; padding: 4px 8px; text-align: left; }}
 th {{ background: #eef2f7; }}
 td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
 tr:nth-child(even) td {{ background: #fafbfc; }}
 dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 2px 12px; }}
 dt {{ font-weight: 600; }}
 pre {{ background: #f6f8fa; padding: 8px; overflow-x: auto; }}
</style></head><body>
<h1>Archive report: {esc(os.path.basename(info.path))}</h1>
<dl>
 <dt>Path</dt><dd>{esc(info.path)}</dd>
 <dt>Generated</dt><dd>{datetime.now():%Y-%m-%d %H:%M:%S}</dd>
 <dt>Format</dt><dd>{esc(info.format.label)}</dd>
 <dt>Details</dt><dd>{esc(info.detail_line or '-')}</dd>
 <dt>Files</dt><dd>{info.file_count}</dd>
 <dt>Folders</dt><dd>{info.folder_count}</dd>
 <dt>Total size</dt><dd>{format_size(info.total_size)} bytes
   ({format_size_short(info.total_size)})</dd>
 <dt>Packed size</dt><dd>{format_size(info.total_packed)} bytes
   ({format_size_short(info.total_packed)})</dd>
 <dt>Ratio</dt><dd>{info.ratio}%</dd>
</dl>
{comment}
<h2>Contents</h2>
<table><thead><tr>{headers}</tr></thead><tbody>
{body}
</tbody></table>
</body></html>
"""


FORMATS = {
    "Text (*.txt)": ("txt", as_text),
    "CSV spreadsheet (*.csv)": ("csv", as_csv),
    "HTML page (*.html)": ("html", as_html),
}
