import math

import numpy as np
import pandas as pd

from model_integration.predict import predict_from_excel


def make_json_safe(value):
    """
    Recursively convert pandas/numpy values into
    standard Python JSON-compatible values.
    """

    if isinstance(value, dict):
        return {
            str(key): make_json_safe(val)
            for key, val in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [
            make_json_safe(item)
            for item in value
        ]

    if isinstance(value, np.ndarray):
        return [
            make_json_safe(item)
            for item in value.tolist()
        ]

    if isinstance(value, np.generic):
        value = value.item()

        if isinstance(value, float) and not math.isfinite(value):
            return None

        return value

    if isinstance(value, float) and not math.isfinite(value):
        return None

    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    if isinstance(value, pd.DataFrame):
        return make_json_safe(
            value.to_dict(orient="records")
        )

    return value


def generate_mark_predictions(
    workbook_bytes: bytes,
    workbook_name: str,
    target_subjects: list[dict],
) -> dict:
    """
    Generate academic mark and SGPI predictions using
    the ML team's prediction pipeline.

    Args:
        workbook_bytes: Uploaded Excel file as bytes.
        workbook_name: Original Excel filename.
        target_subjects: List of target subject dictionaries.

    Returns:
        JSON-compatible dictionary containing academic year,
        extraction logs, subject predictions, SGPI predictions,
        and duplicate validation.
    """

    if not workbook_bytes:
        raise ValueError("Uploaded Excel file is empty.")

    if not workbook_name:
        raise ValueError("Workbook filename is required.")

    if not target_subjects:
        raise ValueError("At least one target subject is required.")

    result = predict_from_excel(
        workbook_bytes=workbook_bytes,
        workbook_name=workbook_name,
        target_subjects=target_subjects,
    )

    # Convert DataFrames to records.
    if hasattr(result.get("subject_predictions"), "to_dict"):
        result["subject_predictions"] = (
            result["subject_predictions"]
            .to_dict(orient="records")
        )

    if hasattr(result.get("sgpi_predictions"), "to_dict"):
        result["sgpi_predictions"] = (
            result["sgpi_predictions"]
            .to_dict(orient="records")
        )

    # Convert all NumPy/Pandas values recursively
    # into standard JSON-compatible Python values.
    result = make_json_safe(result)

    return result