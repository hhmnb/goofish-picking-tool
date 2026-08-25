# adjust_to_30_70.py
import json
from pathlib import Path

config_file = Path(__file__).parent / "filter_configs.json"

with open(config_file, "r", encoding="utf-8") as f:
    data = json.load(f)

if "全局精细捡漏" in data:
    models = data["全局精细捡漏"].get("models", [])
    for model in models:
        if not isinstance(model, dict) or not model:
            continue
        if "min_price" in model:
            try:
                old_min = float(model["min_price"])
                # 30% / 50% = 0.6
                new_min = round(old_min * 0.6)
                model["min_price"] = str(new_min)
            except:
                pass
        # max_price 保持不变（70%）

with open(config_file, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("已将最低捡漏价调整为参考价的30%，最高价保持70%。")