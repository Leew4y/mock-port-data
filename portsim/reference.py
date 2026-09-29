"""Fixed reference tables. All figures are approximate or invented; see docs/data_dictionary.md."""

from __future__ import annotations

PORT_LAT, PORT_LON = 30.18, 120.27  # a point near Hangzhou; synthetic

# vehicle_type: (length_m, max_load_kg, volume_m3); rough typical figures for Chinese box trucks
VEHICLE_TYPES = {
    "4.2m": (4.2, 1_800, 16.0),
    "6.8m": (6.8, 8_000, 38.0),
    "9.6m": (9.6, 16_000, 55.0),
    "13m": (13.0, 30_000, 80.0),
    "17.5m": (17.5, 30_000, 110.0),
}
SMALL_VEHICLES = ["4.2m", "6.8m", "9.6m"]

# (city, lat, lon, approx road km from Hangzhou, plate prefix)
DESTINATIONS = [
    ("上海", 31.23, 121.47, 180, "沪A"),
    ("南京", 32.06, 118.80, 280, "苏A"),
    ("合肥", 31.82, 117.23, 400, "皖A"),
    ("南昌", 28.68, 115.86, 550, "赣A"),
    ("福州", 26.07, 119.30, 600, "闽A"),
    ("武汉", 30.59, 114.31, 750, "鄂A"),
    ("长沙", 28.23, 112.94, 900, "湘A"),
    ("郑州", 34.75, 113.62, 950, "豫A"),
    ("广州", 23.13, 113.26, 1250, "粤A"),
    ("西安", 34.34, 108.94, 1300, "陕A"),
    ("重庆", 29.56, 106.55, 1600, "渝A"),
    ("成都", 30.57, 104.07, 1900, "川A"),
]
LOCAL_PLATE_PREFIX = "浙A"

# category: (probability, density kg/m3, items, unit)
CATEGORIES = {
    "服装鞋帽": (0.22, 120, ["男装", "女装", "童装", "运动鞋", "箱包"], "箱"),
    "电子电器": (0.14, 180, ["手机配件", "小家电", "显示器", "路由器"], "箱"),
    "五金工具": (0.14, 550, ["螺丝紧固件", "手动工具", "阀门", "管件"], "箱"),
    "食品饮料": (0.12, 380, ["饮料", "零食", "调味品", "茶叶"], "箱"),
    "机械配件": (0.12, 450, ["轴承", "电机", "齿轮", "泵配件"], "件"),
    "日用百货": (0.18, 200, ["洗护用品", "塑料制品", "纸品", "厨具"], "箱"),
    "纺织原料": (0.08, 300, ["布匹", "纱线", "化纤面料"], "卷"),
}

HAZMAT_CATEGORY = "危险品"
# class: (probability on hazmat lines, items, unit)
HAZMAT_CLASSES = {
    "2.1": (0.05, ["丁烷气雾剂", "打火机充气罐"], "箱"),
    "3": (0.35, ["油漆", "稀释剂", "乙醇溶液", "油墨"], "桶"),
    "4.1": (0.07, ["硫磺", "赛璐珞制品"], "袋"),
    "5.1": (0.08, ["次氯酸钙", "过氧化氢溶液"], "桶"),
    "6.1": (0.10, ["农药", "苯胺"], "桶"),
    "8": (0.20, ["盐酸", "氢氧化钠溶液", "腐蚀性清洗剂"], "桶"),
    "9": (0.15, ["锂离子电池", "锂电池组"], "箱"),
}

# Hazardous goods hidden in general-line orders: (item, likely class, declared category, unit)
UNDECLARED_ITEMS = [
    ("油漆", "3", "日用百货", "桶"),
    ("稀释剂", "3", "五金工具", "桶"),
    ("酒精消毒液", "3", "日用百货", "箱"),
    ("锂电池", "9", "电子电器", "箱"),
    ("打火机", "2.1", "日用百货", "箱"),
    ("农药", "6.1", "日用百货", "瓶"),
]

# ILLUSTRATIVE mixing rules, NOT the JT/T 617.6 table (which was not read). Replace before any real claim.
# Each entry: (a, b) where a and b are hazmat classes or goods categories that must not share a vehicle.
ILLUSTRATIVE_INCOMPATIBLE = [
    ("5.1", "2.1"),
    ("5.1", "3"),
    ("5.1", "4.1"),
    ("6.1", "食品饮料"),
]

# Hour-of-day profiles for planned arrivals: (first hour, weights)
ARRIVAL_PROFILE = {
    "delivery_in": (8, [4, 6, 8, 7, 5, 5, 6, 8, 9, 7]),
    "linehaul_in": (5, [3, 6, 8, 6, 4, 2]),
    "pickup_out": (7, [4, 7, 8, 6, 4, 3, 2]),
}
APPOINTMENT_SHARE = {"delivery_in": 0.30, "linehaul_out": 0.85, "linehaul_in": 0.80, "pickup_out": 0.40}
# (mean, sd) of arrival minus booked time, minutes
ARRIVAL_DELAY = {"delivery_in": (5, 15), "linehaul_out": (0, 12), "linehaul_in": (10, 25), "pickup_out": (5, 15)}
SERVICE_RATE_MIN_PER_M3 = {"delivery_in": 2.5, "linehaul_in": 1.8, "linehaul_out": 2.2, "pickup_out": 2.0}
SERVICE_SETUP_MIN = 10
LOADING_LEAD_MIN = 150  # linehaul loading is booked this long before departure

WEEKDAY_FACTOR = [1.10, 1.00, 1.00, 1.00, 1.05, 0.80, 0.50]
DEPARTURE_TIMES = ["20:30", "21:00", "21:30", "22:00", "22:30", "23:00"]
