import { useState } from 'react'

/** รูปโปรไฟล์วงกลม ถ้าไม่มีรูปหรือโหลดไม่ได้ แสดงตัวอักษรแรกของชื่อ (เหมือน staff mobile app) */
export function StaffAvatar({ name, imageUrl, size = 56 }: { name: string; imageUrl: string | null; size?: number }) {
  const [failed, setFailed] = useState(false)
  const letter = name.trim().charAt(0).toUpperCase() || '?'

  if (!imageUrl || failed) {
    return (
      <div
        className="flex shrink-0 items-center justify-center rounded-full bg-brand-tint font-bold text-brand"
        style={{ width: size, height: size, fontSize: size * 0.42 }}
      >
        {letter}
      </div>
    )
  }
  return (
    <img
      src={imageUrl}
      alt=""
      width={size}
      height={size}
      onError={() => setFailed(true)}
      className="shrink-0 rounded-full bg-brand-tint object-cover"
      style={{ width: size, height: size }}
    />
  )
}
