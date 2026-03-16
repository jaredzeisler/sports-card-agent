"""Batch PSA cert number lookup script."""

import sys
import time
import json
import csv
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.api.psa import PSAClient


CERT_NUMBERS = [
    "VIH00000047165", "VIH00000046313", "00017037275", "63759922", "58219979",
    "86431191", "0010274998", "0009492065", "0012492466", "0010795789",
    "135695120", "26438933", "24605312", "0009976052", "141817341",
    "63592622", "136081904", "66746356", "0015014867", "136499426",
    "100986599", "106425388", "87509842", "116464626", "0011230094",
    "63137038", "0007334310", "85222231", "120648327", "97577827",
    "23084298", "121750653", "72383626", "98905200", "63754311",
    "66494565", "114372462", "0011435819", "95693753", "96012155",
    "94483258", "120943345", "65147563", "85222228", "0012820696",
    "126393754", "98904159", "135924481", "136944511", "120703580",
    "126949500", "0013094942", "66441936", "136780260", "97351741",
    "64868004", "114930602", "133580570", "131642791", "136323233",
    "68623196", "0001113499", "132153763", "0012769095", "99978259",
    "0016411170", "76397134", "0014829087", "141440363", "136947718",
    "125626607", "128527494", "111400579", "0011326506", "0019159879",
    "70525298", "79400339", "0015990317", "03185302", "0016368393",
    "0015430378", "91028250", "0018287138", "95106789", "119038174",
    "3533486", "87311665", "67099241", "111029076", "134665754",
    "0007639584", "102621215", "142786505", "86381234", "113981684",
    "120061744", "63962554", "85613697", "96536274", "0013304131",
    "100826804", "132140621", "108908533", "126462153",
    "VIH00000045347", "VIH00000045098", "VIH00000045096", "VIH00000042096",
    "VIH00000045284", "VIH00000043571", "VIH00000045873", "VIH00000042722",
    "VIH00000043150", "VIH00000044392", "VIH00000042867", "VIH00000043176",
    "VIH00000042776", "VIH00000043616", "VIH00000043620", "VIH00000042213",
    "VIH00000044315", "VIH00000042183", "VIH00000043336", "VIH00000042829",
    "VIH00000042418", "VIH00000043134", "VIH00000042250", "VIH00000044584",
    "VIH00000044967", "VIH00000045329", "VIH00000043635", "VIH00000042182",
    "VIH00000043354", "VIH00000042298", "VIH00000043570", "VIH00000043569",
    "VIH00000042101", "VIH00000042316", "VIH00000042239", "VIH00000042604",
    "VIH00000043083", "VIH00000044288", "VIH00000042826", "VIH00000044585",
    "VIH00000042222", "VIH00000045008", "VIH00000042215", "VIH00000043062",
]


def main():
    client = PSAClient()
    results = []
    errors = []

    total = len(CERT_NUMBERS)
    print(f"Looking up {total} cert numbers via PSA API...\n")

    for i, cert in enumerate(CERT_NUMBERS, 1):
        print(f"[{i}/{total}] Looking up {cert}...", end=" ", flush=True)
        try:
            result = client.verify_cert(cert)
            if result:
                results.append(result)
                grade = result.get("grade_description", "N/A")
                print(f"OK - {result['subject'][:50]} | {grade}")
            else:
                errors.append({"cert": cert, "error": "Not found"})
                print("NOT FOUND")
        except Exception as e:
            errors.append({"cert": cert, "error": str(e)})
            print(f"ERROR: {e}")

        # Rate limit: small delay between requests
        if i < total:
            time.sleep(0.3)

    # Save results to JSON
    output_dir = Path(__file__).resolve().parent.parent / "data"
    output_dir.mkdir(exist_ok=True)

    json_path = output_dir / "cert_lookup_results.json"
    with open(json_path, "w") as f:
        json.dump({"results": results, "errors": errors}, f, indent=2)

    # Save results to CSV
    csv_path = output_dir / "cert_lookup_results.csv"
    if results:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)

    # Print summary
    print(f"\n{'='*80}")
    print(f"SUMMARY: {len(results)} found, {len(errors)} errors/not found")
    print(f"Results saved to: {json_path}")
    print(f"CSV saved to: {csv_path}")

    if errors:
        print(f"\nFailed lookups:")
        for e in errors:
            print(f"  {e['cert']}: {e['error']}")

    # Print table
    print(f"\n{'='*80}")
    print(f"{'Cert':<20} {'Player/Subject':<40} {'Grade':<15} {'Year':<6} {'Brand':<20}")
    print(f"{'-'*20} {'-'*40} {'-'*15} {'-'*6} {'-'*20}")
    for r in results:
        cert = r.get("cert_number", "")[:20]
        subject = r.get("subject", "")[:40]
        grade = r.get("grade_description", "")[:15]
        year = str(r.get("year", ""))[:6]
        brand = r.get("brand", "")[:20]
        print(f"{cert:<20} {subject:<40} {grade:<15} {year:<6} {brand:<20}")


if __name__ == "__main__":
    main()
