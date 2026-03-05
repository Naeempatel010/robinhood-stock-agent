def safe_float(val, default=0):
    try:
        return round(float(val), 4) if val not in (None, "N/A", "") else default
    except (TypeError, ValueError):
        return default
