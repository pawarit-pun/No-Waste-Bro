from db.supabase import supabase

PAGE_SIZE = 1000  # Supabase คืนได้สูงสุด 1,000 แถวต่อ request (ค่า default)


def fetch_all(table: str, columns: str = "*", in_filter: tuple[str, list] | None = None,
              order_by: tuple[str, ...] = ()) -> list[dict]:
    """ดึงทุกแถวของตาราง/view โดยวนดึงทีละหน้า กันข้อมูลถูกตัดที่ 1,000 แถว
    in_filter=("product_id", [...]) กรองเฉพาะค่าที่ระบุ, order_by ทำให้การแบ่งหน้าไม่สลับลำดับ"""
    rows: list[dict] = []
    start = 0
    while True:
        query = supabase.table(table).select(columns)
        if in_filter is not None:
            query = query.in_(in_filter[0], in_filter[1])
        for column in order_by:
            query = query.order(column)
        res = query.range(start, start + PAGE_SIZE - 1).execute()
        rows.extend(res.data)
        if len(res.data) < PAGE_SIZE:
            return rows
        start += PAGE_SIZE


def fetch_by_ids(table: str, key: str, ids, columns: str = "*") -> dict:
    """ดึงหลายแถวจาก key ที่ระบุ คืนเป็น dict {key: row}"""
    ids = {str(i) for i in ids if i is not None}
    if not ids:
        return {}
    res = supabase.table(table).select(columns).in_(key, list(ids)).execute()
    return {str(row[key]): row for row in res.data}
