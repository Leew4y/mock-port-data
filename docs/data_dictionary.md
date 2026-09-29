# Data dictionary: simulated highway freight port

All data is synthetic. Every number below that describes the port (dock counts, service rates, delays, shares) is an
invented assumption chosen so that queues and half-empty trucks appear at a plausible scale; none was measured at
a Transfar port. Most are in `portsim/config.py` and `portsim/reference.py`; the rest are hard-coded in the modules
of `portsim/`:

- `entities.py`: the limits that size a line's standard truck and its hazmat trucks, 6 outbound and 6 inbound fleet
  trucks per line, the spread of line sizes (hazmat lines get 0.4 of a general line's orders), 600 shippers, order
  weight (median 250 kg, hazmat 300 kg) and density spreads.
- `dispatch.py`: the overflow truck sizes and the 3 m³ squeeze of a small leftover.
- `operations.py`: 1 to 4 orders per shipper delivery van (1 + Poisson(0.8)); 6% of inbound linehaul trucks late by
  a further 60 to 240 min; 10 min extra service at hazmat docks; the spread of service times; 5 to 15 min from dock to
  gate; inbound linehaul trucks per day 0.7 to 1.3 times the outbound ones, filled Beta(6, 3); pickup vans of 8 to
  14 m³ each, 80% of them 4.2 m where the load allows; at most 3 hired plates per line and truck size.
- `trajectories.py`: 6% of trucks with an anomaly, 65 km/h ± 15%, at most 180 min of driving before the gate,
  anomaly lengths (long stop 45 to 90 min, route deviation 30 to 60 min, signal gap 40 to 90 min).
- `messy.py`: the share of cells changed by each kind of injected issue.

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
| standard_vehicle | the truck type the line normally runs: sized by expected daily volume for general lines, by expected weight for hazmat lines |
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
| weight_kg, volume_m3, pieces | size of the order; volume is at most 12 m3 (a larger LTL order would ship as a full truck) |
| hazmat_class | UN class (2.1, 3, 4.1, 5.1, 6.1, 8, 9) for hazmat lines, else empty; read it as text |
| dropoff_event_id | the delivery_in gate event that brought it |
| baseline_truck_id | the linehaul truck it left on under today's practice |

About 0.4% of general-line orders hide hazardous goods: the description names the item (油漆, 锂电池, 打火机 ...),
while category is ordinary and hazmat_class is empty. Their weight, density and unit are drawn like any order of the
declared category, so the item name is the only clue. They are listed in `answer_key/undeclared_hazmat.csv`.

## clean/baseline_dispatch.csv (one row per linehaul truck, today's practice)

truck_id, date, line_id, destination, vehicle_type, n_orders, weight_kg, volume_m3, load_factor_volume,
load_factor_weight, load_factor (the larger of the two), hazmat_classes, illustrative_conflicts (pairs from
`hazmat_rules_illustrative.csv` present on the truck), planned_departure.

Each line packs its own orders first-fit-decreasing into its standard trucks. A line with one truck that day runs
its standard truck however empty. When more are needed, the last one is hired at the smallest size that fits the
remainder, and at least 6.8m on routes over 600 km. Plates of hired trucks are separate from the line's own fleet,
except on a saturated port (non-default settings), where a truck whose usual plate is still inside takes another
free plate of the line with the same vehicle type, or a new one.

## clean/appointments.csv

appointment_id, plate, line_id, op_type, vehicle_type, slot_start, slot_end (30-minute slots). Booked shares:
delivery_in 30%, linehaul_out 85%, linehaul_in 80%, pickup_out 40%; the rest walk in. About 5% of booked pickup
vans never come (no gate event: a no-show is an appointment without a matching gate event); that is about 1% of all
appointments (31 of 2,953 in the default run). Slots are not checked against dock capacity, and about 30% of
booked trucks arrive after their slot ends.

## clean/gate_events.csv (one row per truck visit to a dock)

| Column | Meaning |
|---|---|
| event_id | E + sequence |
| date | the planned day (a few exits fall after midnight) |
| plate | licence plate; linehaul trucks carry the destination province's prefix, vans 浙A. A plate is one vehicle of one type, never at the port twice at once |
| appointment_id | empty for walk-ins |
| line_id, op_type, vehicle_type | who and what |
| cargo_volume_m3 | cargo handled at the dock |
| hazmat | True for hazmat-line trucks (they use H docks) |
| truck_id | for linehaul_out, the baseline_dispatch truck |
| gate_in, dock_start, dock_end, gate_out | timestamps; wait = dock_start - gate_in - 5 min drive |

Service time at the dock = 10 min + rate x volume (rate per m3: delivery_in 2.5, linehaul_in 1.8, linehaul_out
2.2, pickup_out 2.0 min) with random spread, plus 10 min for hazmat. Booked trucks arrive off their slot by a
random delay; 6% of booked inbound linehaul trucks (about 5% of all) are 1 to 4 hours late.

A truck's wait has two parts. It waits for its cargo: a linehaul truck starts loading only after every order on it
has been unloaded from its delivery van, and a pickup van (which collects from one inbound truck) only after that
truck is unloaded. Then it queues for a dock, first come first served; among equally good docks the one idle
longest is taken.

## clean/trajectories.csv

GPS pings every 5 minutes over the last 3 hours before each inbound linehaul truck reaches the gate: event_id,
plate, ts, lat, lon, speed_kmh. The truck moves on a straight line from its origin city at constant speed (toy
geometry, not roads); a truck whose trip is shorter than 3 hours (Shanghai) has pings from its departure only.
Each truck has a 6% chance of one anomaly (long_stop, route_deviation, signal_gap; 6.8% of trucks in the default
run), listed in `answer_key/trajectory_anomalies.csv`; every ping with speed 0 lies inside a labelled long_stop.

## clean/hazmat_rules_illustrative.csv

Pairs that must not share a vehicle. **Illustrative only, not the JT/T 617.6 table, which was not read.** Replace
with the standard's table before any claim about compliance (the 2018 text as amended by amendment No. 1 of 2024-05-07).

## messy/

The same three tables as business exports usually arrive. Headers in Chinese; `op_type` values 送货卸车, 干线装车,
干线卸车, 提货装车; `hazmat` as 是/否; `orders.csv` is GB18030-encoded, the other two UTF-8 with BOM.

| Problem | Where | Share |
|---|---|---|
| duplicate rows | all three | 1% |
| missing cells | orders: shipper, category, pieces, volume; gate_events: dock, gate_out, plate; appointments: vehicle type | 2% per column |
| other time formats (2026/9/14 8:05, 14-09-2026 08:05, 20260914080500) | time columns | 15% |
| plate formats (浙A·12345, lower case, spaces) | plates | 5% |
| weight with units (0.1507t, 150.7kg, 150.7公斤) | orders 重量 | 16% |
| dock_end before dock_start (the two swapped) | gate_events | 0.3% |
| the year before the run's year in gate_in | gate_events | 0.2% |
| negative volume | orders | 0.2% |

Header mapping (clean → messy):

| Table | Mapping |
|---|---|
| orders | order_id 运单号, date 日期, line_id 专线编号, shipper_id 发货方编号, destination 目的地, category 货物类别, description 货物描述, weight_kg 重量, volume_m3 体积(方), pieces 件数, hazmat_class 危险品类别, dropoff_event_id 送货作业编号, baseline_truck_id 干线车次 |
| gate_events | event_id 作业编号, date 日期, plate 车牌号, appointment_id 预约号, line_id 专线编号, op_type 作业类型, vehicle_type 车型, cargo_volume_m3 货物体积(方), hazmat 是否危险品, truck_id 干线车次, gate_in 入场时间, dock_id 月台号, dock_start 开始作业时间, dock_end 结束作业时间, gate_out 出场时间 |
| appointments | appointment_id 预约号, plate 车牌号, line_id 专线编号, op_type 作业类型, vehicle_type 车型, slot_start 预约开始时间, slot_end 预约结束时间 |

## answer_key/

- `baseline_summary.json`: the config, counts, baseline dock KPIs (wait split into queueing and waiting for cargo,
  late linehaul departures), a naive pooled reference (any dock, first come first served, 15 min extra handling on
  another line's dock; a reference, not a solution) and baseline dispatch KPIs.
- `undeclared_hazmat.csv`, `trajectory_anomalies.csv`, `messy_injected_issues.csv` (table, key, column, issue): one
  row per changed cell, so a swapped dock_start/dock_end pair is two rows; a duplicated row is an exact copy of the
  row after the other injections and is listed once with an empty column.
