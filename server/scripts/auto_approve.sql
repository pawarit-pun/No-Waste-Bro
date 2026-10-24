-- ============ Manager Agent Phase 4: Auto-approve (AI อนุมัติ plan ความเสี่ยงต่ำเอง) ============
-- รันใน Supabase SQL Editor หลัง scripts/agent_tables.sql และ scripts/daily_reports.sql รันซ้ำได้
--
-- agent_policies   กติกาที่ผู้จัดการตั้งให้ agent (ตอนนี้มีแถวเดียว 'AUTO_APPROVE')
--   enabled          เปิด/ปิด (ค่าเริ่มต้นปิด)
--   params           {actions, max_discount_pct, max_value_thb, min_minutes_before_deadline, daily_limit, undo_minutes}
--                    ค่าที่ไม่ใส่ใช้ค่าเริ่มต้นใน server/services/auto_approve.py
--   owner_staff_id   ผู้จัดการที่เปิดกติกา (FK staff) server ใช้เป็น reviewed_by ของ plan ที่ agent อนุมัติ
--                    เพราะ pending_tasks.reviewed_by เป็น FK ไป staff และ role มีแค่ MANAGER / STAFF
-- pending_tasks
--   approved_by_agent  true = อนุมัติโดย agent ตามกติกา (ไม่ใช่ผู้จัดการกดเอง)
--   agent_run_id       รอบของ agent ที่อนุมัติ (ดูใน agent_runs)
--   agent_undone_at    ผู้จัดการกดย้อนการอนุมัติของ agent แล้ว: plan กลับเป็น WAITING และ agent จะไม่อนุมัติ plan นี้อีก
-- RLS: anon อ่านได้ (prototype ไม่มี login) เขียนผ่าน server เท่านั้น
-- demo_reset() ไม่ต้องแก้: plan ถูกลบตามเดิม กติกาที่ตั้งไว้ยังอยู่

create table if not exists agent_policies (
  policy_id       text primary key check (policy_id in ('AUTO_APPROVE')),
  enabled         boolean not null default false,
  params          jsonb not null default '{}'::jsonb,
  owner_staff_id  varchar references staff (staff_id),
  updated_at      timestamptz not null default now()
);
insert into agent_policies (policy_id) values ('AUTO_APPROVE') on conflict (policy_id) do nothing;

alter table pending_tasks
  add column if not exists approved_by_agent boolean not null default false,
  add column if not exists agent_run_id uuid references agent_runs (agent_run_id) on delete set null,
  add column if not exists agent_undone_at timestamptz;

alter table pending_tasks drop constraint if exists pending_tasks_agent_chk;
alter table pending_tasks add constraint pending_tasks_agent_chk
  check (not approved_by_agent or review_status = 'APPROVED');

create index if not exists pending_tasks_agent_idx on pending_tasks (reviewed_at) where approved_by_agent;

alter table agent_policies enable row level security;
drop policy if exists "anon can read agent policies (prototype, no login)" on agent_policies;
create policy "anon can read agent policies (prototype, no login)" on agent_policies for select to anon using (true);

do $$
begin
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'agent_policies') then
    alter publication supabase_realtime add table agent_policies;
  end if;
end $$;
