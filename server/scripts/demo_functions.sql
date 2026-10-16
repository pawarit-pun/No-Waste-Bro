-- ============ Demo data: baseline + reset + seed + snapshot ============

create table if not exists demo_lot_baseline (
  lot_id                 varchar primary key references inventory_lots(lot_id) on delete cascade,
  initial_quantity       integer not null,
  current_quantity       integer not null,
  current_selling_price  numeric not null,
  ai_status              lot_ai_status not null default 'IDLE',
  received_offset_days   integer not null,   -- received_date   = วัน demo + offset
  expiry_offset_days     integer not null    -- expiration_date = วัน demo + offset
);
alter table demo_lot_baseline enable row level security;
comment on table demo_lot_baseline is 'ค่าตั้งต้นของ lot สำหรับ demo_reset() (วันที่เก็บเป็นจำนวนวันห่างจากวัน demo)';

-- ค่าตั้งต้นของ mock data ชุดปัจจุบัน (วันอ้างอิงเดิม 2026-10-12)
insert into demo_lot_baseline values
  ('LOT-000001',  85,  85,  47.50, 'IDLE',  -7, 2),
  ('LOT-000002', 172, 172,  47.50, 'IDLE',  -1, 8),
  ('LOT-000003',  45,  45,  14.50, 'IDLE', -27, 1),
  ('LOT-000004',  18,  18,  44.50, 'IDLE',  -3, 1),
  ('LOT-000005',  30,  14, 130.00, 'IDLE',  -5, 1),
  ('LOT-000006',  12,  12, 115.50, 'IDLE',  -2, 0),
  ('LOT-000007',  32,  32,  35.00, 'IDLE',  -4, 1),
  ('LOT-000008',  36,  36,  23.75, 'IDLE',  -2, 2),
  ('LOT-000009',  42,  42,  40.00, 'IDLE',  -3, 1),
  ('LOT-000010',  11,  11, 179.00, 'IDLE',  -2, 1)
on conflict (lot_id) do update set
  initial_quantity = excluded.initial_quantity, current_quantity = excluded.current_quantity,
  current_selling_price = excluded.current_selling_price, ai_status = excluded.ai_status,
  received_offset_days = excluded.received_offset_days, expiry_offset_days = excluded.expiry_offset_days;

-- initial_quantity ของ baseline ต้องตรงของจริง
update demo_lot_baseline b set initial_quantity = l.initial_quantity
  from inventory_lots l where l.lot_id = b.lot_id;


-- ---------- demo_reset ----------
create or replace function demo_reset(p_today date default (now() at time zone 'Asia/Bangkok')::date)
returns jsonb language plpgsql set search_path = public as $$
declare
  v_tasks int; v_decisions int; v_assessments int; v_lots_deleted int; v_lots_restored int; v_kitchen int;
begin
  if not exists (select 1 from demo_lot_baseline) then
    raise exception 'demo_lot_baseline is empty, run demo_snapshot() first';
  end if;

  delete from ai_recommended_tasks where true;           get diagnostics v_tasks = row_count;
  delete from optimization_decisions where true;         get diagnostics v_decisions = row_count;
  delete from lot_risk_assessments where true;           get diagnostics v_assessments = row_count;

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
    'assessments_deleted', v_assessments, 'lots_deleted', v_lots_deleted,
    'lots_restored', v_lots_restored, 'kitchen_days_released', v_kitchen);
end $$;


-- ---------- demo_snapshot ----------
-- บันทึก lot ทั้งหมดตอนนี้เป็น baseline (ใช้หลังโหลด mock data ชุดใหม่) p_ref = วันที่ที่ถือเป็น "วัน demo" ของข้อมูลชุดนั้น
create or replace function demo_snapshot(p_ref date default (now() at time zone 'Asia/Bangkok')::date)
returns jsonb language plpgsql set search_path = public as $$
declare v_count int;
begin
  delete from demo_lot_baseline where true;
  insert into demo_lot_baseline
  select lot_id, initial_quantity, current_quantity, current_selling_price, ai_status,
         received_date - p_ref, expiration_date - p_ref
    from inventory_lots;
  get diagnostics v_count = row_count;
  return jsonb_build_object('reference_date', p_ref, 'lots', v_count);
end $$;


