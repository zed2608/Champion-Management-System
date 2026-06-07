import re

with open(r'C:\Users\user\Desktop\Champion_Management_System\views\reports.py', 'r', encoding='utf-8') as f:
    content = f.read()

# The root cause: self.start_date.get() and self.end_date.get() are called
# inside background threads — Tkinter widget access from non-main thread
# returns empty string silently. Fix: read dates BEFORE the thread, use closure.

replacements = [
    # ABC tab
    (
        "        def _fetch_abc():\n            conn = get_connection()\n            if not conn:\n                return\n            try:\n                cursor = conn.cursor(dictionary=True)\n                sd = self.start_date.get().strip()\n                ed = self.end_date.get().strip()",
        "        sd = self.start_date.get().strip()\n        ed = self.end_date.get().strip()\n\n        def _fetch_abc():\n            conn = get_connection()\n            if not conn:\n                return\n            try:\n                cursor = conn.cursor(dictionary=True)"
    ),
    # Usage tab
    (
        "        def _fetch_usage():\n            conn = get_connection()\n            if not conn:\n                return\n            try:\n                cursor = conn.cursor(dictionary=True)\n                \n                sd = self.start_date.get().strip()\n                ed = self.end_date.get().strip()",
        "        sd = self.start_date.get().strip()\n        ed = self.end_date.get().strip()\n\n        def _fetch_usage():\n            conn = get_connection()\n            if not conn:\n                return\n            try:\n                cursor = conn.cursor(dictionary=True)"
    ),
    # Activity tab
    (
        "        def _fetch_activity():\n            conn = get_connection()\n            if not conn:\n                return\n            try:\n                cursor = conn.cursor(dictionary=True)\n                sd = self.start_date.get().strip()\n                ed = self.end_date.get().strip()",
        "        sd = self.start_date.get().strip()\n        ed = self.end_date.get().strip()\n\n        def _fetch_activity():\n            conn = get_connection()\n            if not conn:\n                return\n            try:\n                cursor = conn.cursor(dictionary=True)"
    ),
]

for old, new in replacements:
    if old in content:
        content = content.replace(old, new)
        print(f"Replaced: {old[:60].strip()!r}")
    else:
        print(f"NOT FOUND: {old[:60].strip()!r}")

# For the three _fetch() functions (allocation, damage, overdue)
# they share the same def name so we handle them with a targeted approach
# by finding sd/ed reads inside the thread bodies and pulling them out

import re

def pull_sd_ed_out(content, anchor_before, anchor_sd_line):
    """
    Find a block where anchor_before precedes a _fetch function that reads sd/ed inside,
    and move the sd/ed reads to before the def.
    """
    pattern = (
        r'(        )(def _fetch\(\):)\n'
        r'(            conn = get_connection\(\)\n'
        r'            if not conn: return\n'
        r'            try:\n'
        r'                cursor = conn\.cursor\(dictionary=True\)\n)'
        r'                sd = self\.start_date\.get\(\)\.strip\(\)\n'
        r'                ed = self\.end_date\.get\(\)\.strip\(\)\n'
        r'                \n'
        r'                (params = \[\]\n'
        r'                date_filter = "")'
    )
    replacement = (
        r'        sd = self.start_date.get().strip()\n'
        r'        ed = self.end_date.get().strip()\n\n'
        r'\1\2\n'
        r'\3'
        r'                \4'
    )
    new_content, count = re.subn(pattern, replacement, content)
    print(f"_fetch() pattern replacements: {count}")
    return new_content

content = pull_sd_ed_out(content, None, None)

with open(r'C:\Users\user\Desktop\Champion_Management_System\views\reports.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done.")
