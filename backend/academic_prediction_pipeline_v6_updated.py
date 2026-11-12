
"""
ACADEMIC RESULT PREDICTION PIPELINE V6
======================================

Features:
1. Reads historical ZIP files and direct Excel files.
2. Reads user-uploaded Excel ledgers separately for prediction.
3. Preserves valid PRN masking using the existing HMAC key.
4. Preserves actual zero marks and SGPI.
5. Keeps missing maximum marks as NaN.
6. Accepts target subjects interactively; no catalogue is required.
7. Excludes Civil Engineering and Civil & Environmental Engineering.
8. Trains Random Forest + XGBoost hybrid models.
9. Uses student-level train/validation/test splitting.
10. Predicts next-semester subject percentages and marks.
11. Predicts next-semester SGPI.
12. Predicts unseen subject codes with a low-confidence warning.
13. Validates duplicate predictions.
14. Exports an Excel workbook even when no user uploads exist.

IMPORTANT:
- Keep student_mask.key unchanged.
- Historical files go into source_ledgers.
- New student Excel ledgers go into user_uploads.
- Enter target subjects when prompted during execution.
- Never enter assumed maximum marks.
- User-uploaded ledgers are prediction inputs only, NOT training data.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import zipfile
import warnings
import time

from pathlib import Path
from io import BytesIO

import joblib
import numpy as np
import pandas as pd

from openpyxl import load_workbook

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score
)
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from xgboost import XGBRegressor


# ============================================================
# 1. CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parent

INPUT_DIR = ROOT / "source_ledgers"
USER_UPLOAD_DIR = ROOT / "user_uploads"
OUTPUT_DIR = ROOT / "prediction_results"
MODEL_DIR = ROOT / "saved_models_academic"

MASK_KEY_PATH = ROOT / "student_mask.key"

OUTPUT_FILE = (
    OUTPUT_DIR / "Academic_Prediction_Dataset_V6.xlsx"
)

for directory in [
    INPUT_DIR,
    USER_UPLOAD_DIR,
    OUTPUT_DIR,
    MODEL_DIR
]:
    directory.mkdir(parents=True, exist_ok=True)


# Civil branches excluded from training and prediction.
# ENV is deliberately NOT excluded automatically.

EXCLUDED_BRANCHES = {
    "civil engineering",
    "civil & environmental engineering",
    "civil and environmental engineering",
    "civil environmental engineering",
    "cvl",
    "cee"
}

SUBJECT_CODE_RE = re.compile(
    r"^[A-Z]{2,}[A-Z0-9]*\d{4}$",
    re.I
)

SGPI_RE = re.compile(
    r"SGPI\s*SEM(?:ESTER)?\s*(\d+)",
    re.I
)

warnings.filterwarnings(
    "ignore",
    category=UserWarning
)


# ============================================================
# 2. STUDENT MASKING
# ============================================================

def normalize_prn(value):

    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, np.integer)):
        text = str(int(value))

    elif isinstance(value, (float, np.floating)):

        if not np.isfinite(value):
            return None

        text = (
            str(int(value))
            if float(value).is_integer()
            else str(value)
        )

    else:
        text = str(value).strip()

        if text.endswith(".0") and text[:-2].isdigit():
            text = text[:-2]

    digits = re.sub(r"\D", "", text)

    return digits if len(digits) >= 6 else None


def get_mask_key():

    # Reuse the existing key. Never overwrite it.
    if MASK_KEY_PATH.exists():

        key_text = MASK_KEY_PATH.read_text(
            encoding="utf-8"
        ).strip()

        try:
            key = bytes.fromhex(key_text)
        except ValueError as exc:
            raise ValueError(
                "student_mask.key is not a valid hexadecimal key. "
                "Do not delete or regenerate it. Restore the original key."
            ) from exc

        if len(key) != 32:
            raise ValueError(
                "student_mask.key must contain the original 32-byte key."
            )

        return key

    # Create a key only if this is the first run.
    key = secrets.token_bytes(32)

    MASK_KEY_PATH.write_text(
        key.hex(),
        encoding="utf-8"
    )

    print(
        "\nA new student_mask.key was created because none existed."
    )

    return key


MASK_KEY = get_mask_key()


def mask_prn(prn):

    return hmac.new(
        MASK_KEY,
        prn.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()[:20]


# ============================================================
# 3. BRANCH NORMALIZATION AND FILTERING
# ============================================================



def normalize_branch(branch):
    """
    Standardise equivalent branch names.
    Keep CSE, CSBS, AIML, DS, CVL and CEE separate.
    """

    if pd.isna(branch):
        return ""

    value = str(branch).strip().lower()
    compact = re.sub(r"[^a-z0-9]", "", value)

    branch_aliases = {

        # Computer Science and Engineering
        "cse": "cse",
        "computerscienceandengineering": "cse",
        "computerscienceengineering": "cse",
        "computerscienceengg": "cse",
        "computerscience": "cse",

        # Computer Science and Business Systems
        "csbs": "csbs",
        "computerscienceandbusinesssystems": "csbs",
        "computersciencebusinesssystems": "csbs",
        "computerscienceandbusinesssystem": "csbs",
        "computersciencebusinesssystem": "csbs",

        # Artificial Intelligence and Machine Learning
        "aiml": "aiml",
        "aiandml": "aiml",
        "artificialintelligenceandmachinelearning": "aiml",
        "artificialintelligenceandml": "aiml",
        "artificialintelligencemachinelearning": "aiml",
        "cseaiml": "aiml",

        # Data Science
        "ds": "ds",
        "datascience": "ds",
        "datascienceengineering": "ds",
        "cseds": "ds",

        # Electronics and Telecommunication
        "etc": "etc",
        "entc": "etc",
        "eandtc": "etc",
        "electronicsandtelecommunication": "etc",
        "electronicsandtelecommunications": "etc",
        "electronicsandtelecommunicationengineering": "etc",

        # Mechanical
        "mech": "mechanical",
        "mechanical": "mechanical",
        "mechanicalengineering": "mechanical",

        # CVL - Civil Engineering
        "cvl": "cvl",
        "civil": "cvl",
        "civilengineering": "cvl",

        # CEE - Civil and Environmental Engineering
        "cee": "cee",
        "civilandenvironmentalengineering": "cee",
        "civilenvironmentalengineering": "cee",

        # Electrical
        "electrical": "electrical",
        "electricalengineering": "electrical",
    }

    return branch_aliases.get(compact, compact)



def is_excluded_branch(branch):

    value = normalize_branch(branch)

    if not value:
        return False

    excluded_normalized = {
        normalize_branch(x)
        for x in EXCLUDED_BRANCHES
    }

    if value in excluded_normalized:
        return True

    # Catch longer branch names containing Civil Engineering.
    # Do not exclude unrelated names such as Environmental Engineering.
    original = str(branch).strip().lower()

    if re.search(
        r"\bcivil\b.*\bengineering\b",
        original
    ):
        return True

    if re.search(
        r"\bengineering\b.*\bcivil\b",
        original
    ):
        return True

    return False


def filter_supported_branches(subjects, sgpi):

    if not subjects.empty:
        subjects = subjects[
            ~subjects["Branch"].apply(is_excluded_branch)
        ].copy()

    if not sgpi.empty:
        sgpi = sgpi[
            ~sgpi["Branch"].apply(is_excluded_branch)
        ].copy()

    return (
        subjects.reset_index(drop=True),
        sgpi.reset_index(drop=True)
    )


def build_branch_report(subjects, sgpi, user_subjects=None):

    rows = []

    frames = []

    if not subjects.empty:
        temp = subjects[["Branch"]].copy()
        temp["Source"] = "Historical Training Data"
        frames.append(temp)

    if not sgpi.empty:
        temp = sgpi[["Branch"]].copy()
        temp["Source"] = "Historical SGPI Data"
        frames.append(temp)

    if user_subjects is not None and not user_subjects.empty:
        temp = user_subjects[["Branch"]].copy()
        temp["Source"] = "User Upload"
        frames.append(temp)

    if not frames:
        return pd.DataFrame(
            columns=[
                "Branch",
                "Normalized_Branch",
                "Source",
                "Status"
            ]
        )

    combined = pd.concat(
        frames,
        ignore_index=True
    )

    combined["Normalized_Branch"] = (
        combined["Branch"].apply(normalize_branch)
    )

    combined = combined.drop_duplicates(
        subset=["Branch", "Source"]
    )

    for row in combined.itertuples(index=False):

        rows.append({

            "Branch": row.Branch,
            "Normalized_Branch": row.Normalized_Branch,
            "Source": row.Source,

            "Status": (
                "EXCLUDED"
                if is_excluded_branch(row.Branch)
                else "SUPPORTED_FOR_PIPELINE"
            )

        })

    return pd.DataFrame(rows)


# ============================================================
# 4. GENERAL UTILITIES
# ============================================================

def as_number(value):

    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value) if np.isfinite(value) else None

    text = str(value).strip().replace(",", "")

    if not text or text.upper() in {
        "AB", "NP", "NA", "N/A", "-", "F1"
    }:
        return None

    try:
        number = float(text)
        return number if np.isfinite(number) else None
    except ValueError:
        return None


def cell_text(value):

    return str(value).strip() if value is not None else ""


def first_line(value):

    text = cell_text(value)

    return text.splitlines()[0].strip() if text else ""


def get_academic_year(filename):

    match = re.search(
        r"(20\d{2})\s*[-_]\s*(\d{2,4})",
        filename
    )

    if match:

        start = match.group(1)
        end = match.group(2)

        if len(end) == 4:
            end = end[-2:]

        return f"{start}-{end}"

    return Path(filename).stem


def subject_type_from_name(name):

    value = str(name).lower()

    if "lab" in value or "laboratory" in value:
        return "LAB"

    if any(
        word in value
        for word in ["project", "internship", "dissertation"]
    ):
        return "PROJECT"

    if "audit" in value:
        return "AUDIT"

    return "THEORY_OR_OTHER"


# ============================================================
# 5. MANUAL TARGET SUBJECT INPUT
# ============================================================

def collect_target_subjects():
    """
    Collect target subjects at runtime. Semester may be left blank;
    blank means predict for each student's inferred next semester.
    No assumed marks or predefined catalogue are used.
    """
    columns = [
        "Branch", "Semester", "Subject_Code", "Subject_Name",
        "Max_Marks", "Min_Marks"
    ]
    print("\n" + "=" * 65)
    print("MANUAL NEXT-SEMESTER SUBJECT INPUT")
    print("=" * 65)
    print("Enter the exact branch name as shown in the uploaded ledger.")
    print("Leave semester blank to infer latest semester + 1.")
    print("Enter 0 subjects to skip subject predictions.")
    while True:
        try:
            count = int(input("\nHow many target subjects do you want to enter? ").strip())
            if count >= 0:
                break
        except ValueError:
            pass
        print("Please enter a valid whole number (0 or more).")

    rows = []
    for i in range(count):
        print(f"\nTarget subject {i + 1}/{count}")
        branch = input("Branch name: ").strip()
        code = input("Subject code: ").strip().upper()
        name = input("Subject name: ").strip()
        sem_text = input("Target semester (blank = infer): ").strip()
        max_text = input("Maximum marks (required): ").strip()
        min_text = input("Minimum marks (optional; press Enter if unknown): ").strip()

        try:
            semester = int(sem_text) if sem_text else np.nan
            if not pd.isna(semester) and not 1 <= semester <= 8:
                raise ValueError
        except ValueError:
            print("Invalid semester; this subject entry is skipped.")
            continue

        maximum = as_number(max_text)
        minimum = as_number(min_text) if min_text else np.nan

        if not branch or not code or not name:
            print("Branch, subject code and subject name are required. Entry skipped.")
            continue
        if maximum is None or maximum <= 0:
            print("A valid maximum mark is required. Entry skipped.")
            continue
        if minimum is not None and not pd.isna(minimum) and minimum < 0:
            print("Minimum marks cannot be negative. Entry skipped.")
            continue
        if minimum is not None and not pd.isna(minimum) and minimum > maximum:
            print("Minimum marks cannot exceed maximum marks. Entry skipped.")
            continue
        if is_excluded_branch(branch):
            print("This branch is excluded by the pipeline. Entry skipped.")
            continue

        rows.append({
            "Branch": branch, "Semester": semester,
            "Subject_Code": code, "Subject_Name": name,
            "Max_Marks": maximum, "Min_Marks": minimum
        })

    result = pd.DataFrame(rows, columns=columns)
    print(f"\nAccepted target subjects: {len(result)}")
    return result


def get_code_pattern_features(code):
    """Generic code parsing; no fixed branch/semester grammar is assumed."""
    value = str(code).strip().upper()
    prefix_match = re.match(r"^[A-Z]+", value)
    digit_match = re.search(r"\d+", value)
    suffix_match = re.search(r"[A-Z]+$", value)
    prefix = prefix_match.group(0) if prefix_match else ""
    digits = digit_match.group(0) if digit_match else ""
    suffix = suffix_match.group(0) if suffix_match else ""
    return {
        "Target_Code_Prefix": prefix,
        "Target_Code_Digits": digits,
        "Target_Code_Suffix": suffix,
        "Target_Code_Length": len(value)
    }


# ============================================================
# 6. LEDGER LAYOUT DETECTION
# ============================================================

def detect_layout(ws):

    ws.reset_dimensions()

    scan_max_col = min(
        ws.max_column or 1000,
        2000
    )

    scan_max_row = min(
        ws.max_row or 40,
        15
    )

    rows = {}
    candidates = []

    for ridx, row in enumerate(
        ws.iter_rows(
            min_row=1,
            max_row=scan_max_row,
            max_col=scan_max_col,
            values_only=True
        ),
        start=1
    ):

        rows[ridx] = row
        codes = []

        for cidx, value in enumerate(row):

            code = first_line(value).upper()

            if SUBJECT_CODE_RE.fullmatch(code):
                codes.append((cidx, code))

        if len(codes) >= 3:
            candidates.append((ridx, codes))

    if not candidates:
        return None

    header_row, codes = max(
        candidates,
        key=lambda x: len(x[1])
    )

    header_values = rows[header_row]

    subheader_row = None

    for ridx in range(
        header_row + 1,
        min(header_row + 7, scan_max_row + 1)
    ):

        if any(
            cell_text(v).upper() == "TOTAL"
            for v in rows.get(ridx, ())
        ):
            subheader_row = ridx
            break

    if subheader_row is None:
        return None

    prn_col = None

    for cidx, value in enumerate(header_values):

        label = cell_text(value).upper()

        if (
            "PRN" in label
            or "UNIVERSITY NUMBER" in label
        ):
            prn_col = cidx
            break

    if prn_col is None:
        return None

    sgpi_cols = {}

    for ridx in range(
        max(1, header_row - 1),
        min(scan_max_row, header_row + 3) + 1
    ):

        for cidx, value in enumerate(
            rows.get(ridx, ())
        ):

            match = SGPI_RE.search(
                cell_text(value)
            )

            if match:
                sgpi_cols[int(match.group(1))] = cidx

    data_start = None

    for ridx in range(
        subheader_row + 1,
        min(subheader_row + 30, scan_max_row + 1)
    ):

        row = rows.get(ridx, ())

        if (
            prn_col < len(row)
            and normalize_prn(row[prn_col])
        ):
            data_start = ridx
            break

    if data_start is None:
        return None

    # Keep the existing heuristic, but do not assume a value
    # exists when the row does not contain a valid number.
    max_marks_row = (
        data_start - 1
        if data_start - 1 > subheader_row
        else None
    )

    branch = ws.title

    for ridx in range(
        1,
        min(scan_max_row, 10) + 1
    ):

        for value in rows.get(ridx, ()):

            text = cell_text(value)

            match = re.search(
                r"Branch\s*:\s*(.+)",
                text,
                re.I
            )

            if match:
                branch = match.group(1).strip()
                break

    subheaders = rows[subheader_row]

    positions = [c for c, _ in codes]

    subject_specs = []

    for pos, code in codes:

        next_pos = min(
            [c for c in positions if c > pos]
            or [pos + 12]
        )

        total_col = None
        grade_col = None

        for cidx in range(
            pos,
            min(next_pos, len(subheaders))
        ):

            label = cell_text(
                subheaders[cidx]
            ).upper()

            if label == "TOTAL":
                total_col = cidx

            elif label in {"GR", "GRADE"}:
                grade_col = cidx

        if total_col is None:
            continue

        if grade_col is None:
            grade_col = total_col + 1

        raw_header = cell_text(
            header_values[pos]
        )

        parts = [
            p.strip()
            for p in raw_header.splitlines()
            if p.strip()
        ]

        if len(parts) > 1:
            subject_name = parts[1]
        else:
            name_row = rows.get(
                header_row + 1,
                ()
            )

            subject_name = (
                cell_text(name_row[pos])
                if pos < len(name_row)
                else code
            )

        try:
            semester = int(code[-4:-2])
        except ValueError:
            continue

        if not 1 <= semester <= 8:
            continue

        max_marks = None

        if max_marks_row is not None:

            max_value = next(
                ws.iter_rows(
                    min_row=max_marks_row,
                    max_row=max_marks_row,
                    min_col=total_col + 1,
                    max_col=total_col + 1,
                    values_only=True
                ),
                (None,)
            )

            max_marks = as_number(max_value[0])

        subject_specs.append({

            "code": code,
            "name": subject_name,
            "semester": semester,
            "total_col": total_col,
            "grade_col": grade_col,
            "max_marks": max_marks

        })

    if not subject_specs:
        return None

    max_col = max(
        [prn_col]
        + [s["grade_col"] for s in subject_specs]
        + list(sgpi_cols.values() or [0])
    ) + 1

    return {

        "data_start": data_start,
        "prn_col": prn_col,
        "sgpi_cols": sgpi_cols,
        "subject_specs": subject_specs,
        "branch": branch,
        "max_col": max_col,
        "max_row": ws.max_row or 10000

    }


# ============================================================
# 7. EXTRACT ONE EXCEL WORKBOOK
# ============================================================

def extract_workbook_bytes(
    workbook_bytes,
    workbook_name,
    academic_year
):

    subject_rows = []
    sgpi_rows = []
    logs = []

    workbook = load_workbook(
        BytesIO(workbook_bytes),
        read_only=True,
        data_only=True
    )

    try:

        for ws in workbook.worksheets:

            layout = detect_layout(ws)

            if not layout:

                logs.append({

                    "Workbook": workbook_name,
                    "Sheet": ws.title,
                    "Status": "Layout not detected",
                    "Subject_Codes": 0,
                    "Branch": ws.title

                })

                continue

            for ridx, row in enumerate(
                ws.iter_rows(
                    min_row=layout["data_start"],
                    max_row=layout["max_row"],
                    max_col=layout["max_col"],
                    values_only=True
                ),
                start=layout["data_start"]
            ):

                prn = normalize_prn(
                    row[layout["prn_col"]]
                    if layout["prn_col"] < len(row)
                    else None
                )

                if not prn:
                    continue

                masked_id = mask_prn(prn)

                # SGPI extraction.
                for sem, col in layout["sgpi_cols"].items():

                    value = as_number(
                        row[col]
                        if col < len(row)
                        else None
                    )

                    if (
                        value is not None
                        and 0 <= value <= 10
                    ):

                        sgpi_rows.append({

                            "Masked_ID": masked_id,
                            "Branch": layout["branch"],
                            "Academic_Year": academic_year,
                            "Semester": sem,
                            "SGPI": value,
                            "Source_Workbook": workbook_name,
                            "Source_Sheet": ws.title

                        })

                # Subject marks extraction.
                for spec in layout["subject_specs"]:

                    col = spec["total_col"]

                    marks = as_number(
                        row[col]
                        if col < len(row)
                        else None
                    )

                    # Zero marks are valid and must be preserved.
                    if marks is None:
                        continue

                    grade = cell_text(
                        row[spec["grade_col"]]
                        if spec["grade_col"] < len(row)
                        else ""
                    )

                    subject_rows.append({

                        "Masked_ID": masked_id,
                        "Branch": layout["branch"],
                        "Academic_Year": academic_year,
                        "Semester": spec["semester"],
                        "Subject_Code": spec["code"],
                        "Subject_Name": spec["name"],
                        "Total_Marks": marks,
                        "Max_Marks": spec["max_marks"],
                        "Min_Marks": np.nan,
                        "Grade": grade,
                        "Source_Workbook": workbook_name,
                        "Source_Sheet": ws.title

                    })

            logs.append({

                "Workbook": workbook_name,
                "Sheet": ws.title,
                "Status": "Extracted",
                "Subject_Codes": len(
                    layout["subject_specs"]
                ),
                "Branch": layout["branch"]

            })

    finally:
        workbook.close()

    return subject_rows, sgpi_rows, logs


# ============================================================
# 8. EXTRACT ZIP AND DIRECT EXCEL FILES
# ============================================================

def extract_zip(zip_path):

    all_subjects = []
    all_sgpi = []
    all_logs = []

    academic_year = get_academic_year(
        zip_path.name
    )

    with zipfile.ZipFile(zip_path) as archive:

        members = [
            n for n in archive.namelist()
            if (
                n.lower().endswith(".xlsx")
                and not Path(n).name.startswith("~$")
            )
        ]

        for number, member in enumerate(
            members,
            start=1
        ):

            print(
                f"  Reading {number}/{len(members)}: "
                f"{Path(member).name}"
            )

            try:

                subjects, sgpi, logs = extract_workbook_bytes(
                    archive.read(member),
                    Path(member).name,
                    academic_year
                )

                all_subjects.extend(subjects)
                all_sgpi.extend(sgpi)
                all_logs.extend(logs)

            except Exception as exc:

                all_logs.append({

                    "Workbook": Path(member).name,
                    "Sheet": "",
                    "Status": (
                        f"ERROR: {type(exc).__name__}: {exc}"
                    ),
                    "Subject_Codes": 0,
                    "Branch": ""

                })

    return all_subjects, all_sgpi, all_logs


def extract_direct_excel(excel_path):

    academic_year = get_academic_year(
        excel_path.name
    )

    return extract_workbook_bytes(
        excel_path.read_bytes(),
        excel_path.name,
        academic_year
    )


def extract_training_files():

    all_subjects = []
    all_sgpi = []
    all_logs = []

    zip_files = sorted(
        INPUT_DIR.glob("*.zip")
    )

    excel_files = sorted(
        [
            p for p in INPUT_DIR.glob("*.xlsx")
            if not p.name.startswith("~$")
        ]
    )

    files = zip_files + excel_files

    if not files:
        raise FileNotFoundError(
            "No historical ZIP or Excel files found in source_ledgers."
        )

    for path in files:

        print(
            f"\nProcessing historical file: {path.name}"
        )

        if path.suffix.lower() == ".zip":
            subjects, sgpi, logs = extract_zip(path)
        else:
            subjects, sgpi, logs = extract_direct_excel(path)

        all_subjects.extend(subjects)
        all_sgpi.extend(sgpi)
        all_logs.extend(logs)

        print(
            f"Subject records: {len(subjects):,}; "
            f"SGPI records: {len(sgpi):,}"
        )

    return (
        pd.DataFrame(all_subjects),
        pd.DataFrame(all_sgpi),
        pd.DataFrame(all_logs)
    )


def extract_user_uploads():

    files = sorted(
        [
            p for p in USER_UPLOAD_DIR.glob("*.xlsx")
            if not p.name.startswith("~$")
        ]
    )

    if not files:

        print(
            "\nNo user Excel files found in user_uploads."
        )

        return (
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame()
        )

    all_subjects = []
    all_sgpi = []
    all_logs = []

    for path in files:

        print(
            f"\nReading user-uploaded ledger: {path.name}"
        )

        try:

            subjects, sgpi, logs = extract_direct_excel(path)

            all_subjects.extend(subjects)
            all_sgpi.extend(sgpi)
            all_logs.extend(logs)

        except Exception as exc:

            all_logs.append({

                "Workbook": path.name,
                "Sheet": "",
                "Status": (
                    f"ERROR: {type(exc).__name__}: {exc}"
                ),
                "Subject_Codes": 0,
                "Branch": ""

            })

            print(
                f"Could not read {path.name}: "
                f"{type(exc).__name__}: {exc}"
            )

    return (
        pd.DataFrame(all_subjects),
        pd.DataFrame(all_sgpi),
        pd.DataFrame(all_logs)
    )


# ============================================================
# 9. CLEAN DATA
# ============================================================

def clean_data(subjects, sgpi):

    if not subjects.empty:

        subjects = subjects.copy()

        for col in [
            "Masked_ID",
            "Branch",
            "Subject_Code",
            "Subject_Name"
        ]:

            subjects[col] = (
                subjects[col]
                .astype("string")
                .str.strip()
            )

        subjects["Semester"] = pd.to_numeric(
            subjects["Semester"],
            errors="coerce"
        )

        subjects["Total_Marks"] = pd.to_numeric(
            subjects["Total_Marks"],
            errors="coerce"
        )

        subjects["Max_Marks"] = pd.to_numeric(
            subjects["Max_Marks"],
            errors="coerce"
        )

        subjects = subjects.dropna(
            subset=[
                "Masked_ID",
                "Branch",
                "Semester",
                "Subject_Code",
                "Total_Marks"
            ]
        )

        subjects = subjects[
            subjects["Semester"] > 0
        ].copy()

        subjects = subjects.drop_duplicates(
            subset=[
                "Masked_ID",
                "Branch",
                "Academic_Year",
                "Semester",
                "Subject_Code",
                "Subject_Name",
                "Total_Marks"
            ]
        )

        subjects.reset_index(
            drop=True,
            inplace=True
        )

    if not sgpi.empty:

        sgpi = sgpi.copy()

        sgpi["SGPI"] = pd.to_numeric(
            sgpi["SGPI"],
            errors="coerce"
        )

        sgpi["Semester"] = pd.to_numeric(
            sgpi["Semester"],
            errors="coerce"
        )

        sgpi = sgpi.dropna(
            subset=[
                "Masked_ID",
                "Branch",
                "Semester",
                "SGPI"
            ]
        )

        sgpi = sgpi[
            sgpi["SGPI"].between(0, 10)
            & (sgpi["Semester"] > 0)
        ].copy()

        sgpi = (
            sgpi.groupby(
                [
                    "Masked_ID",
                    "Branch",
                    "Semester"
                ],
                as_index=False
            )
            .agg(
                SGPI=("SGPI", "median"),
                Academic_Year=("Academic_Year", "first")
            )
        )

    return subjects, sgpi


# ============================================================
# 10. FEATURE ENGINEERING
# ============================================================

def get_previous_features(previous, previous_sgpi):

    marks = pd.to_numeric(
        previous["Total_Marks"],
        errors="coerce"
    ).dropna()

    if marks.empty:
        return None

    maxima = pd.to_numeric(
        previous["Max_Marks"],
        errors="coerce"
    )

    percentages = (
        pd.to_numeric(
            previous["Total_Marks"],
            errors="coerce"
        )
        / maxima.replace(0, np.nan)
        * 100
    )

    percentages = percentages.where(
        percentages.between(0, 100)
    ).dropna()

    return {

        "Previous_SGPI": previous_sgpi,

        "Previous_Mean_Percentage": (
            percentages.mean()
            if not percentages.empty
            else np.nan
        ),

        "Previous_Std_Percentage": (
            percentages.std(ddof=0)
            if len(percentages) > 1
            else np.nan
        ),

        "Previous_Min_Percentage": (
            percentages.min()
            if not percentages.empty
            else np.nan
        ),

        "Previous_Max_Percentage": (
            percentages.max()
            if not percentages.empty
            else np.nan
        ),

        "Previous_Median_Percentage": (
            percentages.median()
            if not percentages.empty
            else np.nan
        ),

        "Previous_Valid_Percentage_Count": len(
            percentages
        )

    }


def get_family_features(previous, target_code):

    code = str(target_code).strip().upper()
    family = code[:4]

    previous_codes = (
        previous["Subject_Code"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    family_rows = previous.loc[
        previous_codes.str[:4] == family
    ]

    marks = pd.to_numeric(
        family_rows["Total_Marks"],
        errors="coerce"
    )

    maxima = pd.to_numeric(
        family_rows["Max_Marks"],
        errors="coerce"
    )

    percentages = (
        marks / maxima.replace(0, np.nan) * 100
    )

    percentages = percentages.where(
        percentages.between(0, 100)
    ).dropna()

    return {

        "Target_Subject_Family": family,

        "Previous_Family_Mean_Percentage": (
            percentages.mean()
            if not percentages.empty
            else np.nan
        ),

        "Previous_Family_Median_Percentage": (
            percentages.median()
            if not percentages.empty
            else np.nan
        ),

        "Previous_Family_Subject_Count": len(
            percentages
        )

    }


# ============================================================
# 11. BUILD TRAINING TABLES
# ============================================================

def build_training_tables(subjects, sgpi):

    subject_rows = []
    sgpi_rows = []

    stats = {

        "Students_Checked": 0,
        "Missing_Previous_Semester": 0,
        "Missing_Next_Semester": 0,
        "Missing_Previous_Features": 0,
        "Target_Rows_Examined": 0,
        "Missing_Max_Marks": 0,
        "Invalid_Max_Marks": 0,
        "Missing_Target_Marks": 0,
        "Negative_Target_Marks": 0,
        "Marks_Greater_Than_Max": 0,
        "Valid_Target_Rows": 0

    }

    if subjects.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(
            list(stats.items()),
            columns=["Diagnostic", "Count"]
        )

    sgpi_lookup = {}

    if not sgpi.empty:

        for row in sgpi.itertuples(index=False):

            sgpi_lookup[
                (
                    row.Masked_ID,
                    row.Branch,
                    int(row.Semester)
                )
            ] = float(row.SGPI)

    # SUBJECT TRAINING DATA

    for (sid, branch), student in subjects.groupby(
        ["Masked_ID", "Branch"]
    ):

        stats["Students_Checked"] += 1

        semester_groups = {
            int(sem): group
            for sem, group in student.groupby("Semester")
        }

        for previous_sem in range(1, 8):

            next_sem = previous_sem + 1

            previous = semester_groups.get(previous_sem)
            following = semester_groups.get(next_sem)

            if previous is None:
                stats["Missing_Previous_Semester"] += 1
                continue

            if following is None:
                stats["Missing_Next_Semester"] += 1
                continue

            previous_sgpi = sgpi_lookup.get(
                (sid, branch, previous_sem)
            )

            features = get_previous_features(
                previous,
                previous_sgpi
            )

            if features is None:
                stats["Missing_Previous_Features"] += 1
                continue

            for target in following.itertuples(index=False):

                stats["Target_Rows_Examined"] += 1

                maximum = as_number(target.Max_Marks)
                marks = as_number(target.Total_Marks)

                if maximum is None:
                    stats["Missing_Max_Marks"] += 1
                    continue

                if maximum <= 0:
                    stats["Invalid_Max_Marks"] += 1
                    continue

                if marks is None:
                    stats["Missing_Target_Marks"] += 1
                    continue

                if marks < 0:
                    stats["Negative_Target_Marks"] += 1
                    continue

                if marks > maximum:
                    stats["Marks_Greater_Than_Max"] += 1
                    continue

                percentage = marks / maximum * 100

                family = get_family_features(
                    previous,
                    target.Subject_Code
                )

                subject_rows.append({

                    "Masked_ID": sid,
                    "Branch": branch,
                    "Previous_Semester": previous_sem,
                    "Next_Semester": next_sem,

                    **features,

                    "Target_Max_Marks": maximum,
                    "Target_Subject_Code": target.Subject_Code,
                    "Target_Subject_Family": family[
                        "Target_Subject_Family"
                    ],

                    "Target_Subject_Type": subject_type_from_name(
                        target.Subject_Name
                    ),

                    "Target_Code_Prefix": get_code_pattern_features(target.Subject_Code)["Target_Code_Prefix"],
                    "Target_Code_Digits": get_code_pattern_features(target.Subject_Code)["Target_Code_Digits"],
                    "Target_Code_Suffix": get_code_pattern_features(target.Subject_Code)["Target_Code_Suffix"],
                    "Target_Code_Length": get_code_pattern_features(target.Subject_Code)["Target_Code_Length"],
                    "Target_Subject_Name": str(target.Subject_Name),

                    "Previous_Family_Mean_Percentage": family[
                        "Previous_Family_Mean_Percentage"
                    ],

                    "Previous_Family_Median_Percentage": family[
                        "Previous_Family_Median_Percentage"
                    ],

                    "Previous_Family_Subject_Count": family[
                        "Previous_Family_Subject_Count"
                    ],

                    "Target_Percentage": percentage,
                    "Target_Marks": marks

                })

                stats["Valid_Target_Rows"] += 1

    # SGPI TRAINING DATA

    if not sgpi.empty:

        for (sid, branch), student in sgpi.groupby(
            ["Masked_ID", "Branch"]
        ):

            sem_map = {
                int(row.Semester): float(row.SGPI)
                for row in student.itertuples(index=False)
            }

            for previous_sem in range(1, 8):

                next_sem = previous_sem + 1

                if (
                    previous_sem not in sem_map
                    or next_sem not in sem_map
                ):
                    continue

                previous_sgpi = sem_map[previous_sem]

                previous2 = sem_map.get(
                    previous_sem - 1
                )

                sgpi_rows.append({

                    "Masked_ID": sid,
                    "Branch": branch,
                    "Previous_Semester": previous_sem,
                    "Next_Semester": next_sem,
                    "Previous_SGPI": previous_sgpi,
                    "Previous2_SGPI": previous2,

                    "SGPI_Trend": (
                        previous_sgpi - previous2
                        if previous2 is not None
                        else np.nan
                    ),

                    "Target_SGPI": sem_map[next_sem]

                })

    print("\n" + "=" * 60)
    print("SUBJECT TRAINING DATA DIAGNOSTICS")
    print("=" * 60)

    for reason, count in stats.items():
        print(f"{reason:<35}: {count:,}")

    print("-" * 60)
    print(f"{'Total subject training rows':<35}: {len(subject_rows):,}")
    print(f"{'Total SGPI training rows':<35}: {len(sgpi_rows):,}")
    print("=" * 60)

    diagnostics = pd.DataFrame(
        list(stats.items()),
        columns=["Diagnostic", "Count"]
    )

    return (
        pd.DataFrame(subject_rows),
        pd.DataFrame(sgpi_rows),
        diagnostics
    )


# ============================================================
# 12. MODEL PIPELINE
# ============================================================

def make_pipeline(categorical, numeric, estimator):

    transformers = []

    if categorical:

        transformers.append((
            "cat",

            Pipeline([
                (
                    "imputer",
                    SimpleImputer(strategy="most_frequent")
                ),
                (
                    "onehot",
                    OneHotEncoder(handle_unknown="ignore")
                )
            ]),

            categorical
        ))

    if numeric:

        transformers.append((
            "num",

            Pipeline([
                (
                    "imputer",
                    SimpleImputer(strategy="median")
                )
            ]),

            numeric
        ))

    preprocessor = ColumnTransformer(
        transformers,
        remainder="drop"
    )

    return Pipeline([
        ("preprocess", preprocessor),
        ("model", estimator)
    ])


# ============================================================
# 13. TRAIN HYBRID MODELS
# ============================================================

def train_hybrid(
    df,
    target,
    task_name,
    model_path,
    test_prediction_rows
):

    # Remove any old model first.
    # This prevents accidental reuse of stale models.
    if model_path.exists():
        model_path.unlink()

    if df.empty:

        print(
            f"No training data available for {task_name}."
        )

        return None, None

    if target == "Target_Percentage":

        feature_cols = [

            "Branch",
            "Previous_Semester",
            "Next_Semester",
            "Previous_SGPI",
            "Previous_Mean_Percentage",
            "Previous_Std_Percentage",
            "Previous_Min_Percentage",
            "Previous_Max_Percentage",
            "Previous_Median_Percentage",
            "Previous_Valid_Percentage_Count",
            "Target_Max_Marks",
            "Target_Code_Prefix",
            "Target_Code_Digits",
            "Target_Code_Suffix",
            "Target_Code_Length",
            "Target_Subject_Name",
            "Target_Subject_Type",
            "Previous_Family_Mean_Percentage",
            "Previous_Family_Median_Percentage",
            "Previous_Family_Subject_Count"

        ]

    else:

        feature_cols = [

            "Branch",
            "Previous_Semester",
            "Next_Semester",
            "Previous_SGPI",
            "Previous2_SGPI",
            "SGPI_Trend"

        ]

    X = df[feature_cols].copy()

    y = pd.to_numeric(
        df[target],
        errors="coerce"
    )

    valid = y.notna()

    if target == "Target_Percentage":
        valid &= y.between(0, 100)

    X = X.loc[valid].reset_index(drop=True)
    y = y.loc[valid].reset_index(drop=True)
    valid_df = df.loc[valid].reset_index(drop=True)

    groups = (
        valid_df["Masked_ID"]
        .astype(str)
        .reset_index(drop=True)
    )

    # Remove columns that are entirely empty.
    usable = [
        col for col in X.columns
        if X[col].notna().any()
    ]

    X = X[usable]

    if len(X) < 30 or groups.nunique() < 8:

        print(
            f"Insufficient training data for {task_name}: "
            f"{len(X)} rows, {groups.nunique()} students."
        )

        return None, None

    # Outer student-level train/test split.
    splitter = GroupShuffleSplit(
        n_splits=1,
        test_size=0.20,
        random_state=42
    )

    try:

        train_idx, test_idx = next(
            splitter.split(X, y, groups)
        )

    except ValueError as exc:

        print(
            f"Could not create train/test split for {task_name}: {exc}"
        )

        return None, None

    X_train = X.iloc[train_idx]
    X_test = X.iloc[test_idx]

    y_train = y.iloc[train_idx]
    y_test = y.iloc[test_idx]

    train_groups = groups.iloc[train_idx]

    categorical = X.select_dtypes(
        include=["object", "category", "string"]
    ).columns.tolist()

    numeric = [
        col for col in X.columns
        if col not in categorical
    ]

    def create_rf():

        return make_pipeline(
            categorical,
            numeric,
            RandomForestRegressor(
                n_estimators=120,
                max_depth=18,
                max_features=0.8,
                min_samples_leaf=3,
                random_state=42,
                n_jobs=1
            )
        )

    def create_xgb():

        return make_pipeline(
            categorical,
            numeric,
            XGBRegressor(
                n_estimators=220,
                max_depth=4,
                learning_rate=0.04,
                min_child_weight=3,
                subsample=0.85,
                colsample_bytree=0.85,
                reg_lambda=1.5,
                objective="reg:squarederror",
                eval_metric="rmse",
                random_state=42,
                n_jobs=1,
                verbosity=0
            )
        )

    print(f"\nTraining {task_name}...")
    print(f"Training rows: {len(X_train):,}")
    print(f"Testing rows: {len(X_test):,}")

    # Inner student-level train/validation split.
    validation_splitter = GroupShuffleSplit(
        n_splits=1,
        test_size=0.20,
        random_state=43
    )

    try:

        inner_train, inner_val = next(
            validation_splitter.split(
                X_train,
                y_train,
                train_groups
            )
        )

    except ValueError as exc:

        print(
            f"Could not create validation split for {task_name}: {exc}"
        )

        return None, None

    X_inner_train = X_train.iloc[inner_train]
    y_inner_train = y_train.iloc[inner_train]

    X_inner_val = X_train.iloc[inner_val]
    y_inner_val = y_train.iloc[inner_val]

    # Train temporary models only on inner training students.
    rf_temp = create_rf()
    xgb_temp = create_xgb()

    try:

        rf_temp.fit(
            X_inner_train,
            y_inner_train
        )

        xgb_temp.fit(
            X_inner_train,
            y_inner_train
        )

    except Exception as exc:

        print(
            f"Model training failed for {task_name}: "
            f"{type(exc).__name__}: {exc}"
        )

        return None, None

    rf_val = rf_temp.predict(X_inner_val)
    xgb_val = xgb_temp.predict(X_inner_val)

    # Select RF/XGBoost blend weight using validation data only.
    best_weight = 0.5
    best_mae = float("inf")

    for weight in np.linspace(0, 1, 21):

        combined = (
            weight * rf_val
            + (1 - weight) * xgb_val
        )

        error = mean_absolute_error(
            y_inner_val,
            combined
        )

        if error < best_mae:

            best_mae = error
            best_weight = float(weight)

    print(f"Selected RF weight: {best_weight:.2f}")
    print(f"Selected XGBoost weight: {1-best_weight:.2f}")
    print(f"Validation MAE: {best_mae:.4f}")

    # Train final models on the full outer training set.
    rf = create_rf()
    xgb = create_xgb()

    try:

        rf.fit(X_train, y_train)
        xgb.fit(X_train, y_train)

    except Exception as exc:

        print(
            f"Final model training failed for {task_name}: "
            f"{type(exc).__name__}: {exc}"
        )

        return None, None

    # Evaluate only on untouched test students.
    rf_test = rf.predict(X_test)
    xgb_test = xgb.predict(X_test)

    hybrid_test = (
        best_weight * rf_test
        + (1 - best_weight) * xgb_test
    )

    metrics = {

        "Task": task_name,
        "Rows": len(X),
        "Students": groups.nunique(),

        "RF_MAE": mean_absolute_error(
            y_test,
            rf_test
        ),

        "XGBoost_MAE": mean_absolute_error(
            y_test,
            xgb_test
        ),

        "Hybrid_MAE": mean_absolute_error(
            y_test,
            hybrid_test
        ),

        "Hybrid_RMSE": np.sqrt(
            mean_squared_error(
                y_test,
                hybrid_test
            )
        ),

        "Hybrid_R2": (
            r2_score(y_test, hybrid_test)
            if len(y_test) > 1
            else np.nan
        ),

        "RF_Weight": best_weight,
        "XGBoost_Weight": 1 - best_weight

    }

    bundle = {

        "task": task_name,
        "rf_model": rf,
        "xgb_model": xgb,
        "rf_weight": best_weight,
        "xgb_weight": 1 - best_weight,
        "feature_columns": usable,
        "target": target

    }

    joblib.dump(
        bundle,
        model_path,
        compress=1
    )

    # Save test predictions.
    meta_cols = [

        "Masked_ID",
        "Branch",
        "Previous_Semester",
        "Next_Semester",
        "Target_Subject_Code"

    ]

    meta_cols = [
        col for col in meta_cols
        if col in valid_df.columns
    ]

    test_output = valid_df.iloc[test_idx][
        meta_cols
    ].reset_index(drop=True)

    test_output["Task"] = task_name
    test_output["Actual"] = y_test.to_numpy()
    test_output["Predicted_RF"] = rf_test
    test_output["Predicted_XGBoost"] = xgb_test
    test_output["Predicted_Hybrid"] = hybrid_test

    test_prediction_rows.extend(
        test_output.to_dict("records")
    )

    print(
        f"{task_name} completed. "
        f"Hybrid MAE: {metrics['Hybrid_MAE']:.4f}"
    )

    return metrics, bundle


# ============================================================
# 14. PREDICT FROM USER-UPLOADED LEDGERS
# ============================================================


def predict_user_ledgers(
    user_subjects,
    user_sgpi,
    subject_bundle,
    sgpi_bundle,
    target_subjects,
    training_subjects
):
    subject_output = []
    sgpi_output = []

    diagnostics = {
        "Students_Examined": 0,
        "Branch_Mismatch": 0,
        "Missing_Previous_Semester": 0,
        "Missing_Previous_Features": 0,
        "Eligible_For_Subject_Prediction": 0,
        "Subject_Predictions_Generated": 0,
        "SGPI_Predictions_Generated": 0
    }

    if user_subjects.empty:
        print("No user subject records available.")
        return pd.DataFrame(), pd.DataFrame()

    user_subjects, user_sgpi = filter_supported_branches(
        user_subjects.copy(),
        user_sgpi.copy()
    )

    # SGPI lookup
    sgpi_lookup = {}

    if not user_sgpi.empty:
        for row in user_sgpi.itertuples(index=False):
            sgpi_lookup[
                (row.Masked_ID, row.Branch, int(row.Semester))
            ] = float(row.SGPI)

    # Historical subject codes
    trained_subject_codes = {}

    if not training_subjects.empty:
        for branch, group in training_subjects.groupby("Branch"):
            trained_subject_codes[normalize_branch(branch)] = set(
                group["Target_Subject_Code"]
                .astype(str)
                .str.strip()
                .str.upper()
                .unique()
            )

    # Process each student separately
    for (sid, branch), student in user_subjects.groupby(
        ["Masked_ID", "Branch"]
    ):

        diagnostics["Students_Examined"] += 1

        semester_groups = {
            int(sem): group
            for sem, group in student.groupby("Semester")
        }

        if not semester_groups:
            continue

        latest_semester = max(semester_groups)

        # ====================================================
        # SUBJECT PREDICTION
        # ====================================================

        if subject_bundle is not None and not target_subjects.empty:

            branch_targets = target_subjects[
                target_subjects["Branch"].apply(
                    normalize_branch
                ) == normalize_branch(branch)
            ].copy()

            if branch_targets.empty:
                diagnostics["Branch_Mismatch"] += 1

            for target in branch_targets.itertuples(index=False):

                # Explicit target semester takes priority.
                # Blank semester means latest semester + 1.
                if pd.isna(target.Semester):
                    target_semester = latest_semester + 1
                else:
                    target_semester = int(target.Semester)

                if not 1 <= target_semester <= 8:
                    continue

                previous_semester = target_semester - 1

                # Use the semester immediately before the
                # requested target semester, not necessarily
                # the student's latest semester.
                previous = semester_groups.get(previous_semester)

                if previous is None:
                    diagnostics["Missing_Previous_Semester"] += 1
                    continue

                previous_sgpi = sgpi_lookup.get(
                    (sid, branch, previous_semester)
                )

                features = get_previous_features(
                    previous,
                    previous_sgpi
                )

                if features is None:
                    diagnostics["Missing_Previous_Features"] += 1
                    continue

                diagnostics["Eligible_For_Subject_Prediction"] += 1

                code = str(target.Subject_Code).strip().upper()
                maximum = as_number(target.Max_Marks)

                if maximum is None or maximum <= 0:
                    continue

                family = get_family_features(previous, code)
                code_features = get_code_pattern_features(code)

                model_input = {
                    "Branch": branch,
                    "Previous_Semester": previous_semester,
                    "Next_Semester": target_semester,

                    **features,

                    "Target_Max_Marks": maximum,
                    "Target_Subject_Code": code,
                    "Target_Subject_Family": family[
                        "Target_Subject_Family"
                    ],

                    "Target_Subject_Type": subject_type_from_name(
                        target.Subject_Name
                    ),

                    "Target_Code_Prefix": code_features[
                        "Target_Code_Prefix"
                    ],

                    "Target_Code_Digits": code_features[
                        "Target_Code_Digits"
                    ],

                    "Target_Code_Suffix": code_features[
                        "Target_Code_Suffix"
                    ],

                    "Target_Code_Length": code_features[
                        "Target_Code_Length"
                    ],

                    "Target_Subject_Name": str(
                        target.Subject_Name
                    ),

                    "Previous_Family_Mean_Percentage": family[
                        "Previous_Family_Mean_Percentage"
                    ],

                    "Previous_Family_Median_Percentage": family[
                        "Previous_Family_Median_Percentage"
                    ],

                    "Previous_Family_Subject_Count": family[
                        "Previous_Family_Subject_Count"
                    ]
                }

                X = pd.DataFrame([model_input]).reindex(
                    columns=subject_bundle["feature_columns"]
                )

                rf_prediction = float(
                    subject_bundle["rf_model"].predict(X)[0]
                )

                xgb_prediction = float(
                    subject_bundle["xgb_model"].predict(X)[0]
                )

                raw_percentage = (
                    subject_bundle["rf_weight"] * rf_prediction
                    + subject_bundle["xgb_weight"] * xgb_prediction
                )

                percentage = float(
                    np.clip(raw_percentage, 0, 100)
                )

                predicted_marks = percentage * maximum / 100

                known_codes = trained_subject_codes.get(
                    normalize_branch(branch),
                    set()
                )

                seen_code = code in known_codes

                subject_output.append({

                    "Masked_ID": sid,
                    "Branch": branch,

                    "Previous_Semester": previous_semester,
                    "Predicted_Semester": target_semester,

                    "Subject_Code": code,
                    "Subject_Name": target.Subject_Name,

                    "Max_Marks": maximum,
                    "Min_Marks": target.Min_Marks,

                    "Predicted_Percentage": percentage,
                    "Predicted_Marks": predicted_marks,

                    "Predicted_RF_Percentage": rf_prediction,
                    "Predicted_XGBoost_Percentage": xgb_prediction,

                    "Prediction_Status": (
                        "PREDICTED"
                        if seen_code
                        else "PREDICTED_UNSEEN_CODE_LOW_CONFIDENCE"
                    ),

                    "Code_Seen_In_Branch_Training": seen_code,

                    "Confidence_Note": (
                        "Subject code appeared in historical branch training data."
                        if seen_code else
                        "Unseen subject code: estimate uses general academic "
                        "and parsed code-pattern features. Reliability is "
                        "not established for this code."
                    ),

                    "Max_Marks_Status": "MANUALLY_ENTERED"

                })

                diagnostics["Subject_Predictions_Generated"] += 1

        # ====================================================
        # INDEPENDENT SGPI PREDICTION (OPTION A)
        # ====================================================

        if sgpi_bundle is not None:

            previous_sgpi = sgpi_lookup.get(
                (sid, branch, latest_semester)
            )

            if previous_sgpi is not None and latest_semester < 8:

                next_semester = latest_semester + 1

                previous2 = sgpi_lookup.get(
                    (sid, branch, latest_semester - 1)
                )

                sgpi_input = pd.DataFrame([{

                    "Branch": branch,
                    "Previous_Semester": latest_semester,
                    "Next_Semester": next_semester,
                    "Previous_SGPI": previous_sgpi,
                    "Previous2_SGPI": previous2,

                    "SGPI_Trend": (
                        previous_sgpi - previous2
                        if previous2 is not None
                        else np.nan
                    )

                }]).reindex(
                    columns=sgpi_bundle["feature_columns"]
                )

                rf_value = float(
                    sgpi_bundle["rf_model"].predict(sgpi_input)[0]
                )

                xgb_value = float(
                    sgpi_bundle["xgb_model"].predict(sgpi_input)[0]
                )

                prediction = (
                    sgpi_bundle["rf_weight"] * rf_value
                    + sgpi_bundle["xgb_weight"] * xgb_value
                )

                sgpi_output.append({

                    "Masked_ID": sid,
                    "Branch": branch,

                    "Previous_Semester": latest_semester,
                    "Predicted_Semester": next_semester,

                    "Previous_SGPI": previous_sgpi,

                    "Predicted_SGPI": float(
                        np.clip(prediction, 0, 10)
                    ),

                    "Prediction_Method": (
                        "Independent RF + XGBoost hybrid"
                    )

                })

                diagnostics["SGPI_Predictions_Generated"] += 1

    print("\n" + "=" * 60)
    print("USER PREDICTION DIAGNOSTICS")
    print("=" * 60)

    for name, count in diagnostics.items():
        print(f"{name:<42}: {count:,}")

    print("=" * 60)

    if not subject_output:
        print(
            "WARNING: No subject predictions generated. "
            "Check the branch and previous-semester diagnostics."
        )

    return (
        pd.DataFrame(subject_output),
        pd.DataFrame(sgpi_output)
    )

# ============================================================
# 15. DUPLICATE VALIDATION
# ============================================================

def validate_duplicates(
    subject_predictions,
    sgpi_predictions
):

    results = []

    subject_keys = [

        "Masked_ID",
        "Branch",
        "Previous_Semester",
        "Predicted_Semester",
        "Subject_Code",
        "Subject_Name"

    ]

    sgpi_keys = [

        "Masked_ID",
        "Branch",
        "Previous_Semester",
        "Predicted_Semester"

    ]

    for name, df, keys in [

        (
            "Subject Predictions",
            subject_predictions,
            subject_keys
        ),

        (
            "SGPI Predictions",
            sgpi_predictions,
            sgpi_keys
        )

    ]:

        if df.empty:

            duplicate_rows = 0
            duplicate_groups = 0

        else:

            duplicate_mask = df.duplicated(
                subset=keys,
                keep=False
            )

            duplicate_rows = int(
                duplicate_mask.sum()
            )

            duplicate_groups = int(
                df.loc[duplicate_mask]
                .groupby(
                    keys,
                    dropna=False
                )
                .ngroups
            )

        results.append({

            "Dataset": name,
            "Total_Rows": len(df),
            "Duplicate_Rows": duplicate_rows,
            "Duplicate_Groups": duplicate_groups,
            "Status": (
                "PASS"
                if duplicate_groups == 0
                else "CHECK"
            )

        })

    return pd.DataFrame(results)


# ============================================================
# 16. EXCEL EXPORT
# ============================================================

def export_results(
    subjects,
    sgpi,
    subject_training,
    sgpi_training,
    metrics_rows,
    test_predictions,
    user_subjects,
    user_sgpi,
    target_subjects,
    subject_predictions,
    sgpi_predictions,
    duplicate_validation,
    logs,
    user_logs,
    summary,
    diagnostics,
    branch_report
):

    print("\nExporting Excel results...")

    with pd.ExcelWriter(
        OUTPUT_FILE,
        engine="openpyxl"
    ) as writer:

        subjects.to_excel(
            writer,
            sheet_name="Training_Student_Results",
            index=False
        )

        sgpi.to_excel(
            writer,
            sheet_name="Training_SGPI_Results",
            index=False
        )

        subject_training.to_excel(
            writer,
            sheet_name="Subject_Training_Data",
            index=False
        )

        sgpi_training.to_excel(
            writer,
            sheet_name="SGPI_Training_Data",
            index=False
        )

        pd.DataFrame(metrics_rows).to_excel(
            writer,
            sheet_name="Model_Metrics",
            index=False
        )

        pd.DataFrame(test_predictions).to_excel(
            writer,
            sheet_name="Test_Predictions",
            index=False
        )

        user_subjects.to_excel(
            writer,
            sheet_name="User_Student_Results",
            index=False
        )

        user_sgpi.to_excel(
            writer,
            sheet_name="User_SGPI_Results",
            index=False
        )

        target_subjects.to_excel(
            writer,
            sheet_name="Manual_Target_Subjects",
            index=False
        )

        subject_predictions.to_excel(
            writer,
            sheet_name="Next_Sem_Subject_Predictions",
            index=False
        )

        sgpi_predictions.to_excel(
            writer,
            sheet_name="Next_Sem_SGPI_Predictions",
            index=False
        )

        duplicate_validation.to_excel(
            writer,
            sheet_name="Duplicate_Validation",
            index=False
        )

        pd.concat(
            [logs, user_logs],
            ignore_index=True
        ).to_excel(
            writer,
            sheet_name="Extraction_Log",
            index=False
        )

        summary.to_excel(
            writer,
            sheet_name="Data_Summary",
            index=False
        )

        diagnostics.to_excel(
            writer,
            sheet_name="Training_Diagnostics",
            index=False
        )

        branch_report.to_excel(
            writer,
            sheet_name="Branch_Filter_Report",
            index=False
        )


# ============================================================
# 17. MAIN
# ============================================================

def main():

    start = time.time()

    print("\n" + "=" * 65)
    print("ACADEMIC RESULT PREDICTION PIPELINE V6")
    print("=" * 65)

    # Collect manual target subjects before the long extraction/training run.
    target_subjects = collect_target_subjects()

    # --------------------------------------------------------
    # STEP 1: EXTRACT HISTORICAL TRAINING DATA
    # --------------------------------------------------------

    print("\nSTEP 1: Reading historical training ledgers")

    subjects, sgpi, logs = extract_training_files()

    if subjects.empty:
        raise ValueError(
            "No historical subject records were extracted. "
            "Check the ledger format."
        )

    subjects, sgpi = clean_data(
        subjects,
        sgpi
    )

    print(
        f"\nHistorical subject rows before branch filtering: "
        f"{len(subjects):,}"
    )

    print(
        f"Historical SGPI rows before branch filtering: "
        f"{len(sgpi):,}"
    )

    # --------------------------------------------------------
    # STEP 2: EXCLUDE CIVIL BRANCHES
    # --------------------------------------------------------

    print("\nSTEP 2: Filtering unsupported branches")

    all_historical_branches = sorted(
        set(subjects["Branch"].dropna().astype(str))
        | set(sgpi["Branch"].dropna().astype(str))
    )

    excluded_found = [
        branch
        for branch in all_historical_branches
        if is_excluded_branch(branch)
    ]

    print("\nExcluded branches detected:")

    if excluded_found:
        for branch in excluded_found:
            print(f"  - {branch}")
    else:
        print("  No excluded branches detected.")

    subjects, sgpi = filter_supported_branches(
        subjects,
        sgpi
    )

    if subjects.empty:
        raise ValueError(
            "No supported historical subject records remain "
            "after branch filtering."
        )

    print(
        f"\nSupported historical subject rows: {len(subjects):,}"
    )

    print(
        f"Supported historical SGPI rows: {len(sgpi):,}"
    )

    # --------------------------------------------------------
    # STEP 3: BUILD TRAINING DATASETS
    # --------------------------------------------------------

    print("\nSTEP 3: Building training datasets")

    (
        subject_training,
        sgpi_training,
        diagnostics
    ) = build_training_tables(
        subjects,
        sgpi
    )

    print(
        f"\nSubject training rows: {len(subject_training):,}"
    )

    print(
        f"SGPI training rows: {len(sgpi_training):,}"
    )

    # --------------------------------------------------------
    # STEP 4: TRAIN HYBRID MODELS
    # --------------------------------------------------------

    print("\nSTEP 4: Training hybrid models")

    metrics_rows = []
    test_predictions = []

    subject_model_path = (
        MODEL_DIR / "subject_hybrid_model.joblib"
    )

    sgpi_model_path = (
        MODEL_DIR / "sgpi_hybrid_model.joblib"
    )

    subject_metrics, subject_bundle = train_hybrid(

        subject_training,
        "Target_Percentage",
        "Subject-wise Marks Percentage",
        subject_model_path,
        test_predictions

    )

    sgpi_metrics, sgpi_bundle = train_hybrid(

        sgpi_training,
        "Target_SGPI",
        "Overall SGPI",
        sgpi_model_path,
        test_predictions

    )

    if subject_metrics is not None:
        metrics_rows.append(subject_metrics)

    if sgpi_metrics is not None:
        metrics_rows.append(sgpi_metrics)

    if subject_bundle is None and sgpi_bundle is None:
        raise ValueError(
            "Neither model could be trained. "
            "Check the training data and diagnostics."
        )

    # --------------------------------------------------------
    # STEP 5: COLLECT TARGET SUBJECTS MANUALLY
    # --------------------------------------------------------

    print(f"Manual target subjects ready: {len(target_subjects)}")

    # --------------------------------------------------------
    # STEP 6: READ USER-UPLOADED EXCEL FILES
    # --------------------------------------------------------

    print("\nSTEP 6: Reading user-uploaded Excel ledgers")

    (
        user_subjects,
        user_sgpi,
        user_logs
    ) = extract_user_uploads()

    if not user_subjects.empty:

        user_subjects, user_sgpi = clean_data(
            user_subjects,
            user_sgpi
        )

        print(
            f"User subject rows before branch filtering: "
            f"{len(user_subjects):,}"
        )

        print(
            f"User SGPI rows before branch filtering: "
            f"{len(user_sgpi):,}"
        )

        user_subjects, user_sgpi = filter_supported_branches(
            user_subjects,
            user_sgpi
        )

    else:

        print(
            "\nNo user-uploaded ledgers found. "
            "The training results will still be exported."
        )

        user_subjects = pd.DataFrame()
        user_sgpi = pd.DataFrame()

    # --------------------------------------------------------
    # STEP 7: GENERATE USER PREDICTIONS
    # --------------------------------------------------------

    print("\nSTEP 7: Generating user predictions")

    if not user_subjects.empty:

        (
            subject_predictions,
            sgpi_predictions
        ) = predict_user_ledgers(

            user_subjects,
            user_sgpi,
            subject_bundle,
            sgpi_bundle,
            target_subjects,
            subject_training

        )

    else:

        subject_predictions = pd.DataFrame()
        sgpi_predictions = pd.DataFrame()

    print(
        f"Subject prediction rows: {len(subject_predictions):,}"
    )

    print(
        f"SGPI prediction rows: {len(sgpi_predictions):,}"
    )

    # --------------------------------------------------------
    # STEP 8: DUPLICATE VALIDATION
    # --------------------------------------------------------

    print("\nSTEP 8: Duplicate validation")

    duplicate_validation = validate_duplicates(
        subject_predictions,
        sgpi_predictions
    )

    print(
        duplicate_validation.to_string(index=False)
    )

    # --------------------------------------------------------
    # STEP 9: BRANCH REPORT
    # --------------------------------------------------------

    branch_report = build_branch_report(
        subjects,
        sgpi,
        user_subjects
    )

    # --------------------------------------------------------
    # STEP 10: DATA SUMMARY
    # --------------------------------------------------------

    summary_rows = [

        {
            "Metric": "Historical Subject Records",
            "Value": len(subjects)
        },

        {
            "Metric": "Historical SGPI Records",
            "Value": len(sgpi)
        },

        {
            "Metric": "Subject Training Rows",
            "Value": len(subject_training)
        },

        {
            "Metric": "SGPI Training Rows",
            "Value": len(sgpi_training)
        },

        {
            "Metric": "User Ledger Subject Records",
            "Value": len(user_subjects)
        },

        {
            "Metric": "User Ledger SGPI Records",
            "Value": len(user_sgpi)
        },

        {
            "Metric": "Manually Entered Target Subjects",
            "Value": len(target_subjects)
        },

        {
            "Metric": "Subject Predictions",
            "Value": len(subject_predictions)
        },

        {
            "Metric": "SGPI Predictions",
            "Value": len(sgpi_predictions)
        },

        {
            "Metric": "Excluded Branches",
            "Value": ", ".join(excluded_found)
        },

        {
            "Metric": "Masking Method",
            "Value": "HMAC-SHA256"
        },

        {
            "Metric": "Subject Prediction Method",
            "Value": "Random Forest + XGBoost hybrid"
        },

        {
            "Metric": "Maximum Marks Source",
            "Value": "Manually entered at runtime; maximum marks required"
        },

        {
            "Metric": "User Uploads Used For Training",
            "Value": "NO"
        },

        {
            "Metric": "Output Version",
            "Value": "V6"
        }

    ]

    summary = pd.DataFrame(summary_rows)

    # --------------------------------------------------------
    # STEP 11: EXPORT EXCEL WORKBOOK
    # --------------------------------------------------------

    print("\nSTEP 11: Exporting Excel results")

    export_results(

        subjects,
        sgpi,
        subject_training,
        sgpi_training,
        metrics_rows,
        test_predictions,
        user_subjects,
        user_sgpi,
        target_subjects,
        subject_predictions,
        sgpi_predictions,
        duplicate_validation,
        logs,
        user_logs,
        summary,
        diagnostics,
        branch_report

    )

    # --------------------------------------------------------
    # STEP 12: FINAL REPORT
    # --------------------------------------------------------

    print("\n" + "=" * 65)
    print("PIPELINE V6 COMPLETED")
    print("=" * 65)

    print(f"\nOutput workbook:\n{OUTPUT_FILE}")

    print(f"\nSaved models:\n{MODEL_DIR}")

    print(
        f"\nHistorical subject records: {len(subjects):,}"
    )

    print(
        f"Historical SGPI records: {len(sgpi):,}"
    )

    print(
        f"Subject training rows: {len(subject_training):,}"
    )

    print(
        f"SGPI training rows: {len(sgpi_training):,}"
    )

    print(
        f"Subject predictions: {len(subject_predictions):,}"
    )

    print(
        f"SGPI predictions: {len(sgpi_predictions):,}"
    )

    print(
        f"\nExecution time: "
        f"{(time.time() - start) / 60:.2f} minutes"
    )

    print(
        "\nKeep student_mask.key safe and unchanged."
    )

    print(
        "\nNOTE: Unseen subject codes are estimated using parsed code-pattern "
        "and general academic features, but are explicitly flagged LOW_CONFIDENCE. "
        "This does not establish validated accuracy for unseen codes."
    )


# ============================================================
# 18. RUN
# ============================================================

if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:
        print("\nPipeline interrupted.")

    except Exception as exc:

        print("\nPIPELINE ERROR:")
        print(f"{type(exc).__name__}: {exc}")

        raise
