import json
import pandas as pd
from pathlib import Path
from academic_prediction_pipeline_v6_updated import normalize_branch

workbook = Path("prediction_results/Academic_Prediction_Dataset_V6.xlsx")
output = Path("model_integration/subject_code_registry.json")

df = pd.read_excel(workbook, sheet_name="Subject_Training_Data")

registry = {}

for branch, group in df.groupby("Branch"):
    normalized = normalize_branch(branch)

    if not normalized:
        continue

    codes = sorted(
        group["Target_Subject_Code"]
        .dropna()
        .astype(str)
        .str.strip()
        .str.upper()
        .unique()
        .tolist()
    )

    registry.setdefault(normalized, set()).update(codes)

registry = {
    branch: sorted(codes)
    for branch, codes in registry.items()
}

output.write_text(
    json.dumps(registry, indent=2),
    encoding="utf-8"
)

print("Registry created:", output)
print("Branches:", len(registry))

for branch, codes in registry.items():
    print(f"{branch}: {len(codes)} subject codes")

