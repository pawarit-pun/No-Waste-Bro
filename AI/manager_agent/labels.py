"""ชื่อภาษาไทยของวิธีจัดการ (method ภายใน Optimizer) และ action_type ของ task"""

METHOD_TH = {
    "MARKDOWN": "ลดราคา", "SELL_REGULAR": "ขายราคาปกติ", "KITCHEN": "ส่งเข้าครัวทำเมนู",
    "KITCHEN_INGREDIENT": "ใช้เป็นวัตถุดิบในครัว", "DONATION": "บริจาค", "ANIMAL_FEED": "ส่งทำอาหารสัตว์",
    "COMPOSTING": "ส่งทำปุ๋ยหมัก", "ANAEROBIC_DIGESTION": "ส่งทำก๊าซชีวภาพ", "LANDFILL": "ส่งฝังกลบ",
    "UNRESOLVED": "ไม่มีทางไป (ทิ้งเองในร้าน)",
}
ACTION_TH = {
    "MARKDOWN": "ลดราคา", "KITCHEN_REPURPOSE": "ส่งเข้าครัว", "DONATE": "บริจาค", "DISCARD": "ทิ้งในร้าน",
    "ANIMAL_FEED": "อาหารสัตว์", "COMPOST": "ปุ๋ยหมัก", "ANAEROBIC_DIGESTION": "ก๊าซชีวภาพ", "LANDFILL": "ฝังกลบ",
}
