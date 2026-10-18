"""Server-side paging helpers shared by every table.

``fetch_page`` runs a COUNT and a LIMIT/OFFSET query, so a screen only ever holds one page of rows, however big the table grows.
Only fixed SQL text written by the programmer is passed in (never user text); user values go in ``params``.
"""
from dataclasses import dataclass

PAGE_SIZES = (10, 25, 50, 100)
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 500


@dataclass(frozen=True)
class PageInfo:
    page: int          # 0-based, already clamped to a real page
    size: int
    total: int

    @property
    def pages(self):
        return max(1, -(-self.total // self.size))

    @property
    def offset(self):
        return self.page * self.size

    @property
    def first(self):
        return 0 if self.total == 0 else self.offset + 1

    @property
    def last(self):
        return min(self.total, self.offset + self.size)

    def label(self):
        return "No records" if self.total == 0 else f"Showing {self.first}-{self.last} of {self.total}"


def clean_size(size):
    try:
        n = int(size)
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE
    return max(1, min(n, MAX_PAGE_SIZE))


def clamp_page(page, size, total):
    """A page number that exists (the table may have shrunk since the person last looked)."""
    try:
        p = int(page)
    except (TypeError, ValueError):
        p = 0
    last = max(0, -(-total // size) - 1)
    return max(0, min(p, last))


def fetch_page(cur, select_sql, from_where_sql, params, order_sql, page=0, size=DEFAULT_PAGE_SIZE, count_sql=None):
    """-> (rows, PageInfo). ``cur`` must be a dictionary cursor.
    select_sql: "SELECT a, b"   from_where_sql: "FROM t WHERE x = %s"   order_sql: "ORDER BY id DESC" (must be a total order,
    add the primary key as the last key, or rows can repeat or vanish between pages)."""
    size = clean_size(size)
    cur.execute(count_sql or f"SELECT COUNT(*) AS n {from_where_sql}", tuple(params))
    total = int(cur.fetchone()["n"])
    page = clamp_page(page, size, total)
    info = PageInfo(page, size, total)
    if total == 0:
        return [], info
    cur.execute(f"{select_sql} {from_where_sql} {order_sql} LIMIT %s OFFSET %s", tuple(params) + (size, info.offset))
    return cur.fetchall(), info
