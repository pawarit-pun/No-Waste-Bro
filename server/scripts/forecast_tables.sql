-- ผลพยากรณ์ของ Risk Scanner + Forecaster ที่ส่งต่อให้ Optimizer
-- บันทึกผ่าน POST /api/v1/risk-assessments (เรียก save_risk_run) อ่านผ่าน GET /api/v1/ai/optimize-inputs
-- รันซ้ำได้ (if not exists / create or replace)

-- ---------- รอบสแกน ----------
create table if not exists forecast_runs (
  run_id          uuid primary key default gen_random_uuid(),
  reference_date  date not null,                       -- "วันนี้" ของรอบสแกน
  model_version   varchar(100),
  metrics         jsonb,                               -- ความแม่นของโมเดล, cutoff ที่ใช้, lift ของส่วนลด
  created_at      timestamptz not null default now()
);
alter table forecast_runs enable row level security;
comment on table forecast_runs is 'รอบสแกนของ Risk Scanner + Forecaster (1 แถว = 1 รอบ)';

-- ---------- ชั่วโมงร้านเปิดที่เหลือจนสิ้นวันหมดอายุ ----------
alter table lot_risk_assessments add column if not exists sellable_hours integer
  check (sellable_hours is null or sellable_hours >= 0);
comment on column lot_risk_assessments.sellable_hours is 'ชั่วโมงร้านเปิด (08:00-22:00) ที่เหลือจนสิ้นวันหมดอายุ ตอนประเมิน';

-- ---------- shelf curve: ลด x% ตั้งแต่เปิดร้านวันนี้จนหมดอายุ จะขายได้เท่าไร ----------
create table if not exists lot_shelf_forecasts (
  assessment_id          uuid not null references lot_risk_assessments(assessment_id) on delete cascade,
  discount_pct           numeric(5,2) not null check (discount_pct >= 0 and discount_pct < 100),
  price                  numeric(10,2) not null check (price >= 0),
  expected_qty           numeric(10,2) not null check (expected_qty >= 0),   -- ยอดที่ล็อตนี้คาดว่าขายได้ก่อนหมดอายุ
  low_qty                numeric(10,2) not null check (low_qty >= 0),        -- ช่วงล่าง (10%)
  high_qty               numeric(10,2) not null check (high_qty >= low_qty), -- ช่วงบน (90%)
  applies_from           date not null,
  applies_until          date not null check (applies_until >= applies_from),
  lost_sales_other_lots  numeric(10,2) not null default 0 check (lost_sales_other_lots >= 0),
  primary key (assessment_id, discount_pct)
);
alter table lot_shelf_forecasts enable row level security;
comment on table lot_shelf_forecasts is 'ถ้าลดราคา x% ตั้งแต่เปิดร้านวันนี้จนหมดอายุ ล็อตนี้จะขายได้เท่าไร (เฉพาะล็อต HIGH / CRITICAL)';
comment on column lot_shelf_forecasts.lost_sales_other_lots is 'ล็อตอื่นของสินค้าเดียวกันขายได้น้อยลงเท่าไร เพราะลูกค้าไปหยิบล็อตที่ลดราคา';

-- ---------- ความต้องการเมนูครัวต่อสูตร ----------
create table if not exists recipe_demand_forecasts (
  run_id             uuid not null references forecast_runs(run_id) on delete cascade,
  recipe_id          varchar(50) not null references recipes(recipe_id),
  output_product_id  varchar(50) not null references products(product_id),
  window_from        date not null,
  window_to          date not null check (window_to >= window_from),   -- ช่วงอายุเมนู
  gross_demand       numeric(10,2) not null check (gross_demand >= 0), -- ความต้องการเมนูทั้งช่วง
  current_stock      integer not null default 0 check (current_stock >= 0),
  menu_qty           numeric(10,2) not null check (menu_qty >= 0),     -- gross_demand - current_stock
  low_qty            numeric(10,2) not null check (low_qty >= 0),
  high_qty           numeric(10,2) not null check (high_qty >= low_qty),
  expected_revenue   numeric(12,2) not null check (expected_revenue >= 0),
  primary key (run_id, recipe_id)
);
alter table recipe_demand_forecasts enable row level security;
comment on table recipe_demand_forecasts is 'ความต้องการเมนูครัวต่อสูตรในรอบสแกน หักของเมนูที่มีบนชั้นแล้ว (ใช้เลือกสูตรตามรายได้)';

