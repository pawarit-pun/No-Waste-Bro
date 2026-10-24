-- ============ Task log: ประวัติสถานะของ task ที่อนุมัติแล้ว (หน้า Task log ของ manager dashboard) ============
-- รันใน Supabase SQL Editor (รันซ้ำได้) ไม่ต้องแก้ Flutter app หรือ server: trigger บันทึกให้ทุกครั้งที่ task ถูกสร้าง / เปลี่ยนสถานะ
--
-- task_events   1 แถว = 1 เหตุการณ์ของ task
--   CREATED    task ถูกสร้างตอนอนุมัติ plan (ผู้จัดการหรือ AI auto-approve) staff_id = คนที่ระบบมอบหมาย
--   STARTED    staff กดรับงาน (PENDING -> IN_PROGRESS)
--   COMPLETED  staff ทำเสร็จ quantity = actual_quantity_handled
--   REJECTED   staff ปฏิเสธ note = rejection_reason
-- task ถูกลบ (Undo AI approval / demo_reset) -> event ถูกลบตาม (on delete cascade)
-- RLS: anon อ่านได้ (prototype ไม่มี login) เขียนผ่าน trigger เท่านั้น

create table if not exists task_events (
  event_id     bigint generated always as identity primary key,
  task_id      uuid not null references ai_recommended_tasks (task_id) on delete cascade,
  event_type   text not null check (event_type in ('CREATED', 'STARTED', 'COMPLETED', 'REJECTED', 'STATUS_CHANGED')),
  from_status  text,
  to_status    text not null,
  staff_id     varchar,
  quantity     integer,
  note         text,
  backfilled   boolean not null default false,
  created_at   timestamptz not null default now()
);
create index if not exists task_events_task_idx on task_events (task_id, created_at);
create index if not exists task_events_created_idx on task_events (created_at desc);

create or replace function public.log_task_event()
 returns trigger
 language plpgsql
 security definer
 set search_path to 'public'
as $function$
begin
  if tg_op = 'INSERT' then
    insert into task_events (task_id, event_type, from_status, to_status, staff_id)
    values (new.task_id, 'CREATED', null, new.task_status::text, new.assigned_staff_id);
  elsif new.task_status is distinct from old.task_status then
    insert into task_events (task_id, event_type, from_status, to_status, staff_id, quantity, note)
    values (new.task_id,
            case new.task_status::text when 'IN_PROGRESS' then 'STARTED' when 'COMPLETED' then 'COMPLETED'
                                       when 'REJECTED' then 'REJECTED' else 'STATUS_CHANGED' end,
            old.task_status::text, new.task_status::text, new.assigned_staff_id,
            case when new.task_status::text = 'COMPLETED' then new.actual_quantity_handled end,
            case when new.task_status::text = 'REJECTED' then new.rejection_reason end);
  end if;
  return null;
end;
$function$;

drop trigger if exists trg_task_events on ai_recommended_tasks;
create trigger trg_task_events
  after insert or update of task_status on ai_recommended_tasks
  for each row execute function public.log_task_event();

-- ย้อนหลังให้ task ที่มีอยู่แล้ว (เฉพาะ task ที่ยังไม่มี event) รู้เวลาได้แค่ตอนสร้างและตอนเสร็จ
insert into task_events (task_id, event_type, from_status, to_status, staff_id, backfilled, created_at)
select t.task_id, 'CREATED', null, 'PENDING', t.assigned_staff_id, true, t.created_at
from ai_recommended_tasks t
where not exists (select 1 from task_events e where e.task_id = t.task_id);

insert into task_events (task_id, event_type, from_status, to_status, staff_id, quantity, backfilled, created_at)
select t.task_id, 'COMPLETED', null, 'COMPLETED', t.assigned_staff_id, t.actual_quantity_handled, true, t.completed_at
from ai_recommended_tasks t
where t.task_status::text = 'COMPLETED' and t.completed_at is not null
  and not exists (select 1 from task_events e where e.task_id = t.task_id and e.event_type = 'COMPLETED');

alter table task_events enable row level security;
drop policy if exists "anon can read task events (prototype, no login)" on task_events;
create policy "anon can read task events (prototype, no login)" on task_events for select to anon using (true);

do $$
begin
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'task_events') then
    alter publication supabase_realtime add table task_events;
  end if;
end $$;
