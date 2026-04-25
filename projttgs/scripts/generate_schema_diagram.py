from __future__ import annotations

import argparse
import html
import re
import sqlite3
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Column:
    name: str
    raw_type: str
    is_pk: bool
    not_null: bool


@dataclass
class ForeignKey:
    from_column: str
    to_table: str
    to_column: str


@dataclass
class TableLayout:
    x: int
    y: int
    width: int
    height: int


def sanitize(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if cleaned and cleaned[0].isdigit():
        cleaned = f"t_{cleaned}"
    return cleaned


def load_schema(conn: sqlite3.Connection) -> tuple[dict[str, list[Column]], dict[str, list[ForeignKey]]]:
    table_rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()

    columns_by_table: dict[str, list[Column]] = {}
    fks_by_table: dict[str, list[ForeignKey]] = {}

    for (table_name,) in table_rows:
        column_rows = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        fk_rows = conn.execute(f'PRAGMA foreign_key_list("{table_name}")').fetchall()

        columns_by_table[table_name] = [
            Column(
                name=row[1],
                raw_type=row[2] or "TEXT",
                not_null=bool(row[3]),
                is_pk=bool(row[5]),
            )
            for row in column_rows
        ]
        fks_by_table[table_name] = [
            ForeignKey(from_column=row[3], to_table=row[2], to_column=row[4]) for row in fk_rows
        ]

    return columns_by_table, fks_by_table


def pick_tables(
    columns_by_table: dict[str, list[Column]],
    fks_by_table: dict[str, list[ForeignKey]],
    mode: str,
) -> list[str]:
    if mode == "full":
        return sorted(columns_by_table)

    selected = {
        name
        for name in columns_by_table
        if name.startswith("ttgen_") or name.startswith("user_account_")
    }

    queue = list(selected)
    while queue:
        table = queue.pop()
        for fk in fks_by_table.get(table, []):
            if fk.to_table not in selected:
                selected.add(fk.to_table)
                queue.append(fk.to_table)

    return sorted(selected)


def order_tables(chosen_tables: list[str], mode: str) -> list[str]:
    if mode != "app":
        return sorted(chosen_tables)

    preferred = [
        "auth_user",
        "ttgen_department",
        "ttgen_course",
        "ttgen_section",
        "ttgen_instructor",
        "ttgen_room",
        "ttgen_meetingtime",
        "ttgen_savedtimetable",
        "ttgen_scheduledslot",
        "ttgen_course_instructors",
        "ttgen_section_allowed_courses",
        "ttgen_teachersection",
        "ttgen_scheduledslot_lab_slots",
        "ttgen_profile",
        "ttgen_useraccessplan",
        "user_account_profile",
    ]
    rank = {name: index for index, name in enumerate(preferred)}
    return sorted(chosen_tables, key=lambda name: (rank.get(name, len(preferred)), name))


def format_column(column: Column) -> str:
    bits = [column.raw_type.lower(), column.name]
    if column.is_pk:
        bits.append("PK")
    if column.not_null and not column.is_pk:
        bits.append("NOT NULL")
    return " ".join(bits)


def format_svg_column(column: Column) -> str:
    suffixes = []
    if column.is_pk:
        suffixes.append("PK")
    if column.not_null and not column.is_pk:
        suffixes.append("NN")
    suffix = f" [{' '.join(suffixes)}]" if suffixes else ""
    return f"{column.name} : {column.raw_type.lower()}{suffix}"


def build_mermaid(
    columns_by_table: dict[str, list[Column]],
    fks_by_table: dict[str, list[ForeignKey]],
    mode: str,
) -> str:
    chosen_tables = order_tables(pick_tables(columns_by_table, fks_by_table, mode), mode)
    chosen_set = set(chosen_tables)
    alias_map = {table: sanitize(table) for table in chosen_tables}

    lines = ["erDiagram"]

    for table in chosen_tables:
        lines.append(f"    {alias_map[table]} {{")
        for column in columns_by_table[table]:
            lines.append(f"        {format_column(column)}")
        lines.append("    }")

    seen_edges: set[tuple[str, str, str]] = set()
    for from_table in chosen_tables:
        for fk in fks_by_table.get(from_table, []):
            if fk.to_table not in chosen_set:
                continue

            edge = (from_table, fk.to_table, fk.from_column)
            if edge in seen_edges:
                continue
            seen_edges.add(edge)

            left = alias_map[fk.to_table]
            right = alias_map[from_table]
            label = f"{fk.to_column} <- {fk.from_column}"
            lines.append(f"    {left} ||--o{{ {right} : \"{label}\"")

    lines.append("")
    lines.append("%% Table aliases")
    for table in chosen_tables:
        lines.append(f"%% {alias_map[table]} = {table}")

    return "\n".join(lines) + "\n"


def estimate_table_size(table_name: str, columns: list[Column]) -> tuple[int, int]:
    max_chars = max([len(table_name), *[len(format_svg_column(column)) for column in columns]])
    width = max(240, min(440, 26 + max_chars * 7))
    height = 48 + len(columns) * 20 + 16
    return width, height


def build_layout(
    chosen_tables: list[str],
    columns_by_table: dict[str, list[Column]],
    mode: str,
) -> tuple[dict[str, TableLayout], int, int]:
    column_count = 4 if mode == "app" else 5
    top_padding = 120
    side_padding = 40
    gap_x = 80
    gap_y = 60

    sizes = {table: estimate_table_size(table, columns_by_table[table]) for table in chosen_tables}
    placements: dict[str, tuple[int, int]] = {}
    col_widths = [0] * column_count
    row_heights: list[int] = []

    for index, table in enumerate(chosen_tables):
        row = index // column_count
        col = index % column_count
        placements[table] = (row, col)
        width, height = sizes[table]
        col_widths[col] = max(col_widths[col], width)
        while len(row_heights) <= row:
            row_heights.append(0)
        row_heights[row] = max(row_heights[row], height)

    x_positions: list[int] = []
    cursor_x = side_padding
    for width in col_widths:
        x_positions.append(cursor_x)
        cursor_x += width + gap_x

    y_positions: list[int] = []
    cursor_y = top_padding
    for height in row_heights:
        y_positions.append(cursor_y)
        cursor_y += height + gap_y

    layout: dict[str, TableLayout] = {}
    for table, (row, col) in placements.items():
        width, height = sizes[table]
        x = x_positions[col] + (col_widths[col] - width) // 2
        y = y_positions[row]
        layout[table] = TableLayout(x=x, y=y, width=width, height=height)

    canvas_width = side_padding + sum(col_widths) + gap_x * (column_count - 1) + side_padding
    canvas_height = top_padding + sum(row_heights) + gap_y * max(0, len(row_heights) - 1) + 60
    return layout, canvas_width, canvas_height


def classify_table(table_name: str, columns: list[Column], fks: list[ForeignKey]) -> tuple[str, str]:
    if table_name == "auth_user":
        return "#dbeafe", "#1d4ed8"
    if table_name.startswith("auth_") or table_name.startswith("django_") or table_name.startswith("account_") or table_name.startswith("socialaccount_"):
        return "#e0f2fe", "#0369a1"
    if len(columns) <= 3 and len(fks) >= 2:
        return "#ede9fe", "#6d28d9"
    return "#fff7ed", "#c2410c"


def edge_points(parent: TableLayout, child: TableLayout) -> list[tuple[int, int]]:
    parent_cx = parent.x + parent.width // 2
    parent_cy = parent.y + parent.height // 2
    child_cx = child.x + child.width // 2
    child_cy = child.y + child.height // 2

    if abs(child_cx - parent_cx) >= abs(child_cy - parent_cy):
        if child_cx >= parent_cx:
            start = (parent.x + parent.width, parent_cy)
            end = (child.x, child_cy)
        else:
            start = (parent.x, parent_cy)
            end = (child.x + child.width, child_cy)
        mid_x = (start[0] + end[0]) // 2
        return [start, (mid_x, start[1]), (mid_x, end[1]), end]

    if child_cy >= parent_cy:
        start = (parent_cx, parent.y + parent.height)
        end = (child_cx, child.y)
    else:
        start = (parent_cx, parent.y)
        end = (child_cx, child.y + child.height)
    mid_y = (start[1] + end[1]) // 2
    return [start, (start[0], mid_y), (end[0], mid_y), end]


def polyline_path(points: list[tuple[int, int]]) -> str:
    return " ".join(f"{x},{y}" for x, y in points)


def svg_text(x: int, y: int, text: str, *, size: int = 14, weight: str = "400", fill: str = "#0f172a") -> str:
    escaped = html.escape(text)
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
        f'fill="{fill}" font-family="Segoe UI, Arial, sans-serif">{escaped}</text>'
    )


