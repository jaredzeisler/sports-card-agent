"""Card grading assessment using Claude vision to estimate PSA/BGS grades from images."""

import base64
import re
from pathlib import Path

from config.settings import get_settings


# Grading criteria weights for PSA-style assessment
GRADING_CRITERIA = {
    "centering": {
        "weight": 0.25,
        "description": "How well-centered the image is within the card borders",
    },
    "corners": {
        "weight": 0.25,
        "description": "Sharpness and condition of all four corners",
    },
    "edges": {
        "weight": 0.25,
        "description": "Smoothness and condition of card edges, chips, or dings",
    },
    "surface": {
        "weight": 0.25,
        "description": "Surface condition including scratches, print defects, staining",
    },
}

# PSA grade scale
PSA_SCALE = {
    10: "GEM-MT (Gem Mint)",
    9: "MINT",
    8: "NM-MT (Near Mint-Mint)",
    7: "NM (Near Mint)",
    6: "EX-MT (Excellent-Mint)",
    5: "EX (Excellent)",
    4: "VG-EX (Very Good-Excellent)",
    3: "VG (Very Good)",
    2: "GOOD",
    1: "PR (Poor)",
}

# BGS sub-grade scale
BGS_SCALE = {
    10: "Pristine",
    9.5: "Gem Mint",
    9: "Mint",
    8.5: "NM-MT+",
    8: "NM-MT",
    7.5: "NM+",
    7: "NM",
    6.5: "EX-MT+",
    6: "EX-MT",
}


def _encode_image(image_path: str) -> tuple[str, str]:
    """Read and base64-encode an image file. Returns (base64_data, media_type)."""
    path = Path(image_path)
    suffix = path.suffix.lower()
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_types.get(suffix, "image/jpeg")
    data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    return data, media_type


def assess_grade(image_path: str, settings=None) -> dict | None:
    """Assess the likely PSA/BGS grade of a card from an image.

    Uses Claude's vision capabilities to analyze centering, corners,
    edges, and surface condition.

    Args:
        image_path: Path to the card image file.
        settings: Optional settings override.

    Returns:
        Dict with estimated grades and analysis, or None if unavailable.
    """
    settings = settings or get_settings()
    if not settings.anthropic_api_key:
        return None

    try:
        import anthropic

        image_data, media_type = _encode_image(image_path)
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        prompt = (
            "You are an expert sports card grader with decades of experience at PSA and BGS. "
            "Analyze this card image and provide a grading assessment.\n\n"
            "Evaluate these four criteria on a scale of 1-10:\n"
            "1. **Centering** — How well-centered is the image within the borders? "
            "Check left/right and top/bottom ratios.\n"
            "2. **Corners** — Are the corners sharp and crisp, or do they show "
            "wear, rounding, or fraying?\n"
            "3. **Edges** — Are the edges clean and smooth, or are there chips, "
            "dings, or rough spots?\n"
            "4. **Surface** — Is the surface free of scratches, print defects, "
            "staining, or other flaws?\n\n"
            "Also identify the card: player name, year, brand, set, variation/parallel, "
            "and any serial numbering visible.\n\n"
            "Respond in EXACTLY this format (no extra text):\n"
            "PLAYER: <player name>\n"
            "YEAR: <year or UNKNOWN>\n"
            "BRAND: <brand>\n"
            "SET: <set name>\n"
            "VARIATION: <variation/parallel or NONE>\n"
            "SERIAL: <serial number like 04/25 or NONE>\n"
            "CENTERING: <1-10>\n"
            "CORNERS: <1-10>\n"
            "EDGES: <1-10>\n"
            "SURFACE: <1-10>\n"
            "PSA_ESTIMATE: <estimated PSA grade 1-10>\n"
            "BGS_ESTIMATE: <estimated BGS grade like 9.5>\n"
            "NOTES: <brief grading notes, one line>"
        )

        response = client.messages.create(
            model="claude-sonnet-4-5-20250514",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }],
        )

        text = response.content[0].text.strip()
        return _parse_grading_response(text)

    except Exception as e:
        return {"error": str(e)}


def _parse_grading_response(text: str) -> dict:
    """Parse the structured grading response from Claude."""
    result = {
        "card": {},
        "sub_grades": {},
        "psa_estimate": None,
        "bgs_estimate": None,
        "psa_label": None,
        "bgs_label": None,
        "notes": "",
        "raw_response": text,
    }

    lines = text.strip().split("\n")
    for line in lines:
        line = line.strip()
        if not line or ":" not in line:
            continue

        key, _, value = line.partition(":")
        key = key.strip().upper()
        value = value.strip()

        if key == "PLAYER":
            result["card"]["player"] = value
        elif key == "YEAR":
            if value != "UNKNOWN":
                try:
                    result["card"]["year"] = int(value)
                except ValueError:
                    result["card"]["year_raw"] = value
        elif key == "BRAND":
            result["card"]["brand"] = value
        elif key == "SET":
            result["card"]["set_name"] = value
        elif key == "VARIATION":
            if value.upper() != "NONE":
                result["card"]["variation"] = value
        elif key == "SERIAL":
            if value.upper() != "NONE":
                result["card"]["serial"] = value
        elif key == "CENTERING":
            result["sub_grades"]["centering"] = _parse_number(value)
        elif key == "CORNERS":
            result["sub_grades"]["corners"] = _parse_number(value)
        elif key == "EDGES":
            result["sub_grades"]["edges"] = _parse_number(value)
        elif key == "SURFACE":
            result["sub_grades"]["surface"] = _parse_number(value)
        elif key == "PSA_ESTIMATE":
            grade = _parse_number(value)
            result["psa_estimate"] = grade
            if grade is not None:
                int_grade = int(round(grade))
                result["psa_label"] = PSA_SCALE.get(int_grade, f"Grade {int_grade}")
        elif key == "BGS_ESTIMATE":
            grade = _parse_number(value)
            result["bgs_estimate"] = grade
            if grade is not None:
                # Find closest BGS label
                closest = min(BGS_SCALE.keys(), key=lambda k: abs(k - grade))
                result["bgs_label"] = BGS_SCALE[closest]
        elif key == "NOTES":
            result["notes"] = value

    return result


def _parse_number(value: str) -> float | None:
    """Extract a numeric value from a string."""
    match = re.search(r"(\d+\.?\d*)", value)
    if match:
        return float(match.group(1))
    return None
