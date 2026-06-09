"""
Wraps every op.add_column, op.drop_column, op.create_table, op.drop_table,
and op.drop_constraint call in an existence check so migrations are idempotent.

Run from your project root:
    python fix_all_migrations.py

Then:
    alembic upgrade head
"""

import os
import re

VERSIONS_DIR = "alembic/versions"

GUARD_HEADER = """\
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    def get_cols(table):
        if table not in existing_tables:
            return []
        return [c['name'] for c in inspector.get_columns(table)]

    def get_fks(table):
        if table not in existing_tables:
            return []
        return [f['name'] for f in inspector.get_foreign_keys(table)]

    def get_indexes(table):
        if table not in existing_tables:
            return []
        return [i['name'] for i in inspector.get_indexes(table)]

"""

def already_patched(content):
    return "existing_tables = inspector.get_table_names()" in content

def patch_upgrade_body(body):
    lines = body.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip blank / comment lines as-is
        if not stripped or stripped.startswith("#"):
            out.append(line)
            i += 1
            continue

        indent = len(line) - len(line.lstrip())
        pad = " " * indent

        # op.create_table("name", ...)
        m = re.match(r'\s*op\.create_table\(\s*["\'](\w+)["\']', line)
        if m:
            table = m.group(1)
            # collect full call (may span multiple lines)
            call_lines, i = collect_call(lines, i)
            out.append(f"{pad}if '{table}' not in existing_tables:")
            for cl in call_lines:
                out.append("    " + cl)
            continue

        # op.drop_table("name")
        m = re.match(r'\s*op\.drop_table\(\s*["\'](\w+)["\']', line)
        if m:
            table = m.group(1)
            call_lines, i = collect_call(lines, i)
            out.append(f"{pad}if '{table}' in existing_tables:")
            for cl in call_lines:
                out.append("    " + cl)
            continue

        # op.add_column("table", sa.Column("colname", ...))
        m = re.match(r'\s*op\.add_column\(\s*["\'](\w+)["\']', line)
        if m:
            table = m.group(1)
            call_lines, i = collect_call(lines, i)
            # try to extract column name
            full = " ".join(cl.strip() for cl in call_lines)
            cm = re.search(r'sa\.Column\(\s*["\'](\w+)["\']', full)
            col = cm.group(1) if cm else None
            if col:
                out.append(f"{pad}if '{col}' not in get_cols('{table}'):")
            else:
                out.append(f"{pad}if True:  # add_column guard (col name not detected)")
            for cl in call_lines:
                out.append("    " + cl)
            continue

        # op.drop_column("table", "col")
        m = re.match(r'\s*op\.drop_column\(\s*["\'](\w+)["\']\s*,\s*["\'](\w+)["\']', line)
        if m:
            table, col = m.group(1), m.group(2)
            call_lines, i = collect_call(lines, i)
            out.append(f"{pad}if '{col}' in get_cols('{table}'):")
            for cl in call_lines:
                out.append("    " + cl)
            continue

        # op.drop_constraint("name", "table", ...)
        m = re.match(r'\s*op\.drop_constraint\(\s*["\'](\w+)["\']', line)
        if m:
            constraint = m.group(1)
            # get table from second arg
            tm = re.search(r'op\.drop_constraint\(\s*["\'](\w+)["\']\s*,\s*["\'](\w+)["\']', line)
            table = tm.group(2) if tm else None
            call_lines, i = collect_call(lines, i)
            if table:
                out.append(f"{pad}if '{constraint}' in get_fks('{table}'):")
            else:
                out.append(f"{pad}if True:  # drop_constraint guard")
            for cl in call_lines:
                out.append("    " + cl)
            continue

        # op.create_index(op.f("name"), "table", ...)
        m = re.match(r'\s*op\.create_index\(\s*op\.f\(\s*["\'](\w+)["\']', line)
        if m:
            idx = m.group(1)
            tm = re.search(r'op\.create_index\([^,]+,\s*["\'](\w+)["\']', line)
            table = tm.group(1) if tm else None
            call_lines, i = collect_call(lines, i)
            if table:
                out.append(f"{pad}if '{idx}' not in get_indexes('{table}'):")
            else:
                out.append(f"{pad}if True:  # create_index guard")
            for cl in call_lines:
                out.append("    " + cl)
            continue

        out.append(line)
        i += 1

    return "\n".join(out)


def collect_call(lines, i):
    """Collect lines of a single op.xxx(...) call, handling multiline."""
    collected = []
    depth = 0
    while i < len(lines):
        line = lines[i]
        collected.append(line)
        depth += line.count("(") - line.count(")")
        i += 1
        if depth <= 0:
            break
    return collected, i


def patch_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    if already_patched(content):
        print(f"  SKIP (already patched): {os.path.basename(filepath)}")
        return

    # Find upgrade function
    match = re.search(
        r"(def upgrade\(\) -> None:\n)(.*?)(?=\ndef downgrade|\Z)",
        content,
        re.DOTALL,
    )
    if not match:
        print(f"  SKIP (no upgrade fn):   {os.path.basename(filepath)}")
        return

    fn_def = match.group(1)
    body = match.group(2)

    # Check if body is just a pass or comment
    stripped_body = body.strip()
    if stripped_body in ("", "pass", "# ### end Alembic commands ###"):
        print(f"  SKIP (empty body):      {os.path.basename(filepath)}")
        return

    patched_body = GUARD_HEADER + patch_upgrade_body(body)
    new_content = (
        content[: match.start()]
        + fn_def
        + patched_body
        + content[match.end() :]
    )

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"  PATCHED:                {os.path.basename(filepath)}")


def main():
    print(f"Scanning {VERSIONS_DIR} ...\n")
    files = sorted(
        os.path.join(VERSIONS_DIR, f)
        for f in os.listdir(VERSIONS_DIR)
        if f.endswith(".py") and not f.startswith("__")
    )
    for fp in files:
        patch_file(fp)
    print("\nAll done. Now run:  alembic upgrade head")


if __name__ == "__main__":
    main()