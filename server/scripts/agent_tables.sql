-- ============ Manager Agent Phase 2: แจ้งเตือน + ข้อเสนอ + บันทึกการทำงาน ============
-- รันใน Supabase SQL Editor (หรือ apply เป็น migration) รันซ้ำได้
--
-- agent_runs           ทุกรอบของ agent (แชท / เหตุการณ์ / ตรวจตามเวลา): tool ที่เรียก ผลลัพธ์ token เวลา (audit)
-- agent_proposals      ข้อเสนอที่ผู้จัดการกดยืนยันได้ agent สร้างได้อย่างเดียว server ทำตามเมื่อผู้จัดการกดยืนยัน
-- agent_notifications  แจ้งเตือนในกระดิ่งของ dashboard (dedupe_key กันเหตุการณ์เดิมแจ้งซ้ำ)
--
-- ไม่มี foreign key ไป lot / task / decision: demo_reset() และ scripts/load_mock_data ลบแถวพวกนั้นได้ตามเดิม
-- RLS + Realtime แบบเดียวกับ pipeline_runs: anon อ่านได้ (prototype ไม่มี login) เขียนผ่าน server (service role) เท่านั้น
-- demo_reset(): ลบแจ้งเตือนและข้อเสนอด้วย (agent_runs เก็บไว้เป็นประวัติ)

create table if not exists agent_runs (
  agent_run_id  uuid primary key default gen_random_uuid(),
  trigger       text not null check (trigger in ('CHAT', 'EVENT', 'SCHEDULE')),
  event_type    text,                                   -- TASK_REJECTED / KITCHEN_FULL / PIPELINE_FAILED / WATCH
  input         jsonb not null default '{}'::jsonb,     -- คำถาม + context หรือข้อมูลของเหตุการณ์
  answer        text,
  model_used    text,
  tool_calls    jsonb not null default '[]'::jsonb,
  warnings      jsonb not null default '[]'::jsonb,
  usage         jsonb not null default '{}'::jsonb,
  latency_ms    integer,
  created_at    timestamptz not null default now()
);
create index if not exists agent_runs_created_idx on agent_runs (created_at desc);

create table if not exists agent_proposals (
  proposal_id   uuid primary key default gen_random_uuid(),
  kind          text not null check (kind in ('RUN_PIPELINE', 'RELEASE_LOTS', 'BLOCK_KITCHEN')),
  params        jsonb not null default '{}'::jsonb,     -- {stop_after} / {lot_ids} / {department_id, date, hours}
  title         text not null,                          -- ข้อความบนปุ่ม/การ์ด เช่น "คืน 3 lot เป็น IDLE"
  reason        text,
  status        text not null default 'PROPOSED'
                check (status in ('PROPOSED', 'EXECUTED', 'DISMISSED', 'FAILED', 'EXPIRED')),
  source        text not null check (source in ('CHAT', 'EVENT', 'SCHEDULE')),
  agent_run_id  uuid references agent_runs (agent_run_id) on delete set null,
  expires_at    timestamptz,
  decided_by    varchar,                                -- staff_id ของผู้จัดการที่กดยืนยัน / ไม่ทำ
  decided_at    timestamptz,
  result        jsonb,                                  -- ผลที่ server ทำ หรือ error
  created_at    timestamptz not null default now()
);
create index if not exists agent_proposals_status_idx on agent_proposals (status, created_at desc);

create table if not exists agent_notifications (
  notification_id uuid primary key default gen_random_uuid(),
  severity      text not null default 'INFO' check (severity in ('INFO', 'WARNING', 'CRITICAL')),
  title         text not null,
  message       text not null,
  event_type    text,
  lot_id        varchar,
  task_id       uuid,
  dedupe_key    text unique,                            -- เช่น REJECTED:<task_id>, OVERDUE:<task_id>
  proposal_id   uuid references agent_proposals (proposal_id) on delete set null,
  agent_run_id  uuid references agent_runs (agent_run_id) on delete set null,
  read_at       timestamptz,
  created_at    timestamptz not null default now()
);
create index if not exists agent_notifications_created_idx on agent_notifications (created_at desc);

-- ---------- RLS: anon อ่านอย่างเดียว ----------
alter table agent_runs enable row level security;
alter table agent_proposals enable row level security;
alter table agent_notifications enable row level security;

drop policy if exists "anon can read agent runs (prototype, no login)" on agent_runs;
create policy "anon can read agent runs (prototype, no login)" on agent_runs for select to anon using (true);
drop policy if exists "anon can read agent proposals (prototype, no login)" on agent_proposals;
create policy "anon can read agent proposals (prototype, no login)" on agent_proposals for select to anon using (true);
drop policy if exists "anon can read agent notifications (prototype, no login)" on agent_notifications;
create policy "anon can read agent notifications (prototype, no login)" on agent_notifications for select to anon using (true);

-- ---------- Realtime: dashboard ใช้ event เป็นสัญญาณให้โหลดใหม่ ----------
do $$
begin
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'agent_notifications') then
    alter publication supabase_realtime add table agent_notifications;
  end if;
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'agent_proposals') then
    alter publication supabase_realtime add table agent_proposals;
  end if;
end $$;

-- ---------- demo_reset(): ลบแจ้งเตือน + ข้อเสนอของรอบ demo ก่อนหน้า ----------
-- เหมือนเดิมทุกบรรทัด เพิ่มแค่ 2 บรรทัด delete แรก และ 'agent_notifications_deleted' ในผลลัพธ์
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

  -- แจ้งเตือน / ข้อเสนอของ Manager Agent อ้างถึง task / lot ของรอบก่อน
  delete from agent_notifications where true;            get diagnostics v_notifications = row_count;
  delete from agent_proposals where true;

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
