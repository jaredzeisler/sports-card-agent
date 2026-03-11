"""PSA API client for certificate verification.

Supports two auth modes:
1. Direct API token (PSA_API_KEY env var) — if you already have a bearer token
2. OAuth login (PSA_USERNAME + PSA_PASSWORD) — exchanges credentials for a token

Free tier: 100 API calls/day.
"""

import re
import httpx

from config.settings import get_settings

BASE_URL = "https://api.psacard.com/publicapi"
TOKEN_URL = f"{BASE_URL}/account/GetToken"
CERT_URL = f"{BASE_URL}/cert/GetByCertNumber"


class PSAClient:
    """Client for the PSA Cert Verification API."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self._token: str | None = None

    def _get_token(self) -> str:
        """Get bearer token, using cached value if available."""
        if self._token:
            return self._token

        # Option 1: direct API key / token
        if self.settings.psa_api_key:
            self._token = self.settings.psa_api_key
            return self._token

        # Option 2: OAuth password grant
        if self.settings.psa_username and self.settings.psa_password:
            resp = httpx.post(
                TOKEN_URL,
                json={
                    "userNameOrEmail": self.settings.psa_username,
                    "password": self.settings.psa_password,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            self._token = data.get("token") or data.get("access_token")
            if not self._token:
                raise ValueError(f"PSA auth returned no token: {data}")
            return self._token

        raise ValueError(
            "No PSA credentials configured. Set PSA_API_KEY or PSA_USERNAME + PSA_PASSWORD in .env"
        )

    def _headers(self) -> dict:
        return {
            "Authorization": f"bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    def verify_cert(self, cert_number: str) -> dict | None:
        """Verify a PSA certificate number and return card details.

        Returns dict with: subject, grade, card_number, year, brand, variety,
                          label_type, reverse_cert_number, or None if not found.
        """
        # Clean cert number — strip spaces, leading zeros
        cert_number = str(cert_number).strip().lstrip("0") or "0"

        try:
            resp = httpx.get(
                f"{CERT_URL}/{cert_number}",
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            if not data or data.get("PSACert") is None:
                return None

            cert = data["PSACert"]
            return {
                "cert_number": cert.get("CertNumber", cert_number),
                "subject": cert.get("Subject", ""),
                "grade": self._parse_grade(cert.get("CardGrade", "")),
                "grade_description": cert.get("CardGrade", ""),
                "card_number": cert.get("CardNumber", ""),
                "year": cert.get("Year", ""),
                "brand": cert.get("Brand", ""),
                "variety": cert.get("Variety", ""),
                "label_type": cert.get("LabelType", ""),
                "category": cert.get("Category", ""),
                "reverse_cert": cert.get("ReverseBarcodeNumber", ""),
                "is_authentic": cert.get("IsPSADNACert", False),
            }
        except httpx.HTTPError as e:
            print(f"PSA API error for cert {cert_number}: {e}")
            return None

    def _parse_grade(self, grade_str: str) -> float | None:
        """Parse PSA grade string to numeric value."""
        if not grade_str:
            return None
        # PSA grades: "GEM-MT 10", "MINT 9", "NM-MT 8", etc.
        parts = grade_str.strip().split()
        if parts:
            try:
                return float(parts[-1])
            except ValueError:
                return None
        return None

    def verify_and_match(self, cert_number: str, expected_player: str | None = None) -> dict:
        """Verify cert and optionally check if it matches expected player.

        Returns dict with verified data and a 'match' boolean.
        """
        result = self.verify_cert(cert_number)
        if result is None:
            return {"verified": False, "match": False, "error": "Cert not found"}

        match = True
        if expected_player:
            subject_lower = result.get("subject", "").lower()
            match = expected_player.lower() in subject_lower

        return {
            "verified": True,
            "match": match,
            **result,
        }

    def verify_listing(self, listing: dict) -> dict:
        """Verify a scanned listing by extracting cert number from the title/description.

        Looks for PSA cert numbers in the listing title (common patterns:
        "PSA 10 #12345678", "cert 12345678", 8-digit numbers near "PSA").

        Returns the listing dict with added 'psa_verified' field.
        """
        title = listing.get("title", "")
        cert_num = extract_cert_number(title)

        if not cert_num:
            listing["psa_verified"] = None  # no cert number found
            return listing

        result = self.verify_and_match(
            cert_number=cert_num,
            expected_player=listing.get("player"),
        )

        listing["psa_verified"] = result
        listing["psa_cert_number"] = cert_num

        # Flag mismatches
        if result.get("verified"):
            expected_grade = listing.get("grade", "")
            psa_grade = result.get("grade")
            if psa_grade and expected_grade:
                grade_num = re.search(r"\d+", expected_grade)
                if grade_num and float(grade_num.group()) != psa_grade:
                    listing["psa_grade_mismatch"] = True

        return listing


def extract_cert_number(text: str) -> str | None:
    """Extract PSA cert number from text.

    Looks for 7-10 digit numbers near PSA-related keywords.
    Common patterns:
    - "PSA 10 #12345678"
    - "PSA 10 Cert# 12345678"
    - "PSA 10 (cert 12345678)"
    - Just a standalone 8-digit number when PSA is mentioned
    """
    t = text.lower()
    if "psa" not in t:
        return None

    # Pattern 1: cert/certification followed by number
    m = re.search(r"cert(?:ification)?[#:\s]*(\d{7,10})", t)
    if m:
        return m.group(1)

    # Pattern 2: # followed by 8+ digit number (not card numbers which are shorter)
    m = re.search(r"#(\d{8,10})", t)
    if m:
        return m.group(1)

    # Pattern 3: standalone 8-10 digit number (likely cert number)
    numbers = re.findall(r"\b(\d{8,10})\b", t)
    if len(numbers) == 1:
        return numbers[0]

    return None
