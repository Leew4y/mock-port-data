# Data dictionary: simulated highway freight port

All data is synthetic. Every number below that describes the port (dock counts, service rates, delays, shares) is an
invented assumption chosen so that queues and half-empty trucks appear at a plausible scale; none was measured at
a Transfar port. Change them in `portsim/config.py` and `portsim/reference.py`.

## The port being simulated

- 30 LTL lines (专线) rent space in one port near Hangzhou. 28 are general lines, 2 are hazardous-goods lines.
  Several lines serve the same destination city (12 cities).
- 40 docks: 36 general docks, each rented by one general line (large lines rent two), and 4 hazmat docks run by
  the port and used by the hazmat lines.
- Each day, for each line:
  - **delivery_in**: shippers' vans bring LTL orders to the line's dock (08:00 to 18:00).
  - **linehaul_out**: the line loads the day's orders into its own trucks and leaves in the evening.
  - **linehaul_in**: trucks from the destination side arrive and unload (05:00 to 11:00).
  - **pickup_out**: local vans load the unloaded goods for delivery (07:00 to 14:00).
- Today's practice (the baseline in the data): a truck may use only its own line's docks, first come first
  served; each line loads only its own orders. These two habits are what the rehearsal team is meant to improve.

## Folders

| Folder | Give to the team? | Contents |
|---|---|---|
| `clean/` | reference tables yes; see README | tidy tables, English headers, UTF-8 |
| `messy/` | yes | the same orders, gate events and appointments as exported business data: Chinese headers, problems injected |
| `answer_key/` | no, keep for scoring | hidden hazmat, trajectory anomalies, every injected data problem, baseline KPIs |

## clean/lines.csv

| Column | Meaning |
|---|---|
| line_id | L01 to L30 |
| line_name | display name, e.g. 成都专线A |
| destination | destination city |
| distance_km | approximate road distance from Hangzhou |
| hazmat_qualified | True for the two hazmat lines |
| standard_vehicle | the truck type the line normally runs |
| departure_time | daily linehaul departure (HH:MM) |
| docks_owned | general docks the line rents (0 for hazmat lines) |

## clean/docks.csv

| Column | Meaning |
|---|---|
| dock_id | G01 to G36 general, H01 to H04 hazmat |
| dock_type | general or hazmat |
| owner | renting line_id, or PORT |
| zone | A to D along the building for general docks, H for hazmat |

## clean/vehicle_types.csv

Rough figures for Chinese box trucks: vehicle_type, length_m, max_load_kg, volume_m3. Loading uses at most 90% of
the volume (`volume_fill_limit`), except that a leftover under 3 m3 may fill a truck up to 100%.

## clean/orders.csv (one row per LTL order)

| Column | Meaning |
|---|---|
| order_id | O + MMDD + line number + sequence |
| date | the day the shipper hands it over |
| line_id, destination | the line and its city |
| shipper_id | S0001 to S0600 |
| category | goods category; 危险品 for hazmat lines |
| description | free text, item and pieces, e.g. 女装 8箱 |
| weight_kg, volume_m3, pieces | size of the order |
| hazmat_class | UN class (2.1, 3, 4.1, 5.1, 6.1, 8, 9) for hazmat lines, else empty |
| dropoff_event_id | the delivery_in gate event that brought it |
| baseline_truck_id | the linehaul truck it left on under today's practice |

About 0.4% of general-line orders hide hazardous goods: the description names the item (油漆, 锂电池, 打火机 ...),
while category is ordinary and hazmat_class is empty. They are listed in `answer_key/undeclared_hazmat.csv`.

## clean/baseline_dispatch.csv (one row per linehaul truck, today's practice)

truck_id, date, line_id, destination, vehicle_type, n_orders, weight_kg, volume_m3, load_factor_volume,
load_factor_weight, load_factor (the larger of the two), hazmat_classes, illustrative_conflicts (pairs from
`hazmat_rules_illustrative.csv` present on the truck), planned_departure.

Each line packs its own orders first-fit-decreasing into its standard truck; the last truck of the day is the
smallest size that fits the remainder.

## clean/appointments.csv

