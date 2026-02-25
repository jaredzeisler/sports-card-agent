"""PSA API client for certificate verification."""

import httpx

from config.settings import get_settings

BASE_URL = "https://api.psacard.com/publicapi/cert/GetByCertNumber"


class PSAClient:
    """Client for the PSA Cert Verification API."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.api_key = self.settings.psa_api_key

    def _headers(self) -> dict:
        return {
            "Authorization": f"bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def verify_cert(self, cert_number: str) -> dict | None:
        """Verify a PSA certificate number and return card details.

        Returns dict with: subject, grade, card_number, year, brand, variety,
                          label_type, reverse_cert_number, or None if not found.
        """
        try:
            resp = httpx.get(
                f"{BASE_URL}/{cert_number}",
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
        except httpx.HTTPError:
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
