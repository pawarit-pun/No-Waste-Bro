-- ============ Lot lifecycle: lot กลับมาให้สแกนใหม่หลัง task จบ ============
-- รันใน Supabase SQL Editor (หรือ apply เป็น migration) รันซ้ำได้
--
-- ทำไม: Optimizer ออก decision "เอาของออก" (partner / ทิ้ง) เฉพาะวันที่ลงมือจริง ส่วนที่ต้องกำจัดวันอื่นเป็นแผนชั่วคราว
--       lot ต้องถูกสแกนใหม่ในวันนั้น แต่ lot ที่มี task (ลดราคา / ครัว / ...) เป็น CHECKED และไม่เคยกลับเป็น IDLE
--       -> ของที่เหลือหลังลดราคาไม่มีใครวางแผนกำจัดอีก
--
-- เปลี่ยนจากเดิม 3 จุด:
--   1. release_lot_if_idle(lot_id)  (ใหม่) lot ที่ยังมีของ ไม่มี task ค้าง (PENDING / IN_PROGRESS) และไม่มี decision
--      รอทำ (PENDING / IN_REVIEW ใน optimization_decisions_status) -> IDLE ให้ pipeline รอบหน้าสแกนใหม่
--   2. complete_task(): เรียก release_lot_if_idle กับ lot ของ task หลังปิด task
--   3. complete_task(): lot ที่แยกออกมาตอนติดป้ายลดราคา (MARKDOWN_SPLIT) เริ่มเป็น IDLE (เดิม CHECKED = ไม่ถูกสแกนอีก)
-- ส่วนอื่นของ complete_task() เหมือนเดิมทุกบรรทัด
-- server/services/task_actions.py เรียก release_lot_if_idle ตอนพนักงานปฏิเสธ task ด้วย

create or replace function release_lot_if_idle(p_lot_id varchar)
returns boolean language plpgsql set search_path = public as $$
declare v_count int;
begin
  update inventory_lots l
     set ai_status = 'IDLE', updated_at = now()
   where l.lot_id = p_lot_id
     and l.ai_status <> 'IDLE'
     and l.current_quantity > 0
     and not exists (select 1 from ai_recommended_tasks t
                      where t.lot_id = l.lot_id and t.task_status in ('PENDING', 'IN_PROGRESS'))
     and not exists (select 1 from optimization_decisions_status s
                      where s.lot_id = l.lot_id and s.status in ('PENDING', 'IN_REVIEW'));
  get diagnostics v_count = row_count;
  return v_count > 0;
end $$;


CREATE OR REPLACE FUNCTION public.complete_task(p_task_id uuid, p_staff_id character varying, p_actual_qty integer, p_today date)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO 'public'
AS $function$
declare
  t        ai_recommended_tasks%rowtype;
  l        inventory_lots%rowtype;
  r        recipes%rowtype;
  p_out    products%rowtype;
  ing      record;
  src      record;
  v_need   integer;
  v_take   integer;
  v_new    varchar;
  v_qty    integer;
  v_updated   jsonb := '[]'::jsonb;
  v_created   jsonb := '[]'::jsonb;
  v_shortages jsonb := '[]'::jsonb;
  v_released  boolean;