appointment_id, plate, line_id, op_type, vehicle_type, slot_start, slot_end (30-minute slots). Booked shares:
delivery_in 30%, linehaul_out 85%, linehaul_in 80%, pickup_out 40%; the rest walk in. About 5% of booked pickup
vans never come (no gate event: a no-show is an appointment without a matching gate event).

## clean/gate_events.csv (one row per truck visit to a dock)

| Column | Meaning |
|---|---|
| event_id | E + sequence |
| date | the planned day |
| plate | licence plate; linehaul trucks carry the destination province's prefix, vans 浙A |
| appointment_id | empty for walk-ins |
| line_id, op_type, vehicle_type | who and what |
| cargo_volume_m3 | cargo handled at the dock |
| hazmat | True for hazmat-line trucks (they use H docks) |
| truck_id | for linehaul_out, the baseline_dispatch truck |
| gate_in, dock_start, dock_end, gate_out | timestamps; queue wait = dock_start - gate_in - 5 min drive |

Service time at the dock = 10 min + rate x volume (rate per m3: delivery_in 2.5, linehaul_in 1.8, linehaul_out
2.2, pickup_out 2.0 min) with random spread, plus 10 min for hazmat. Booked trucks arrive off their slot by a
random delay; 6% of inbound linehaul trucks are 1 to 4 hours late.

## clean/trajectories.csv

GPS pings every 5 minutes over the last 3 hours before each inbound linehaul truck reaches the gate: event_id,
plate, ts, lat, lon, speed_kmh. The truck moves on a straight line from its origin city (toy geometry, not
roads). About 6% of trucks have one anomaly (long_stop, route_deviation, signal_gap), listed in
`answer_key/trajectory_anomalies.csv`.

## clean/hazmat_rules_illustrative.csv

Pairs that must not share a vehicle. **Illustrative only, not the JT/T 617.6 table, which was not read.** Replace
with the standard's table before any claim about compliance.

## messy/

The same three tables as business exports usually arrive. Headers in Chinese; `op_type` values 送货卸车, 干线装车,
干线卸车, 提货装车; `hazmat` as 是/否; `orders.csv` is GB18030-encoded, the other two UTF-8 with BOM.

| Problem | Where | Share |
|---|---|---|
| duplicate rows | all three | 1% |
| missing cells | orders: shipper, category, pieces, volume; gate_events: dock, gate_out, plate; appointments: vehicle type | 2% per column |
| other time formats (2026/9/14 8:05, 14-09-2026 08:05, 20260914080500) | time columns | 15% |
| plate formats (浙A·12345, lower case, spaces) | plates | 5% |
| weight with units (0.151t, 151kg, 151公斤) | orders 重量 | 16% |
| dock_end before dock_start | gate_events | 0.3% |
| year 2025 in gate_in | gate_events | 0.2% |
| negative volume | orders | 0.2% |

Header mapping (clean → messy):

| Table | Mapping |
|---|---|
| orders | order_id 运单号, date 日期, line_id 专线编号, shipper_id 发货方编号, destination 目的地, category 货物类别, description 货物描述, weight_kg 重量, volume_m3 体积(方), pieces 件数, hazmat_class 危险品类别, dropoff_event_id 送货作业编号, baseline_truck_id 干线车次 |
| gate_events | event_id 作业编号, date 日期, plate 车牌号, appointment_id 预约号, line_id 专线编号, op_type 作业类型, vehicle_type 车型, cargo_volume_m3 货物体积(方), hazmat 是否危险品, truck_id 干线车次, gate_in 入场时间, dock_id 月台号, dock_start 开始作业时间, dock_end 结束作业时间, gate_out 出场时间 |
| appointments | appointment_id 预约号, plate 车牌号, line_id 专线编号, op_type 作业类型, vehicle_type 车型, slot_start 预约开始时间, slot_end 预约结束时间 |

## answer_key/

- `baseline_summary.json`: the config, counts, baseline dock KPIs, a naive pooled reference (any dock, first come
  first served, 15 min extra handling on another line's dock; a reference, not a solution) and baseline dispatch
  KPIs.
- `undeclared_hazmat.csv`, `trajectory_anomalies.csv`, `messy_injected_issues.csv` (table, key, column, issue).
