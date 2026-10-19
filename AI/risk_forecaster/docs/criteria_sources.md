# ที่มาของเกณฑ์ใน Risk Scanner + Forecaster

ระดับของที่มา
- **[A]** มีแหล่งอ้างอิง (ค้นเมื่อ 16 ต.ค. 2569 อ่านจากสรุปผลค้นเว็บ **ยังไม่ได้เปิดอ่านเอกสารต้นฉบับเต็ม** ควรตรวจซ้ำก่อนอ้างอิงทางการ)
- **[B]** หลักการทั่วไปในสาย forecasting / สถิติ
- **[C]** ทีมตั้งเอง (สมมติฐาน / นโยบาย) ต้องปรับด้วยข้อมูลจริง

## 1. Risk Scanner

| เกณฑ์ | ค่าที่ใช้ | ที่มา | สรุปหลักฐาน |
| --- | --- | --- | --- |
| วันที่ยังขายได้ | `days_to_expiry + 1` | **[A]** | ประกาศ สธ. ฉบับ 367 (2557) นิยาม "หมดอายุ" ว่า "...และหลังจากวันที่ระบุไว้นั้น อาหารนั้นวางจำหน่ายไม่ได้" แปลว่าวันหมดอายุเองยังขายได้ [1][2] |
| แบ่งความต้องการให้หลายล็อต | 40% ไปล็อตใหม่สุด ที่เหลือ FIFO | **[A]** ทิศทาง, **[C]** ตัวเลข | งานวิจัยกับห้างใหญ่ในยุโรป (15.3 ล้านรายการ, 125 สาขา) พบว่าลูกค้าเลือกของใหม่สุดเป็นหลัก (LEFO) และ 65% ของการซื้อ ชั้นมีของหลายวันหมดอายุปนกัน [3] ไม่พบสัดส่วนที่ใช้ได้ทั่วไป 40% = ค่าใน simulator |
| risk_score | ของที่คาดว่าจะเหลือ / จำนวน x 100 | **[A]** แนวคิด, **[C]** สูตร | วงการใช้ "days of cover / อายุที่เหลือ" ถ้าเกิน 1 จะเกิดของเสีย [4] score ของเรา = 1 - 1/อัตราส่วนนี้ ไม่พบสูตรหรือเกณฑ์มาตรฐานที่ตีพิมพ์ [4] |
| เกณฑ์ระดับ | MEDIUM 10 / HIGH 40 / CRITICAL 50 | **[B]** วิธี, **[C]** ตัวเลือก | ไม่มีมาตรฐาน จึงเลือกจากข้อมูล: ตัวเลือก 0, 10, ..., 90 (ทีมกำหนด) เลือกชุดที่ macro-F1 ระหว่างระดับที่ทำนายกับระดับจริง (จากของที่ทิ้งจริงรายล็อต) สูงสุดบน validation วัดบน test ได้ 0.345 (เกณฑ์เดิม 30 / 50 / 80 ได้ 0.324) ยังไม่นิ่งเพราะข้อมูล 96 วัน |
| ส่งต่อเฉพาะ HIGH / CRITICAL | | **[C]** | ทีมตกลง LOW / MEDIUM คืน IDLE ให้สแกนใหม่พรุ่งนี้ |
| วันสุดท้ายขยับขึ้น 1 ระดับ | | **[A]** ทิศทาง, **[B]** เลือกจากข้อมูล | ห้างจริงลดราคาหนักช่วงเย็นของวันสุดท้าย แต่ไม่มีเวลาตายตัว [5] เปิด/ปิดถูกเลือกพร้อม cutoff (เปิดดีกว่า) |
| sellable_hours | (days_to_expiry + 1) x 14 ชม. - ชั่วโมงที่ผ่านไปวันนี้ | **[A]** วัน, **[C]** เวลาร้าน | ขายได้ถึงสิ้นวันหมดอายุ [1] ร้านเปิด 08:00-22:00 เป็นสมมติฐานของ mock data |
| โอกาสขายหมด | Negative Binomial, variance = phi_k x mean | **[A]** | ยอดขายค้าปลีกผันผวนเกิน Poisson NB fit ข้อมูลเชนค้าปลีกได้ดีกว่า Poisson / normal [6][7] |
| ความไม่แน่นอนหลายวัน | phi_k แยกตามจำนวนวัน k (1.76 → 3.08) | **[A]** | ยอดวันติดกันสัมพันธ์กัน ถ้ารวมแบบอิสระจะประเมินความไม่แน่นอนต่ำเกินไป [8] จึงวัด phi ของยอดรวม k วันโดยตรงจาก validation |

