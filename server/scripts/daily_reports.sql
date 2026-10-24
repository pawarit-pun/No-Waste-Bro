-- ============ Manager Agent Phase 3: รายงานประจำวัน (Morning brief / Evening summary) ============
-- รันใน Supabase SQL Editor หลัง scripts/agent_tables.sql (ต้องมีตาราง agent_* แล้ว) รันซ้ำได้
--
-- daily_reports  1 วันมีได้ 1 แถวต่อ kind: รันซ้ำวันเดิม = ทับ (DEMO_DATE ตรึงวัน -> รายงานวัน demo ถูกทับทุกครั้ง)
--   metrics    ตัวเลขที่โค้ดของ agent คำนวณ (decision ต่อวิธี, kg, กำไรที่ Optimizer คาด, ชั่วโมงครัว, task ที่ทำจริง)
--   anomalies  ความผิดปกติที่ตรวจเจอ [{code, severity, text, lot_ids}]
--   message    ข้อความสรุปภาษาไทย (LLM เขียนจาก metrics ผ่าน guard หรือข้อความสำเร็จรูป)
-- RLS + Realtime แบบเดียวกับตาราง agent_*: anon อ่านได้ (prototype ไม่มี login) เขียนผ่าน server เท่านั้น
-- demo_reset(): ลบรายงานของวัน demo ด้วย (เพิ่ม 1 บรรทัดจากเวอร์ชันใน agent_tables.sql)

create table if not exists daily_reports (
  report_id     uuid primary key default gen_random_uuid(),
  report_date   date not null,
  kind          text not null check (kind in ('MORNING', 'EVENING')),
  metrics       jsonb not null default '{}'::jsonb,
  anomalies     jsonb not null default '[]'::jsonb,
  message       text,
  model_used    text,
  agent_run_id  uuid references agent_runs (agent_run_id) on delete set null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (report_date, kind)
);
create index if not exists daily_reports_date_idx on daily_reports (report_date desc);

alter table daily_reports enable row level security;
drop policy if exists "anon can read daily reports (prototype, no login)" on daily_reports;
create policy "anon can read daily reports (prototype, no login)" on daily_reports for select to anon using (true);

do $$
begin
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'daily_reports') then
    alter publication supabase_realtime add table daily_reports;
  end if;
end $$;

CREATE OR REPLACE FUNCTION public.demo_reset(p_today date DEFAULT ((now() AT TIME ZONE 'Asia/Bangkok'::text))::date)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO 'public'
AS $function$
declare
  v_tasks int; v_decisions int; v_assessments int; v_lots_deleted int; v_lots_restored int; v_kitchen int;
  v_runs int; v_notifications int;
begin
  if not exists (select 1 from demo_lot_baseline) then
    raise exception 'demo_lot_baseline is empty, run demo_snapshot() first';
  end if;

  -- แจ้งเตือน / ข้อเสนอ / รายงานประจำวันของ Manager Agent อ้างถึง task / lot ของรอบก่อน
  delete from agent_notifications where true;            get diagnostics v_notifications = row_count;
  delete from agent_proposals where true;
  delete from daily_reports where report_date = p_today;

  -- plan ที่รอ/ผ่านการอนุมัติ ต้องลบก่อน เพราะชี้ไปที่ task / decision / assessment / lot
  delete from pending_tasks where true;
  delete from ai_recommended_tasks where true;           get diagnostics v_tasks = row_count;
  delete from optimization_decisions where true;         get diagnostics v_decisions = row_count;
  delete from lot_risk_assessments where true;           get diagnostics v_assessments = row_count;
  -- ผลพยากรณ์ของรอบสแกน (lot_shelf_forecasts ลบตาม lot_risk_assessments อัตโนมัติ)
  delete from recipe_demand_forecasts where true;
  delete from forecast_runs where true;                  get diagnostics v_runs = row_count;

  delete from inventory_lots l
   where not exists (select 1 from demo_lot_baseline b where b.lot_id = l.lot_id);
  get diagnostics v_lots_deleted = row_count;

  update inventory_lots l
     set initial_quantity      = b.initial_quantity,
         current_quantity      = b.current_quantity,
         current_selling_price = b.current_selling_price,
         ai_status             = b.ai_status,
         received_date         = p_today + b.received_offset_days,
         expiration_date       = p_today + b.expiry_offset_days,
         source_task_id        = null,
         updated_at            = now()
    from demo_lot_baseline b
   where b.lot_id = l.lot_id;
  get diagnostics v_lots_restored = row_count;

  update kitchen_capacity_daily set booked_hrs = 0, updated_at = now() where booked_hrs <> 0;
  get diagnostics v_kitchen = row_count;

  -- lot ใหม่จะเริ่มนับต่อจาก lot ล่าสุดใน baseline
  perform setval('inventory_lot_seq',
                 (select max(substring(lot_id from 5)::int) from demo_lot_baseline));

  return jsonb_build_object(
    'demo_date', p_today, 'tasks_deleted', v_tasks, 'decisions_deleted', v_decisions,
    'assessments_deleted', v_assessments, 'forecast_runs_deleted', v_runs, 'lots_deleted', v_lots_deleted,
    'lots_restored', v_lots_restored, 'kitchen_days_released', v_kitchen,
    'agent_notifications_deleted', v_notifications);
end $function$;
