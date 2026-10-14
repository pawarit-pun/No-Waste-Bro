from db.supabase import supabase

PAGE_SIZE = 1000  # Supabase คืนได้สูงสุด 1,000 แถวต่อ request (ค่า default)


def fetch_all(table: str, columns: str = "*") -> list[dict]:
    """ดึงทุกแถวของตาราง/view โดยวนดึงทีละหน้า กันข้อมูลถูกตัดที่ 1,000 แถว"""
    rows: list[dict] = []
    start = 0
    while True:
        res = supabase.table(table).select(columns).range(start, start + PAGE_SIZE - 1).execute()
        rows.extend(res.data)
        if len(res.data) < PAGE_SIZE:
            return rows
        start += PAGE_SIZE
