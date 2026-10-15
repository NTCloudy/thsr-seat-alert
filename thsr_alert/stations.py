"""THSR station name -> TDX StationID mapping."""

STATIONS = {
    "南港": "0990",
    "台北": "1000",
    "板橋": "1010",
    "桃園": "1020",
    "新竹": "1030",
    "苗栗": "1035",
    "台中": "1040",
    "彰化": "1043",
    "雲林": "1047",
    "嘉義": "1050",
    "台南": "1060",
    "左營": "1070",
}

ID_TO_NAME = {v: k for k, v in STATIONS.items()}


def station_id(name: str) -> str:
    """Accepts a Chinese name (台/臺 both OK) or a raw 4-digit StationID."""
    key = str(name).strip().replace("臺", "台").replace("站", "")
    if key in STATIONS:
        return STATIONS[key]
    if key in ID_TO_NAME:
        return key
    raise ValueError(f"未知的高鐵站：{name}（可用：{', '.join(STATIONS)}）")
