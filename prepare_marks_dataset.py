
import pandas as pd
import re
import unicodedata
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "cleaned_data"

marks = pd.read_csv(BASE_DIR / "marks_ledger_cleaned.csv")
attendance = pd.read_csv(
    DATA_DIR / "SY_C_Sem2_2024_25_Attendance.csv"
)

marks_name_col = "student_full_name_as_per_hsc_diploma_be_b_tech"
attendance_name_col = next(
    c for c in attendance.columns if "student_name" in c.lower()
)

def tokens(name):
    if pd.isna(name):
        return set()
    name = unicodedata.normalize("NFKC", str(name)).upper()
    return set(re.findall(r"[A-Z0-9]+", name))

marks = marks[marks[marks_name_col].notna()].copy()
attendance = attendance[attendance[attendance_name_col].notna()].copy()

marks["name_tokens"] = marks[marks_name_col].apply(tokens)
attendance["name_tokens"] = attendance[attendance_name_col].apply(tokens)

results = []

for _, a in attendance.iterrows():
    # Ignore very short names to reduce accidental matches.
    if len(a["name_tokens"]) < 2:
        continue

    candidates = marks[
        marks["name_tokens"].apply(
            lambda m: a["name_tokens"].issubset(m)
        )
    ]

    if len(candidates) == 1:
        status = "UNIQUE CANDIDATE - VERIFY"
        candidate = candidates.iloc[0]
        marks_name = candidate[marks_name_col]
        prn = candidate.get("prn_university_number", "")
    elif len(candidates) > 1:
        status = "AMBIGUOUS - REVIEW"
        marks_name = " | ".join(candidates[marks_name_col].astype(str))
        prn = ""
    else:
        status = "NO CANDIDATE"
        marks_name = ""
        prn = ""

    results.append({
        "attendance_name": a[attendance_name_col],
        "possible_marks_name": marks_name,
        "possible_prn": prn,
        "status": status
    })

result_df = pd.DataFrame(results)

output_path = DATA_DIR / "marks_match_candidates.csv"
result_df.to_csv(output_path, index=False)

print(result_df["status"].value_counts().to_string())
print("\nSample candidate matches:")
print(result_df.head(30).to_string(index=False))
print(f"\nSaved candidates to: {output_path}")