begin
  -- ---------- ตรวจ task ----------
  select * into t from ai_recommended_tasks where task_id = p_task_id for update;
  if not found then
    raise exception 'task % not found', p_task_id using errcode = 'NW404';
  end if;
  if t.assigned_staff_id is distinct from p_staff_id then
    raise exception 'task % is assigned to %, not %', p_task_id, t.assigned_staff_id, p_staff_id
      using errcode = 'NW403';
  end if;
  if t.task_status <> 'IN_PROGRESS' then
    raise exception 'task % is %, only IN_PROGRESS tasks can be completed', p_task_id, t.task_status
      using errcode = 'NW409';
  end if;
  if p_actual_qty is null or p_actual_qty < 0 or p_actual_qty > t.action_quantity then
    raise exception 'actual_quantity_handled must be between 0 and %', t.action_quantity
      using errcode = 'NW422';
  end if;

  select * into l from inventory_lots where lot_id = t.lot_id for update;
  if p_actual_qty > l.current_quantity then
    raise exception 'lot % only has % unit(s) left', l.lot_id, l.current_quantity using errcode = 'NW422';
  end if;

  -- ---------- ตัด lot ของ task ----------
  if p_actual_qty > 0 then
    update inventory_lots
       set current_quantity = current_quantity - p_actual_qty, updated_at = now()
     where lot_id = l.lot_id;
    v_updated := v_updated || jsonb_build_object(
      'lot_id', l.lot_id, 'product_id', l.product_id, 'reason', 'TASK_LOT',
      'quantity_before', l.current_quantity, 'quantity_after', l.current_quantity - p_actual_qty);
  end if;

  -- ---------- ผลตาม action_type ----------
  if t.action_type = 'MARKDOWN' and p_actual_qty > 0 then
    -- แยกส่วนที่ติดป้ายลดเป็น lot ใหม่ (ราคาลด) เริ่มเป็น IDLE: pipeline รอบหน้าสแกน แล้ววางแผนส่วนที่ยังขายไม่หมด
    insert into inventory_lots (product_id, received_date, expiration_date, initial_quantity, current_quantity,
                                unit_cost, location_aisle, location_shelf, ai_status, current_selling_price,
                                source_task_id)
    values (l.product_id, l.received_date, l.expiration_date, p_actual_qty, p_actual_qty,
            l.unit_cost, l.location_aisle, l.location_shelf, 'IDLE', t.new_recommended_price,
            t.task_id)
    returning lot_id into v_new;
    v_created := v_created || jsonb_build_object(
      'lot_id', v_new, 'product_id', l.product_id, 'reason', 'MARKDOWN_SPLIT',
      'quantity', p_actual_qty, 'current_selling_price', t.new_recommended_price,
      'expiration_date', l.expiration_date, 'ai_status', 'IDLE');

  elsif t.action_type = 'KITCHEN_REPURPOSE' then
    select * into r from recipes where recipe_id = t.target_recipe_id;

    -- วัตถุดิบอื่นในสูตร: ปัดขึ้นเป็นหน่วยเต็ม ตัดจาก lot ที่ยังไม่หมดอายุ หมดอายุก่อนใช้ก่อน (FIFO)
    for ing in
      select ri.ingredient_product_id, ri.required_quantity, pr.net_content_value, pr.net_content_unit
        from recipe_ingredients ri
        join products pr on pr.product_id = ri.ingredient_product_id
       where ri.recipe_id = r.recipe_id
         and ri.ingredient_product_id <> l.product_id
       order by ri.ingredient_product_id
    loop
      if ing.net_content_value is null then
        raise exception 'product % has no net content, cannot convert recipe quantity', ing.ingredient_product_id
          using errcode = 'NW422';
      end if;
      v_need := ceil(ing.required_quantity * t.batch_count
                     / (ing.net_content_value * case when ing.net_content_unit in ('KG', 'L') then 1000 else 1 end));

      for src in
        select lot_id, current_quantity from inventory_lots
         where product_id = ing.ingredient_product_id
           and current_quantity > 0
           and expiration_date >= p_today
         order by expiration_date, lot_id
         for update
      loop
        exit when v_need = 0;
        v_take := least(v_need, src.current_quantity);
        update inventory_lots
           set current_quantity = current_quantity - v_take, updated_at = now()
         where lot_id = src.lot_id;
        v_updated := v_updated || jsonb_build_object(
          'lot_id', src.lot_id, 'product_id', ing.ingredient_product_id, 'reason', 'INGREDIENT',
          'quantity_before', src.current_quantity, 'quantity_after', src.current_quantity - v_take);
        v_need := v_need - v_take;
      end loop;

      if v_need > 0 then
        v_shortages := v_shortages || jsonb_build_object('product_id', ing.ingredient_product_id, 'missing_units', v_need);
      end if;
    end loop;

    if jsonb_array_length(v_shortages) > 0 then
      raise exception 'insufficient ingredients: %', v_shortages::text using errcode = 'NW422';
    end if;

    -- lot ใหม่ของสินค้าที่ผลิตได้
    select * into p_out from products where product_id = r.output_product_id;
    v_qty := floor(r.output_quantity * t.batch_count)::integer;
    insert into inventory_lots (product_id, received_date, expiration_date, initial_quantity, current_quantity,
                                unit_cost, location_aisle, ai_status, current_selling_price, source_task_id)
    values (r.output_product_id, p_today, p_today + r.shelf_life_days, v_qty, v_qty,
            p_out.base_cost, r.department_id, 'IDLE', p_out.regular_price, t.task_id)
    returning lot_id into v_new;
    v_created := v_created || jsonb_build_object(
      'lot_id', v_new, 'product_id', r.output_product_id, 'reason', 'KITCHEN_OUTPUT',
      'quantity', v_qty, 'current_selling_price', p_out.regular_price,
      'expiration_date', p_today + r.shelf_life_days, 'ai_status', 'IDLE');
  end if;
  -- DONATE / DISCARD: ตัด lot ของ task อย่างเดียว (ทำไปแล้วด้านบน)

  update ai_recommended_tasks
     set task_status = 'COMPLETED', completed_at = now(), actual_quantity_handled = p_actual_qty
   where task_id = p_task_id;

  -- lot ที่ยังมีของและไม่มีงานค้างแล้ว -> IDLE ให้สแกนใหม่ (เช่น ส่วนที่ต้องกำจัดหลังหมดเวลาขาย)
  v_released := release_lot_if_idle(l.lot_id);

  return jsonb_build_object('task_id', p_task_id, 'lots_updated', v_updated, 'lots_created', v_created,
                            'lot_released', v_released);
end;
$function$;

revoke execute on function release_lot_if_idle(varchar) from public, anon, authenticated;