-- ---------- บันทึกทั้งรอบใน transaction เดียว ----------
create or replace function save_risk_run(p_run jsonb)
returns jsonb language plpgsql set search_path = public as $$
declare
  v_run   uuid := coalesce(nullif(p_run->>'run_id', '')::uuid, gen_random_uuid());
  v_model varchar := p_run->>'model_version';
  a       jsonb;
  v_ass   uuid;
  v_out   jsonb := '[]'::jsonb;
begin
  insert into forecast_runs (run_id, reference_date, model_version, metrics)
  values (v_run, coalesce((p_run->>'reference_date')::date, (now() at time zone 'Asia/Bangkok')::date),
          v_model, p_run->'run_metrics');

  for a in select value from jsonb_array_elements(coalesce(p_run->'assessments', '[]'::jsonb)) loop
    insert into lot_risk_assessments (run_id, lot_id, days_to_expiry, sellable_hours, quantity_at_assessment,
           forecast_daily_demand, predicted_units_sold_before_expiry, predicted_leftover_units,
           sell_through_probability, risk_score, risk_level, model_version)
    values (v_run, a->>'lot_id', (a->>'days_to_expiry')::int, (a->>'sellable_hours')::int,
            (a->>'quantity_at_assessment')::int, (a->>'forecast_daily_demand')::numeric,
            (a->>'predicted_units_sold_before_expiry')::numeric, (a->>'predicted_leftover_units')::numeric,
            (a->>'sell_through_probability')::numeric, (a->>'risk_score')::numeric,
            (a->>'risk_level')::risk_level, v_model)
    returning assessment_id into v_ass;

    insert into lot_shelf_forecasts (assessment_id, discount_pct, price, expected_qty, low_qty, high_qty,
           applies_from, applies_until, lost_sales_other_lots)
    select v_ass, (s->>'discount_pct')::numeric, (s->>'price')::numeric, (s->>'expected_qty')::numeric,
           (s->>'low_qty')::numeric, (s->>'high_qty')::numeric, (s->>'applies_from')::date,
           (s->>'applies_until')::date, coalesce((s->>'lost_sales_other_lots')::numeric, 0)
      from jsonb_array_elements(coalesce(a->'shelf', '[]'::jsonb)) s;

    v_out := v_out || jsonb_build_object('assessment_id', v_ass, 'lot_id', a->>'lot_id');
  end loop;

  insert into recipe_demand_forecasts (run_id, recipe_id, output_product_id, window_from, window_to, gross_demand,
         current_stock, menu_qty, low_qty, high_qty, expected_revenue)
  select v_run, r->>'recipe_id', r->>'output_product_id', (r->>'window_from')::date, (r->>'window_to')::date,
         (r->>'gross_demand')::numeric, coalesce((r->>'current_stock')::int, 0), (r->>'menu_qty')::numeric,
         (r->>'low_qty')::numeric, (r->>'high_qty')::numeric, (r->>'expected_revenue')::numeric
    from jsonb_array_elements(coalesce(p_run->'recipe_demand', '[]'::jsonb)) r;

  return jsonb_build_object('run_id', v_run, 'created', jsonb_array_length(v_out), 'assessments', v_out);
end $$;
revoke execute on function save_risk_run(jsonb) from public, anon, authenticated;
comment on function save_risk_run(jsonb) is 'บันทึกผลรอบสแกน (forecast_runs, lot_risk_assessments, lot_shelf_forecasts, recipe_demand_forecasts) ทั้งหมดหรือไม่บันทึกเลย';
