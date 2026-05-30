#!/usr/bin/env python3
"""Replace PPT HTML templates to match html_format.txt reference."""

import sys

filepath = 'agent/infrastructure/tools/impl/tools/presentation.py'

with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Total lines: {len(lines)}")

# Template boundaries (0-indexed, inclusive)
TITLE_START = 45   # line 46
TITLE_END = 118    # line 119 (""" closing line)
CONTENT_START = 120  # line 121
CONTENT_END = 178    # line 179 (""" closing line)
END_START = 180      # line 181
END_END = 229        # line 230 (""" closing line)

# _build_right_content boundaries
BUILD_START = 231  # line 232
BUILD_END = 279    # line 280 (line before def generate_ppt_html)

# Verify boundaries
assert '_PPT_TITLE_TEMPLATE' in lines[TITLE_START], f"Expected TITLE template at line {TITLE_START+1}"
assert '_PPT_CONTENT_TEMPLATE' in lines[CONTENT_START], f"Expected CONTENT template at line {CONTENT_START+1}"
assert '_PPT_END_TEMPLATE' in lines[END_START], f"Expected END template at line {END_START+1}"
assert 'def _build_right_content' in lines[BUILD_START], f"Expected _build_right_content at line {BUILD_START+1}"
assert 'def generate_ppt_html' in lines[BUILD_END], f"Expected generate_ppt_html at line {BUILD_END+1}"

print("Boundary verification passed!")

# Read new template content from files
with open('scripts/new_title_template.html', 'r', encoding='utf-8') as f:
    new_title = f.read()

with open('scripts/new_content_template.html', 'r', encoding='utf-8') as f:
    new_content = f.read()

with open('scripts/new_end_template.html', 'r', encoding='utf-8') as f:
    new_end = f.read()

with open('scripts/new_build_right.py', 'r', encoding='utf-8') as f:
    new_build = f.read()

# Build new file
new_lines = []
# Lines before TITLE template
new_lines.extend(lines[:TITLE_START])

# New TITLE template
new_lines.append('_PPT_TITLE_TEMPLATE = """\\\n')
new_lines.extend(new_title)
new_lines.append('"""\n')

# Blank line between templates
new_lines.append('\n')

# New CONTENT template
new_lines.append('_PPT_CONTENT_TEMPLATE = """\\\n')
new_lines.extend(new_content)
new_lines.append('"""\n')

# Blank line between templates
new_lines.append('\n')

# New END template
new_lines.append('_PPT_END_TEMPLATE = """\\\n')
new_lines.extend(new_end)
new_lines.append('"""\n')

# Blank line
new_lines.append('\n')

# New _build_right_content
new_lines.extend(new_build.splitlines(True))
new_lines.append('\n')

# Lines after _build_right_content (generate_ppt_html onwards)
new_lines.extend(lines[BUILD_END:])

new_content_str = ''.join(new_lines)

# Verify syntax
import ast
try:
    ast.parse(new_content_str)
    print("Python syntax OK!")
except SyntaxError as e:
    print(f"SYNTAX ERROR at line {e.lineno}: {e.msg}")
    new_content_lines = new_content_str.split('\n')
    for i in range(max(0, e.lineno-3), min(len(new_content_lines), e.lineno+3)):
        marker = ">>>" if i == e.lineno-1 else "   "
        print(f'{marker} {i+1}|{new_content_lines[i]}')
    sys.exit(1)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(new_content_str)

print(f"Done! New file has {len(new_content_str.splitlines())} lines")