-- ---------- demo_seed ----------
create or replace function demo_seed(p_today date default (now() at time zone 'Asia/Bangkok')::date)
returns jsonb language plpgsql set search_path = public as $$
declare
  v_run uuid := gen_random_uuid();
  s record; a record; lt record; rc record; ing record; po record; p record;
  v_dec uuid; v_task uuid; v_new numeric; v_impact numeric; v_qty int; v_hours numeric; v_mult numeric;
  v_due timestamptz; v_lot varchar; v_ass uuid; v_pickup date; v_kg numeric;
  v_created jsonb := '[]'::jsonb; v_bookings jsonb := '[]'::jsonb;
begin
  if exists (select 1 from ai_recommended_tasks) or exists (select 1 from lot_risk_assessments) then
    raise exception 'tasks or assessments already exist, run demo_reset() first';
  end if;

  -- 1) Risk assessment ของ lot ใน baseline (ยอดขายเฉลี่ย 7 วัน × วันก่อนหมดอายุ นับจากวัน demo)
  insert into lot_risk_assessments (run_id, lot_id, days_to_expiry, quantity_at_assessment, forecast_daily_demand,
         predicted_units_sold_before_expiry, predicted_leftover_units, sell_through_probability, risk_score, risk_level, model_version)
  select v_run, x.lot_id, x.dte, x.qty, x.v7, x.sold, x.qty - x.sold, round(x.sold / x.qty, 4),
         round((x.qty - x.sold) / x.qty * 100, 2),
         (case when (x.qty - x.sold) / x.qty * 100 >= 70 then 'CRITICAL'
               when (x.qty - x.sold) / x.qty * 100 >= 40 then 'HIGH'
               when (x.qty - x.sold) / x.qty * 100 >= 20 then 'MEDIUM' else 'LOW' end)::risk_level,
         'seed-demo-v1'
    from (select il.lot_id, il.current_quantity::numeric qty, (il.expiration_date - p_today) dte, dv.avg_daily_sales_7d v7,
                 round(least(il.current_quantity, dv.avg_daily_sales_7d * greatest(il.expiration_date - p_today, 0)), 2) sold
            from inventory_lots il
            join demo_lot_baseline b on b.lot_id = il.lot_id
            join daily_sales_velocity dv on dv.product_id = il.product_id
           where il.current_quantity > 0) x;

  -- 2) Decision + Task (due เป็นเวลาตายตัวของวัน demo)
  for s in select * from (values
    ('LOT-000006','KITCHEN_REPURPOSE',null::numeric,'RCP-003',4,12,'16:00'::time,1,'STF-002','PENDING',
     'ปลาแซลมอนล็อตนี้ถึงวันหมดอายุแล้ว คาดว่าขายไม่ทันทั้ง 12 แพ็ก (ยอดขายเฉลี่ย 10.14 แพ็ก/วัน) จึงแปรรูปเป็นข้าวหน้าแซลมอนย่าง 4 batch ใช้ปลา 12 แพ็ก ได้ 40 กล่อง จองครัวเดลี่ไว้ 3 ชั่วโมง',
     'นำปลาแซลมอน LOT-000006 ทั้ง 12 แพ็กจากชั้น C-01 ส่งครัวเดลี่ภายใน 16:00 แจ้งเชฟว่าเป็นข้าวหน้าแซลมอนย่าง 4 batch',
     '[{"title":"หา lot","detail":"ไปที่ชั้น SEAFOOD-C / C-01 ตรวจรหัส LOT-000006 บนฉลาก"},{"title":"เก็บปลาแซลมอน 12 แพ็ก","detail":"นำลงจากชั้นทั้ง 12 แพ็ก ใส่รถเข็นเย็นทันที"},{"title":"ส่งครัวเดลี่ภายใน 16:00","detail":"ส่งให้ทีมครัวเดลี่ แจ้งว่าทำข้าวหน้าแซลมอนย่าง 4 batch"},{"title":"ตรวจชั้นวาง","detail":"ยืนยันว่าไม่มีแพ็กของ lot นี้เหลือบนชั้น"}]'),
    ('LOT-000005','MARKDOWN',30,null,null,14,'15:30',1,'STF-002','COMPLETED',
     'สเต็กเนื้อเหลือ 1 วันก่อนหมดอายุ ยอดขายเฉลี่ย 8.43 แพ็ก/วัน คาดว่าเหลือ 5.57 จาก 14 แพ็ก (40%) ลดราคา 30% จาก 130 เหลือ 91 บาท ยังสูงกว่าราคาต่ำสุดที่อนุญาต (65 บาท)',
     'ติดป้ายราคาใหม่ 91.00 บาท ให้สเต็กเนื้อ LOT-000005 ทั้ง 14 แพ็กที่ชั้น B-02 แล้วจัดไว้ด้านหน้าชั้น',
     '[{"title":"หา lot","detail":"ไปที่ชั้น MEAT-B / B-02 ตรวจรหัส LOT-000005 บนฉลาก"},{"title":"พิมพ์ป้ายราคา 14 ใบ","detail":"พิมพ์ราคา ฿91.00 จากเครื่องพิมพ์ป้ายแบบพกพา"},{"title":"ติดป้ายและย้ายไปด้านหน้า","detail":"ติดทับราคาเดิม แล้ววางแพ็กที่ลดราคาไว้หน้าชั้น"}]'),
    ('LOT-000007','KITCHEN_REPURPOSE',null,'RCP-005',4,8,'17:00',1,'STF-004','IN_PROGRESS',
     'กล้วยหอมเหลือ 1 วันก่อนหมดอายุ ยอดขายเฉลี่ย 23.86 แพ็ก/วัน คาดว่าเหลือ 8.14 จาก 32 แพ็ก (25%) แปรรูปเป็นเค้กกล้วยหอม 4 batch ใช้ 8 แพ็ก ได้เค้ก 16 ชิ้น จองแผนกเบเกอรี่ไว้ 5 ชั่วโมง',
     'นำกล้วยหอม LOT-000007 จำนวน 8 แพ็กจากชั้น D-04 ส่งแผนกเบเกอรี่ภายใน 17:00 ส่วนที่เหลือวางขายตามปกติ',
     '[{"title":"หา lot","detail":"ไปที่ชั้น PRODUCE-D / D-04 ตรวจรหัส LOT-000007 บนฉลาก"},{"title":"แยกกล้วยหอม 8 แพ็ก","detail":"เลือกแพ็กที่สุกมากที่สุดก่อน ใส่ตะกร้าแยกไว้"},{"title":"ส่งแผนกเบเกอรี่ภายใน 17:00","detail":"ส่งให้ทีมเบเกอรี่ แจ้งว่าทำเค้กกล้วยหอม 4 batch"},{"title":"จัดชั้นที่เหลือ","detail":"วางกล้วยที่เหลือขายตามปกติ"}]'),
    ('LOT-000003','MARKDOWN',40,null,null,45,'16:00',1,'STF-003','PENDING',
     'โยเกิร์ตเหลือ 1 วันก่อนหมดอายุ ยอดขายเฉลี่ย 26.29 ถ้วย/วัน คาดว่าเหลือ 18.71 จาก 45 ถ้วย (42%) ลดราคา 40% จาก 14.50 เหลือ 8.70 บาท ยังสูงกว่าราคาต่ำสุด (7.25 บาท)',
     'ติดป้ายราคาใหม่ 8.70 บาท ให้โยเกิร์ต LOT-000003 ทั้ง 45 ถ้วยที่ชั้น A-03',
     '[{"title":"หา lot","detail":"ไปที่ชั้น CHILL-A / A-03 ตรวจรหัส LOT-000003 บนฉลาก"},{"title":"พิมพ์ป้ายราคา 45 ใบ","detail":"พิมพ์ราคา ฿8.70 จากเครื่องพิมพ์ป้ายแบบพกพา"},{"title":"ติดป้ายและย้ายไปด้านหน้า","detail":"ติดทับราคาเดิม แล้ววางถ้วยที่ลดราคาไว้หน้าชั้น"}]'),
    ('LOT-000010','MARKDOWN',40,null,null,11,'16:30',1,'STF-003','IN_PROGRESS',
     'เค้กกล้วยหอมเหลือ 1 วันก่อนหมดอายุ ยอดขายเฉลี่ย 7.14 ชิ้น/วัน คาดว่าเหลือ 3.86 จาก 11 ชิ้น (35%) ลดราคา 40% จาก 179 เหลือ 107.40 บาท ยังสูงกว่าราคาต่ำสุด (89.50 บาท)',
     'ติดป้ายราคาใหม่ 107.40 บาท ให้เค้กกล้วยหอม LOT-000010 ทั้ง 11 ชิ้นที่ชั้น E-05',
     '[{"title":"หา lot","detail":"ไปที่ชั้น BAKERY-E / E-05 ตรวจรหัส LOT-000010 บนฉลาก"},{"title":"พิมพ์ป้ายราคา 11 ใบ","detail":"พิมพ์ราคา ฿107.40 จากเครื่องพิมพ์ป้ายแบบพกพา"},{"title":"ติดป้ายและย้ายไปด้านหน้า","detail":"ติดทับราคาเดิม แล้ววางเค้กที่ลดราคาไว้หน้าชั้น"}]'),
    ('LOT-000009','MARKDOWN',30,null,null,42,'18:00',3,'STF-003','PENDING',
     'ขนมปังแซนวิชเหลือ 1 วันก่อนหมดอายุ ยอดขายเฉลี่ย 26.43 ห่อ/วัน คาดว่าเหลือ 15.57 จาก 42 ห่อ (37%) ลดราคา 30% จาก 40 เหลือ 28 บาท (แผนกเบเกอรี่วันนี้จองงานเค้กกล้วยไว้แล้ว จึงลดราคาแทนการทำขนมปังพุดดิ้ง)',
     'ติดป้ายราคาใหม่ 28.00 บาท ให้ขนมปังแซนวิช LOT-000009 ทั้ง 42 ห่อที่ชั้น E-01',
     '[{"title":"หา lot","detail":"ไปที่ชั้น BAKERY-E / E-01 ตรวจรหัส LOT-000009 บนฉลาก"},{"title":"พิมพ์ป้ายราคา 42 ใบ","detail":"พิมพ์ราคา ฿28.00 จากเครื่องพิมพ์ป้ายแบบพกพา"},{"title":"ติดป้ายและย้ายไปด้านหน้า","detail":"ติดทับราคาเดิม แล้ววางขนมปังที่ลดราคาไว้หน้าชั้น"}]'),
    ('LOT-000001','MARKDOWN',20,null,null,85,'19:00',3,'STF-003','PENDING',
     'นมสดล็อตนี้เหลือ 2 วันก่อนหมดอายุ ยอดขายเฉลี่ย 30.29 ขวด/วัน คาดว่าเหลือ 24.42 จาก 85 ขวด (29%) ลดราคา 20% จาก 47.50 เหลือ 38 บาท',
     'ติดป้ายราคาใหม่ 38.00 บาท ให้นมสด LOT-000001 ทั้ง 85 ขวดที่ชั้น A-01 และวางไว้หน้าล็อต LOT-000002 ที่หมดอายุช้ากว่า',
     '[{"title":"หา lot","detail":"ไปที่ชั้น CHILL-A / A-01 ตรวจรหัส LOT-000001 บนฉลาก"},{"title":"พิมพ์ป้ายราคา 85 ใบ","detail":"พิมพ์ราคา ฿38.00 จากเครื่องพิมพ์ป้ายแบบพกพา"},{"title":"ติดป้ายและย้ายไปด้านหน้า","detail":"ติดทับราคาเดิม วางไว้หน้า LOT-000002 ที่หมดอายุช้ากว่า"}]')
  ) as v(lot_id, action, pct, recipe, batches, qty, due_time, prio, staff, status, reasoning, instructions, steps)
  loop
    select * into a from lot_risk_assessments where run_id = v_run and lot_id = s.lot_id;
    if not found then raise exception 'no assessment for % (lot missing from baseline?)', s.lot_id; end if;
    select * into lt from inventory_lots where lot_id = s.lot_id;
    v_due := (p_today + s.due_time) at time zone 'Asia/Bangkok';
    v_new := null; v_impact := null;

    if s.action = 'MARKDOWN' then
      v_new := round(lt.current_selling_price * (1 - s.pct / 100), 2);
      if v_new < (select min_allowed_price from products where product_id = lt.product_id) then
        raise exception 'price below min for %', s.lot_id; end if;
      v_impact := round(a.predicted_leftover_units * v_new, 2);
    else
      select * into rc from recipes where recipe_id = s.recipe;
      select x.required_quantity, pr.net_content_value, pr.net_content_unit into ing
        from recipe_ingredients x join products pr on pr.product_id = x.ingredient_product_id
       where x.recipe_id = s.recipe and x.ingredient_product_id = lt.product_id;
      v_mult := case when ing.net_content_unit in ('KG','L') then 1000 else 1 end;
      v_qty := ceil(ing.required_quantity * s.batches / (ing.net_content_value * v_mult));
      if v_qty <> s.qty then raise exception 'qty mismatch % expected % got %', s.lot_id, s.qty, v_qty; end if;
      select * into po from products where product_id = rc.output_product_id;
      v_impact := round(rc.output_quantity * s.batches * po.regular_price - rc.utility_cost * s.batches, 2);
      v_hours := round(rc.estimated_prep_time_mins * s.batches / 60.0, 2);
      if not exists (select 1 from book_kitchen_hours(rc.department_id, p_today, v_hours)) then
        raise exception 'kitchen % has no % hours left on %', rc.department_id, v_hours, p_today; end if;
      v_bookings := v_bookings || jsonb_build_object('department_id', rc.department_id, 'date', p_today, 'hours', v_hours);
    end if;

    insert into optimization_decisions (run_id, assessment_id, lot_id, action_type, action_quantity, discount_pct,
           new_recommended_price, target_recipe_id, batch_count, due_by, expected_profit_impact, optimizer_version)
    values (v_run, a.assessment_id, s.lot_id, s.action::action_type, s.qty, s.pct, v_new, s.recipe, s.batches,
            v_due, v_impact, 'seed-demo-v1')
    returning decision_id into v_dec;

    insert into ai_recommended_tasks (decision_id, assessment_id, lot_id, product_id, action_type, action_quantity,
           discount_pct, new_recommended_price, target_recipe_id, batch_count, due_by, expected_profit_impact,
           original_price, priority, ai_reasoning, staff_instructions, instruction_steps, assigned_staff_id, task_status)
    values (v_dec, a.assessment_id, s.lot_id, lt.product_id, s.action::action_type, s.qty, s.pct, v_new, s.recipe,
            s.batches, v_due, v_impact, lt.current_selling_price, s.prio, s.reasoning, s.instructions, s.steps::jsonb,
            s.staff, (case when s.status = 'PENDING' then 'PENDING' else 'IN_PROGRESS' end)::task_status)
    returning task_id into v_task;

    if s.status = 'COMPLETED' then
      perform complete_task(v_task, s.staff, s.qty, p_today);
    end if;
    v_created := v_created || jsonb_build_object('lot_id', s.lot_id, 'action', s.action, 'staff', s.staff, 'status', s.status);
  end loop;

  -- 3) งานบริจาค: กล้วยหอมส่งเข้ามาเกิน 220 แพ็ก → ธนาคารอาหาร P-DON-01
  select * into p from donation_partners where partner_id = 'P-DON-01' and is_active;
  if not found then raise exception 'donation partner P-DON-01 not found or inactive'; end if;
  if not ('PRODUCE' = any(p.accepted_categories)) then raise exception 'P-DON-01 does not accept PRODUCE'; end if;
  -- วันรับของถัดไป (หลังวัน demo) ที่อยู่ใน pickup_days (1 = จันทร์ … 7 = อาทิตย์)
  select d::date into v_pickup from generate_series(p_today + 1, p_today + 7, interval '1 day') d
   where extract(isodow from d)::int = any(p.pickup_days) order by d limit 1;
  if v_pickup is null then raise exception 'P-DON-01 has no pickup day'; end if;
  if (p_today + 4) - v_pickup < coalesce(p.min_days_before_expiry, 0) then
    raise exception 'donation lot would have only % day(s) left at pickup', (p_today + 4) - v_pickup; end if;
  select net_content_value * case when net_content_unit = 'KG' then 1 else 0.001 end into v_kg
    from products where product_id = 'PRO-001';
  if 144 * v_kg < p.min_kg_per_pickup or 144 * v_kg > p.max_capacity_kg_per_pickup then
    raise exception 'donation weight % kg outside partner range', 144 * v_kg; end if;

  insert into inventory_lots (product_id, received_date, expiration_date, initial_quantity, current_quantity,
                              unit_cost, location_aisle, location_shelf, ai_status, current_selling_price)
  values ('PRO-001', p_today - 1, p_today + 4, 220, 220, 24.50, 'PRODUCE-D', 'D-05', 'CHECKED', 35.00)
  returning lot_id into v_lot;

  insert into lot_risk_assessments (run_id, lot_id, days_to_expiry, quantity_at_assessment, forecast_daily_demand,
         predicted_units_sold_before_expiry, predicted_leftover_units, sell_through_probability, risk_score, risk_level, model_version)
  values (v_run, v_lot, 4, 220, 23.86, 71, 149, round(71/220.0, 4), round(149/220.0*100, 2), 'HIGH', 'seed-demo-v1')
  returning assessment_id into v_ass;

  v_due := (v_pickup + p.pickup_time_start) at time zone 'Asia/Bangkok';
  insert into optimization_decisions (run_id, assessment_id, lot_id, action_type, action_quantity,
         target_partner_id, due_by, optimizer_version)
  values (v_run, v_ass, v_lot, 'DONATE', 144, 'P-DON-01', v_due, 'seed-demo-v1')
  returning decision_id into v_dec;

  insert into ai_recommended_tasks (decision_id, assessment_id, lot_id, product_id, action_type, action_quantity,
         target_partner_id, due_by, original_price, priority, ai_reasoning, staff_instructions, instruction_steps,
         assigned_staff_id, task_status)
  values (v_dec, v_ass, v_lot, 'PRO-001', 'DONATE', 144, 'P-DON-01', v_due, 35.00, 1,
    format('กล้วยหอมล็อต %s รับเข้ามา 220 แพ็ก เหลือ 4 วันก่อนหมดอายุ ยอดขายเฉลี่ย 23.86 แพ็ก/วัน หลังขายล็อตเก่า (LOT-000007) ที่เหลือ 24 แพ็กก่อน คาดว่าล็อตนี้ขายได้ 71 แพ็ก เหลือ 149 แพ็ก (68%%) ลดราคาก็ขายไม่ทัน จึงบริจาค 144 แพ็ก (144 kg) ให้%s ซึ่งรับผลไม้ รับขั้นต่ำ %s kg และมารับวันที่ %s เวลา %s–%s ตอนรับของสินค้ายังเหลืออายุ %s วัน',
           v_lot, p.name, p.min_kg_per_pickup, to_char(v_pickup, 'DD/MM'), to_char(p.pickup_time_start, 'HH24:MI'),
           to_char(p.pickup_time_end, 'HH24:MI'), (p_today + 4) - v_pickup),
    format('แยกกล้วยหอม %s จำนวน 144 แพ็กจากชั้น D-05 เตรียมไว้ที่ท่ารับของ ส่งให้%s วันที่ %s เวลา %s–%s',
           v_lot, p.name, to_char(v_pickup, 'DD/MM'), to_char(p.pickup_time_start, 'HH24:MI'), to_char(p.pickup_time_end, 'HH24:MI')),
    jsonb_build_array(
      jsonb_build_object('title','หา lot','detail',format('ไปที่ชั้น PRODUCE-D / D-05 ตรวจรหัส %s บนฉลาก', v_lot)),
      jsonb_build_object('title','แยก 144 แพ็ก','detail','คัดแพ็กที่ช้ำหรือเสียออก แล้วบรรจุลงลังพร้อมติดป้าย "บริจาค"'),
      jsonb_build_object('title', format('ส่งที่ท่ารับของก่อน %s', to_char(p.pickup_time_start, 'HH24:MI')),
                         'detail', format('ส่งให้รถ%s%s รับของช่วง %s–%s', p.name,
                                          coalesce(' (ติดต่อ' || p.contact_name || ')', ''),
                                          to_char(p.pickup_time_start, 'HH24:MI'), to_char(p.pickup_time_end, 'HH24:MI'))),
      jsonb_build_object('title','ปิดงานพร้อมจำนวนจริง','detail','กด Complete และใส่จำนวนแพ็กที่ส่งมอบจริง')),
    'STF-004', 'PENDING');
  v_created := v_created || jsonb_build_object('lot_id', v_lot, 'action', 'DONATE', 'staff', 'STF-004', 'status', 'PENDING',
                                               'pickup', v_pickup);

  -- 4) ทุก lot ที่ถูกสแกน → CHECKED
  update inventory_lots set ai_status = 'CHECKED', updated_at = now()
   where lot_id in (select lot_id from lot_risk_assessments where run_id = v_run) and ai_status <> 'CHECKED';

  return jsonb_build_object('demo_date', p_today, 'run_id', v_run, 'tasks', v_created, 'kitchen_bookings', v_bookings);
end $$;

revoke execute on function demo_reset(date), demo_seed(date), demo_snapshot(date) from public, anon, authenticated;
