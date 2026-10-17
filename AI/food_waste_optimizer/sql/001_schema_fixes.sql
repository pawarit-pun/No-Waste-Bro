-- =====================================================================================
-- 001_schema_fixes.sql — สิ่งที่ Optimizer ต้องการแต่ schema ปัจจุบันยังไม่มี / มีปัญหา
-- (เหตุผลของแต่ละข้ออยู่ในคอมเมนต์ และสรุปใน README ส่วน "ปัญหาที่พบ")
-- ⚠ ยังไม่ได้รันกับ Supabase จริง (sandbox ไม่มีเน็ต) ให้รันทีละข้อใน SQL Editor ของ staging ก่อน
-- =====================================================================================

-- ---- 0. ตรวจก่อน: CHECK constraint ของ optimization_decisions ห้ามอะไรบ้าง? ----------
-- Optimizer ส่ง target_partner_id + due_by มากับ action DISCARD (ทิ้งผ่าน partner) ถ้า CHECK ห้ามจะได้ 400
SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'public.optimization_decisions'::regclass AND contype = 'c';


-- ---- 1. action_type: ยังไม่มีวิธีกำจัดผ่าน partner ----------------------------------
-- ปัญหา: enum มีแค่ MARKDOWN / KITCHEN_REPURPOSE / DONATE / DISCARD แต่ partner มี 5 ประเภท
--        (DONATION, ANIMAL_FEED, COMPOSTING, ANAEROBIC_DIGESTION, LANDFILL) ที่ค่าใช้จ่าย/รายได้ต่างกัน
--        ตอนนี้ Optimizer ต้องส่ง ANIMAL_FEED/COMPOSTING/AD/LANDFILL เป็น DISCARD + target_partner_id
--        แล้วแยกชนิดไว้ใน alternatives(jsonb) ซึ่งค้น/รายงานยาก
-- ⚠ ALTER TYPE ... ADD VALUE ให้รันแต่ละบรรทัดแยกกัน (ห้ามอยู่ใน transaction เดียวกับการใช้ค่าใหม่)
ALTER TYPE action_type ADD VALUE IF NOT EXISTS 'ANIMAL_FEED';
ALTER TYPE action_type ADD VALUE IF NOT EXISTS 'COMPOST';
ALTER TYPE action_type ADD VALUE IF NOT EXISTS 'ANAEROBIC_DIGESTION';
ALTER TYPE action_type ADD VALUE IF NOT EXISTS 'LANDFILL';
-- หลังรัน: แก้ API (schemas/enums.py ActionType + schemas/decision.py + services/decisions.py) ให้รับค่าใหม่
-- แล้วตั้ง OptimizerConfig(action_mode="extended")


-- ---- 2. optimization_decisions: เก็บตัวเลขที่ใช้อธิบายการตัดสินใจ ----------------------
-- ปัญหา: ตารางมีแค่ action_quantity (หน่วย) ไม่มีน้ำหนักจริง (kg) / สัดส่วน % ของ lot / เวลารับของ /
--        แยกต้นทุน (ค่าเที่ยว, handling, utility, รายได้ buyback) ทั้งที่ RAG ต้องใช้เขียนเหตุผล
--        และน้ำหนักเป็นฐานของค่า handling + เกณฑ์ min_kg_per_pickup
ALTER TABLE optimization_decisions
  ADD COLUMN IF NOT EXISTS weight_kg      numeric(12,3),
  ADD COLUMN IF NOT EXISTS share_pct      numeric(6,2),
  ADD COLUMN IF NOT EXISTS pickup_at      timestamptz,
  ADD COLUMN IF NOT EXISTS cost_breakdown jsonb;
COMMENT ON COLUMN optimization_decisions.cost_breakdown IS
  'revenue_thb, cost_thb, cogs_thb, net_profit_thb, trip_allocated_thb, handling_thb, buyback_thb, ...';


-- ---- 3. donation_partners: NULL ที่ทำให้ API พัง --------------------------------------
-- ปัญหา: min_days_before_expiry เป็น NULL ใน 4 จาก 5 partner แต่ API model ประกาศเป็น int บังคับ
--        (responses.py DonationPartnerRow) และ services/decisions.py เทียบ `days_left < partner[...]`
--        -> GET /ai/optimize-inputs อาจ 500 และ DONATE อาจ TypeError  ความหมายของ NULL = "ไม่มีเกณฑ์" = 0
UPDATE donation_partners SET min_days_before_expiry = 0 WHERE min_days_before_expiry IS NULL;
ALTER TABLE donation_partners
  ALTER COLUMN min_days_before_expiry SET DEFAULT 0,
  ALTER COLUMN min_days_before_expiry SET NOT NULL;