def build_svg(
    columns_by_table: dict[str, list[Column]],
    fks_by_table: dict[str, list[ForeignKey]],
    mode: str,
) -> str:
    chosen_tables = order_tables(pick_tables(columns_by_table, fks_by_table, mode), mode)
    chosen_set = set(chosen_tables)
    layout, canvas_width, canvas_height = build_layout(chosen_tables, columns_by_table, mode)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_width}" height="{canvas_height}" viewBox="0 0 {canvas_width} {canvas_height}">',
        "<defs>",
        '<marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">',
        '<polygon points="0 0, 10 3.5, 0 7" fill="#64748b" />',
        "</marker>",
        '<filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">',
        '<feDropShadow dx="0" dy="4" stdDeviation="5" flood-color="#94a3b8" flood-opacity="0.25" />',
        "</filter>",
        "</defs>",
        f'<rect width="{canvas_width}" height="{canvas_height}" fill="#f8fafc" />',
        f'<text x="40" y="50" font-size="28" font-weight="700" fill="#0f172a" font-family="Segoe UI, Arial, sans-serif">{"App Schema" if mode == "app" else "Full Database Schema"}</text>',
        f'<text x="40" y="78" font-size="14" fill="#475569" font-family="Segoe UI, Arial, sans-serif">Generated from db.sqlite3 on {generated_at}</text>',
        '<text x="40" y="98" font-size="13" fill="#64748b" font-family="Segoe UI, Arial, sans-serif">Lines point from referenced table to the table containing the foreign key.</text>',
    ]

    for from_table in chosen_tables:
        for fk in fks_by_table.get(from_table, []):
            if fk.to_table not in chosen_set:
                continue
            parent = layout[fk.to_table]
            child = layout[from_table]
            points = edge_points(parent, child)
            tooltip = html.escape(f"{fk.to_table}.{fk.to_column} -> {from_table}.{fk.from_column}")
            parts.append(
                f'<polyline points="{polyline_path(points)}" fill="none" stroke="#94a3b8" stroke-width="2.2" marker-end="url(#arrowhead)">'
                f"<title>{tooltip}</title>"
                "</polyline>"
            )

    for table in chosen_tables:
        table_layout = layout[table]
        columns = columns_by_table[table]
        background, accent = classify_table(table, columns, fks_by_table.get(table, []))
        header_height = 38
        parts.append(
            f'<g filter="url(#shadow)">'
            f'<rect x="{table_layout.x}" y="{table_layout.y}" width="{table_layout.width}" height="{table_layout.height}" rx="14" fill="{background}" stroke="#cbd5e1" stroke-width="1.5" />'
            f'<rect x="{table_layout.x}" y="{table_layout.y}" width="{table_layout.width}" height="{header_height}" rx="14" fill="{accent}" />'
            f'<rect x="{table_layout.x}" y="{table_layout.y + header_height - 14}" width="{table_layout.width}" height="14" fill="{accent}" />'
            "</g>"
        )
        parts.append(svg_text(table_layout.x + 16, table_layout.y + 25, table, size=16, weight="700", fill="#ffffff"))

        y = table_layout.y + 60
        for column in columns:
            parts.append(svg_text(table_layout.x + 16, y, format_svg_column(column), size=13))
            y += 20

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def detect_output_format(out_path: Path, explicit_format: str | None) -> str:
    if explicit_format:
        return explicit_format
    if out_path.suffix.lower() == ".svg":
        return "svg"
    return "mermaid"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate schema diagrams from a SQLite database.")
    parser.add_argument("--db", default="db.sqlite3", help="Path to the SQLite database file.")
    parser.add_argument(
        "--mode",
        choices=("app", "full"),
        default="app",
        help="Generate either the app-focused or full-database diagram.",
    )
    parser.add_argument(
        "--format",
        choices=("mermaid", "svg"),
        help="Output format. If omitted, the format is inferred from the output file extension.",
    )
    parser.add_argument("--out", required=True, help="Output .mmd file path.")
    args = parser.parse_args()

    db_path = Path(args.db)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    output_format = detect_output_format(out_path, args.format)

    with sqlite3.connect(db_path) as conn:
        columns_by_table, fks_by_table = load_schema(conn)

    if output_format == "svg":
        content = build_svg(columns_by_table, fks_by_table, args.mode)
    else:
        content = build_mermaid(columns_by_table, fks_by_table, args.mode)
    out_path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