## 2. Forecaster

| เกณฑ์ | ค่าที่ใช้ | ที่มา | สรุปหลักฐาน |
| --- | --- | --- | --- |
| การแบ่งข้อมูล | เรียงตามเวลา train / validation 20% / test 20% (อย่างน้อย 28 วัน) | **[A]** | Hyndman: evaluation on a rolling forecasting origin, ทดสอบประมาณ 20% ล่าสุด และอย่างน้อยครอบคลุม horizon, ห้ามใช้ k-fold แบบสุ่มกับ time series [9][10] validation แยกไว้เลือก parameter / cutoff เพื่อไม่ให้ test ถูกใช้เลือก |
| feature แบบ origin (lag ถึงเมื่อวาน) | horizon 1-14 วัน | **[A]** | ตรงกับ forecast ŷ(t+h|t) ของ rolling origin [9] |
| ตัดวันของหมดชั้นออก | | **[A]** | ยอดขายที่ของหมดชั้นต่ำกว่าความต้องการจริง (lost sales ไม่ถูกบันทึก) [6] |
| ใช้วันลดราคาของ RTE | | **[C]** | ตัดสินจากวิธีสร้าง mock data ต้องพิสูจน์ใหม่กับข้อมูลจริง |
| WAPE | | **[B]** | |
| LightGBM parameter | 4 ชุดใน `LGBM_GRID` เลือกบน validation (ได้ 7 leaves, lr 0.05, 300 trees) | **[B]** | |
| ผลของการลดราคา | วัดจากวันลดทั้งวัน x1.17 / x1.17 / x1.41 (20 / 30 / 50%) | **[A]** เทียบช่วง | ความยืดหยุ่นราคาอาหาร 0.27-0.81 เนื้อสัตว์ 0.7-0.8 [11] ค่าของเรา = 0.83 / 0.55 / 0.83 อยู่ในช่วงฝั่งบน simulator ตั้งไว้ x1.12 / x1.20 / x1.35 (ความยืดหยุ่น 0.6-0.7) |

## 3. Mock data v3 เทียบ benchmark

| ตัวชี้วัด | mock v3 | benchmark | ที่มา | สรุป |
| --- | --- | --- | --- | --- |
| ของหมดชั้น | 3.1-8.3% (รวม 10.3%, RTE 19.8%) | เฉลี่ยราว 8% (US 7.9%, EU 8.6%, 2002) / 8.3% (2008) / UK on-shelf 89.7% | **[A]** [12][13][14] | ใกล้เคียง ยกเว้น RTE |
| ของเสีย deli / RTE | 20.3% | deli 8.7% | **[A]** FMI (เก่า) [15] | **สูงเกินจริง** (ข้อจำกัด: ผลิตวันละ 3 รอบ ขายหมดในวัน ปริมาณน้อย ลดของหมดชั้นแล้วของเสียจะขึ้น) |
| ของเสีย bakery | 6.3% | 8.5% | **[A]** [15] | ใกล้เคียง |
| ของเสีย seafood | 8.0% | 7.6% | **[A]** [15] | ใกล้เคียง |
| ของเสีย meat | 4.2% | 5.7% | **[A]** [15] | ใกล้เคียง |
| ของเสีย produce / dairy | 2.8% / 1.8% | ไม่มีตัวเลขเทียบตรง | | |
| ของเสียรวม | 7.4% | ทั้งร้าน 3.1% (FMI 2019), NL 1.2% ตามน้ำหนัก | **[A]** [15][16] | สูงกว่า เพราะ mock มีแต่ของสด (ไม่มีของแห้ง) |