UPDATE donation_partners SET min_kg_per_pickup = 0 WHERE min_kg_per_pickup IS NULL;
ALTER TABLE donation_partners
  ALTER COLUMN min_kg_per_pickup SET DEFAULT 0,
  ALTER COLUMN min_kg_per_pickup SET NOT NULL,
  ADD CONSTRAINT chk_partner_kg_range
    CHECK (min_kg_per_pickup >= 0 AND (max_capacity_kg_per_pickup IS NULL OR max_capacity_kg_per_pickup >= min_kg_per_pickup)),
  ADD CONSTRAINT chk_partner_costs_nonneg
    CHECK (fixed_cost_per_trip >= 0 AND travel_cost_per_trip >= 0 AND handling_fee_per_kg >= 0 AND buyback_price_per_kg >= 0);


-- ---- 4. demand: ไม่มีข้อมูลความต้องการรายระดับส่วนลด / ความต้องการเมนู ------------------
-- ปัญหา: lot_risk_assessments มีแค่ยอดขายที่ "ราคาปกติ" (forecast_daily_demand, predicted_units_sold...)
--        แต่ Optimizer ต้องรู้ว่าลด 20/30/40/50% แล้วขายได้กี่หน่วยถึงตัดสินได้ว่า markdown "คุ้มไหม"
--        และต้องรู้ความต้องการเมนูต่อวันของแต่ละสูตรเพื่อไม่ผลิตเกินที่ขายได้ (ตอนนี้ใช้ค่าสำรองใน mock)
ALTER TABLE lot_risk_assessments ADD COLUMN IF NOT EXISTS demand_curve jsonb;
COMMENT ON COLUMN lot_risk_assessments.demand_curve IS
  '[{"discount_pct":0,"expected_qty":20,"low":18,"high":22}, ...] จำนวนที่คาดว่าขายได้ตลอดอายุสินค้าที่ราคานั้น';

CREATE TABLE IF NOT EXISTS recipe_menu_demand (
  recipe_id      varchar      NOT NULL REFERENCES recipes(recipe_id),
  demand_date    date         NOT NULL,
  expected_units numeric      NOT NULL CHECK (expected_units >= 0),
  created_at     timestamptz  NOT NULL DEFAULT now(),
  PRIMARY KEY (recipe_id, demand_date)
);


-- ---- 5. ความจุ partner ที่ถูกจองไปแล้วในรอบรับเดียวกัน ----------------------------------
-- ปัญหา: max_capacity_kg_per_pickup เป็นความจุต่อรอบรับ แต่ไม่มีตารางบอกว่ารอบนั้นจองไปกี่ kg แล้ว
--        (คนละ run / คนละ task ในวันเดียวกันจะจองทับกันได้) Optimizer มี hook booked_kg(partner_id, date)
--        พร้อมใช้ ตอนนี้คืน 0 และเที่ยวที่มีการจองแล้วจะไม่คิดค่าเที่ยวซ้ำ
CREATE TABLE IF NOT EXISTS partner_pickup_bookings (
  booking_id  uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  partner_id  varchar      NOT NULL REFERENCES donation_partners(partner_id),
  pickup_date date         NOT NULL,
  decision_id uuid         REFERENCES optimization_decisions(decision_id) ON DELETE CASCADE,
  booked_kg   numeric(12,3) NOT NULL CHECK (booked_kg > 0),
  created_at  timestamptz  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pickup_bookings_slot ON partner_pickup_bookings (partner_id, pickup_date);
CREATE OR REPLACE VIEW partner_pickup_booked_kg AS
  SELECT partner_id, pickup_date, SUM(booked_kg) AS booked_kg FROM partner_pickup_bookings GROUP BY 1, 2;


-- ---- 6. (ไม่บังคับ) งานครัวที่ใช้วัตถุดิบหลักจากหลาย lot ------------------------------------
-- ปัญหา: POST /tasks จองชั่วโมงครัว = prep_time × batch_count ของ "ทุก task" ถ้างานเดียวถูกแตกเป็นหลาย decision
--        (หนึ่ง decision ต่อ lot วัตถุดิบ) ชั่วโมงจะถูกจองซ้ำ Optimizer จึงส่ง 1 decision ต่องานผูกกับ lot หลัก
--        ถ้าต้องการให้ทุก lot มี decision ของตัวเอง ให้เพิ่มคีย์งาน แล้วให้ server จองชั่วโมงครั้งเดียวต่อคีย์
-- ALTER TABLE optimization_decisions ADD COLUMN IF NOT EXISTS kitchen_job_key text;