ข้อควรระวังของ benchmark: shrink ของ FMI รวมการขโมย ความเสียหาย และส่วนที่ลดราคา ไม่ใช่ของทิ้งอย่างเดียว ตัวเลขจึงสูงกว่าของทิ้งจริง [15]

## 4. ผลของการลดราคาตามวันหมดอายุ (ใช้คาดหวังผลของระบบ)

| ผล | ที่มา |
| --- | --- |
| field experiment กับห้างในยุโรป: ลดราคาตามอายุ + จัดของเก่าไว้หน้า ลดของเสียได้ถึง 30% | [17] |
| field experiment: เฉพาะระบบที่ขยายจำนวนสินค้าเสี่ยงเข้าสู่การลดราคา จึงลดของเสียพอจะลดความสูญเสียรวม | [18] |
| simulation: ลดราคาตามวันหมดอายุ กำไร +3.8% ของเสีย 5.6% → 3.6% | [19] |
| online grocer: ลดราคาอัตโนมัติ margin +25% ของเสีย -3% | [20] |

## แหล่งอ้างอิง

1. ประกาศกระทรวงสาธารณสุข (ฉบับที่ 367) พ.ศ. 2557 https://exfood.fda.moph.go.th/law/data/complilation/Compi_367.pdf
2. วารสารกฎหมาย อย. ก.ย.-ธ.ค. 2557 https://he01.tci-thaijo.org/index.php/fdajournal/article/download/139080/103298/
3. NUS: What Happens to the Milk You Didn't Pick https://www.comp.nus.edu.sg/features/what-happens-to-the-milk-you-didnt-pick/
4. ReFED guest blog: Using Existing Data To Cut Spoilage Shrink https://refed.org/articles/guest-blog-the-low-hanging-fruit-using-existing-data-to-cut-spoilage-shrink-now-at-grocery-retail/
5. What time of day do Aldi, Lidl, Tesco reduce food https://www.gazette-news.co.uk/news/23524669.time-day-aldi-lidl-tesco-reduce-food
6. Agrawal & Smith (1996), Naval Research Logistics https://ideas.repec.org/a/wly/navres/v43y1996i6p839-861.html
7. M5 Competition Uncertainty: Overdispersion https://ar5iv.labs.arxiv.org/html/2107.06675
8. Alwan & Weiß (2017), IJPR https://ideas.repec.org/a/taf/tprsxx/v55y2017i4p1085-1099.html
9. Hyndman, forecast::tsCV https://pkg.robjhyndman.com/forecast/reference/tsCV.html
10. Rob Hyndman on time series cross-validation (SAS blog) https://blogs.sas.com/content/forecasting/2016/06/09/rob-hyndman-on-time-series-cross-validation
11. Andreyeva, Long & Brownell (2010), AJPH https://pmc.ncbi.nlm.nih.gov/articles/PMC2804646
12. Supermarket News: new study aims fix persistent stockouts https://www.supermarketnews.com/archive/new-study-aims-fix-persistent-stockouts
13. Wikipedia: Stockout https://en.wikipedia.org/wiki/Stockout
14. Supermarket News: grocery retailers, customers paying the price https://www.supermarketnews.com/grocery-trends-data/grocery-retailers-customers-paying-the-price
15. Digimarc: A Fresh Perspective on Grocery Shrink https://www.digimarc.com/blog/fresh-perspective-grocery-shrink
16. WUR: Supermarket food waste remains at lowest level https://www.wur.nl/en/news/food-waste-supermarkets-annual-Dutch-survey
17. Dynamic Markdown Strategies for Perishable Products (arXiv 2608.23046) https://arxiv.org/abs/2608.23046
18. Knox et al., Navigating the Waste-Markdown Tradeoff https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7048139
19. WUR: Dynamic expiration date-based discounting of fresh food products https://research.wur.nl/en/publications/dynamic-expiration-date-based-discounting-of-fresh-food-products/
20. Inventory Information Frictions Explain Price Rigidity in Perishable Groceries (Marketing Science) https://pubsonline.informs.org/doi/10.1287/mksc.2023.0473
