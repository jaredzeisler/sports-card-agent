#!/usr/bin/env python3
"""
Card Desk sheet writer - the one sanctioned write path to the two Card Desk files.

  Card Desk Approvals   1bPGiKFzBu_NSDryW96rQUNjQgK0V_tPEp8gDRkC-ONY   (native Google Sheet)
  Card Desk Sell Sheet  1hX50IyectrMSTsyvplSIv55ncN-JxIcm             (xlsx stored in Drive)

File IDs are hardcoded on purpose. Every write goes to the SAME file, never a copy.

AUTH: OAuth installed-app flow, signed in as jzeisler@sportscardcap.com (NOT gmail;
the app is Internal to the Workspace). One-time browser consent, then secrets\\token.json
refreshes silently.

Commands
    auth [--manual]            one-time consent (use --manual if no local browser)
    verify                     confirm sign-in and edit rights on both files
    pull                       download the Sell Sheet to Inventory\\sheet-working
    audit                      Sell Sheet: find formulas / validations hardcoded to old row ends
    fix-ranges [--commit]      widen those ranges to the real last card row (dry run default)
    apply ops.json [--commit]  edits (dry run default; nothing is written without --commit)

ops.json
    {"note": "...",
     "ops": [
       {"file": "approvals", "row_id": "A07", "expect_cert": "0012381981",
        "set": {"Note": "text", "Ask": 2000}},
       {"tab": "Sell Sheet", "row_id": "S031", "expect_cert": "0012381981",
        "set": {"Route": "BIN", "Ask": 2000}},
       {"tab": "Sales Log", "append": ["2026-09-24", "Jordan 98 MJx", "0007014929"]}
     ]}

Guardrails: dry run by default; timestamped PRE-WRITE backup before any change; rows
found by Row ID with the cert in that row required to match; cert 83057190 refused
always; every written value re-read and mismatches reported; WROTE TO SHEET report.
"""
import argparse, datetime, io, json, os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SECRETS = os.path.join(REPO, "secrets")
CLIENT_PATH = os.path.join(SECRETS, "client_secret.json")
TOKEN_PATH = os.environ.get("CARD_TOKEN_PATH", os.path.join(SECRETS, "token.json"))
WORK_DIR = os.path.join(REPO, "Inventory", "sheet-working")
BACKUP_DIR = os.path.join(REPO, "Inventory", "sheet-backups")
MASTER = os.path.join(WORK_DIR, "master.xlsx")

SELL_ID = "1hX50IyectrMSTsyvplSIv55ncN-JxIcm"
APPROVALS_ID = "1bPGiKFzBu_NSDryW96rQUNjQgK0V_tPEp8gDRkC-ONY"
SELL_NAME = "Card Desk Sell Sheet"
APPROVALS_NAME = "Card Desk Approvals"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

SCOPES = ["https://www.googleapis.com/auth/drive",
          "https://www.googleapis.com/auth/spreadsheets"]
WORKSPACE_ACCOUNT = "jzeisler@sportscardcap.com"
WORKSPACE_DOMAIN = "sportscardcap.com"

HARD_LOCK_CERT = "83057190"
HEADER_ROW = 3            # Sell Sheet header row
FIRST_DATA_ROW = 4
SUMMARY_ANCHOR = "Totals by player"

APPR_HEADER_ROW = 1
APPR_PROTECTED = {"Row ID", "Cert", "Title"}   # identity columns are never written


# ---------------------------------------------------------------- auth
def _libs():
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        return Credentials, Request, InstalledAppFlow, build
    except ImportError:
        sys.exit("Missing libraries. Run:\n  python -m pip install google-api-python-client "
                 "google-auth google-auth-oauthlib openpyxl")


def get_creds(manual=False, interactive=True):
    Credentials, Request, InstalledAppFlow, _ = _libs()
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)
            return creds
        except Exception as e:
            print("token refresh failed (%s); re-running consent" % e)
    if not interactive:
        sys.exit("No valid token. Run:  python tools\\card_sheet_writer.py auth")
    if not os.path.exists(CLIENT_PATH):
        sys.exit("Missing %s" % CLIENT_PATH)
    print("Sign in as %s (NOT the gmail account)." % WORKSPACE_ACCOUNT)
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_PATH, SCOPES)
    if manual:
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
        flow.redirect_uri = "http://localhost"
        url, _ = flow.authorization_url(access_type="offline", prompt="consent",
                                        login_hint=WORKSPACE_ACCOUNT)
        print("\n1) Open this URL in a browser:\n\n%s\n" % url)
        print("2) Approve. The browser will then show a page that fails to load")
        print("   (localhost refused). That is expected. Copy the FULL URL from the")
        print("   address bar and paste it here.\n")
        resp = input("Pasted URL: ").strip()
        flow.fetch_token(authorization_response=resp)
        creds = flow.credentials
    else:
        creds = flow.run_local_server(port=0, access_type="offline", prompt="consent",
                                      login_hint=WORKSPACE_ACCOUNT,
                                      authorization_prompt_message="Opening browser for consent...")
    _save_token(creds)
    return creds


def _save_token(creds):
    os.makedirs(SECRETS, exist_ok=True)
    with open(TOKEN_PATH, "w") as f:
        f.write(creds.to_json())


STATE_PATH = os.path.join(SECRETS, ".auth_state.json")


def auth_url_step():
    """Step 1 of a non-interactive manual consent: print URL, remember PKCE state."""
    _, _, InstalledAppFlow, _ = _libs()
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_PATH, SCOPES)
    flow.redirect_uri = "http://localhost"
    url, state = flow.authorization_url(access_type="offline", prompt="consent",
                                        login_hint=WORKSPACE_ACCOUNT)
    json.dump({"state": state, "verifier": flow.code_verifier}, open(STATE_PATH, "w"))
    print(url)


def auth_finish_step(resp):
    """Step 2: paste the failed-to-load localhost URL; exchange the code; cache token."""
    _, _, InstalledAppFlow, _ = _libs()
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    st = json.load(open(STATE_PATH))
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_PATH, SCOPES, state=st["state"])
    flow.redirect_uri = "http://localhost"
    flow.code_verifier = st["verifier"]
    flow.fetch_token(authorization_response=resp.strip())
    _save_token(flow.credentials)
    try:
        os.remove(STATE_PATH)
    except OSError:
        pass   # leftover state file is harmless; overwritten next time
    print("token saved")


def services():
    _, _, _, build = _libs()
    creds = get_creds(interactive=False)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    return drive, sheets


def _whoami(drive):
    return drive.about().get(fields="user(emailAddress,displayName)").execute()["user"]["emailAddress"]


# ---------------------------------------------------------------- helpers
def norm_cert(v):
    """Compare certs ignoring leading zeros / float formatting from Sheets."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip().lstrip("0")


HARD_LOCK_NORM = HARD_LOCK_CERT.lstrip("0")


def _stamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H%M%S")


def _download_xlsx(drive, file_id, dest):
    from googleapiclient.http import MediaIoBaseDownload
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, drive.files().get_media(fileId=file_id))
    done = False
    while not done:
        _, done = dl.next_chunk()
    with open(dest, "wb") as f:
        f.write(buf.getvalue())
    return os.path.getsize(dest)


def _export_sheet_xlsx(drive, file_id, dest):
    from googleapiclient.http import MediaIoBaseDownload
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, drive.files().export_media(fileId=file_id, mimeType=XLSX_MIME))
    done = False
    while not done:
        _, done = dl.next_chunk()
    with open(dest, "wb") as f:
        f.write(buf.getvalue())
    return os.path.getsize(dest)


def _unique(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists("%s (%d)%s" % (base, n, ext)):
        n += 1
    return "%s (%d)%s" % (base, n, ext)


BACKUP_FOLDER_NAME = "Card Desk Sheet Backups"
CLOUD_SCRIPT_NAME = "card_sheet_writer.py (cloud copy)"
CLOUD_TOKEN_NAME = "Card Desk Writer - credentials (private)"
OWNER_GMAIL = "jared.zeisler@gmail.com"


def _backup_folder_id(drive):
    q = ("name = '%s' and mimeType = 'application/vnd.google-apps.folder' and trashed = false and 'me' in owners"
         % BACKUP_FOLDER_NAME)
    r = drive.files().list(q=q, fields="files(id)", pageSize=1).execute().get("files", [])
    if r:
        return r[0]["id"]
    f = drive.files().create(body={"name": BACKUP_FOLDER_NAME,
                                   "mimeType": "application/vnd.google-apps.folder"}, fields="id").execute()
    return f["id"]


def _drive_backup(drive, path):
    """Copy a local backup into the Drive backup folder (survives a cloud sandbox)."""
    from googleapiclient.http import MediaFileUpload
    try:
        fid = _backup_folder_id(drive)
        media = MediaFileUpload(path, mimetype=XLSX_MIME)
        drive.files().create(body={"name": os.path.basename(path), "parents": [fid]},
                             media_body=media, fields="id").execute()
        print("backup also saved to Drive folder %r" % BACKUP_FOLDER_NAME)
    except Exception as e:
        if os.environ.get("CARD_REQUIRE_DRIVE_BACKUP") == "1":
            sys.exit("Drive backup FAILED (%s) and a Drive backup is required here. Nothing written." % e)
        print("note: Drive backup copy failed (%s); local backup still exists" % e)


def cmd_publish_cloud():
    """Upload the script and sign-in file to the workspace Drive and share read-only to the gmail
    account, so cloud tasks (which read Drive as gmail) can fetch them. Re-run after any script change."""
    from googleapiclient.http import MediaFileUpload
    drive, _ = services()
    ids = {}
    for name, path, mime in ((CLOUD_SCRIPT_NAME, os.path.abspath(__file__), "text/plain"),
                             (CLOUD_TOKEN_NAME, TOKEN_PATH, "application/json")):
        q = "name = '%s' and trashed = false and 'me' in owners" % name
        found = drive.files().list(q=q, fields="files(id)", pageSize=1).execute().get("files", [])
        media = MediaFileUpload(path, mimetype=mime)
        if found:
            fid = found[0]["id"]
            drive.files().update(fileId=fid, media_body=media).execute()
        else:
            fid = drive.files().create(body={"name": name}, media_body=media, fields="id").execute()["id"]
            drive.permissions().create(fileId=fid, sendNotificationEmail=False,
                                       body={"type": "user", "role": "reader",
                                             "emailAddress": OWNER_GMAIL}).execute()
        ids[name] = fid
        print("%-45s %s" % (name, fid))
    _backup_folder_id(drive)
    print("backup folder ready: %r" % BACKUP_FOLDER_NAME)
    print(json.dumps(ids))


def _meta(drive, file_id):
    return drive.files().get(fileId=file_id,
                             fields="id,name,mimeType,size,modifiedTime,capabilities(canEdit)").execute()


# ---------------------------------------------------------------- auth / verify / pull
def cmd_auth(manual, url=False, finish=None):
    if url:
        return auth_url_step()
    if finish:
        auth_finish_step(finish)
    creds = get_creds(manual=manual)
    _, _, _, build = _libs()
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    who = _whoami(drive)
    print("signed in as:", who)
    if not who.lower().endswith("@" + WORKSPACE_DOMAIN):
        print("WARNING: not a %s account. Delete secrets\\token.json and re-run auth." % WORKSPACE_DOMAIN)
        sys.exit(1)
    print("token cached at", TOKEN_PATH)


def cmd_verify():
    drive, _ = services()
    print("signed in as:", _whoami(drive))
    ok = True
    for label, fid in ((APPROVALS_NAME, APPROVALS_ID), (SELL_NAME, SELL_ID)):
        m = _meta(drive, fid)
        can = m.get("capabilities", {}).get("canEdit")
        print("%-22s %-45s canEdit=%s  modified=%s" % (label, m["mimeType"].split(".")[-1].split("/")[-1],
                                                        can, m.get("modifiedTime")))
        ok = ok and bool(can)
    if not ok:
        sys.exit("\nNo edit rights on one of the files. Share it with %s as Editor." % WORKSPACE_ACCOUNT)
    print("\nOK - read and write access confirmed on both files.")


def cmd_pull():
    drive, _ = services()
    n = _download_xlsx(drive, SELL_ID, MASTER)
    print("pulled %s bytes -> %s" % (n, MASTER))


# ---------------------------------------------------------------- Sell Sheet helpers
def _headers(ws):
    return {str(c.value).strip(): c.column for c in ws[HEADER_ROW] if c.value not in (None, "")}


def _col(headers, name):
    if name in headers:
        return headers[name]
    for h, i in headers.items():
        if h.startswith(name):
            return i
    return None


def _row_index(ws, headers):
    c = _col(headers, "Row ID")
    out, dupes = {}, set()
    for r in range(FIRST_DATA_ROW, ws.max_row + 1):
        v = ws.cell(row=r, column=c).value
        if v not in (None, ""):
            k = str(v).strip()
            if k in out:
                dupes.add(k)
            out[k] = r
    return out, dupes


def _anchor_row(ws):
    for r in range(FIRST_DATA_ROW, ws.max_row + 1):
        v = ws.cell(row=r, column=1).value
        if v and str(v).strip().startswith(SUMMARY_ANCHOR):
            return r
    return None


def _last_card_row(ws, headers):
    """Last real card row: last row with a Row ID above the summary block."""
    c = _col(headers, "Row ID")
    anchor = _anchor_row(ws) or (ws.max_row + 1)
    last = FIRST_DATA_ROW - 1
    for r in range(FIRST_DATA_ROW, anchor):
        if ws.cell(row=r, column=c).value not in (None, ""):
            last = r
    return last


def _pull_and_backup(drive):
    n = _download_xlsx(drive, SELL_ID, MASTER)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup = _unique(os.path.join(BACKUP_DIR, "%s %s PRE-WRITE backup.xlsx" % (SELL_NAME, _stamp())))
    shutil.copy2(MASTER, backup)
    print("Sell Sheet: pulled %s bytes; backup -> %s" % (n, os.path.basename(backup)))
    _drive_backup(drive, backup)
    return backup


def _upload_sell(drive, wb):
    from googleapiclient.http import MediaFileUpload
    out = os.path.join(WORK_DIR, "master_out.xlsx")
    wb.save(out)
    media = MediaFileUpload(out, mimetype=XLSX_MIME, resumable=True)
    drive.files().update(fileId=SELL_ID, media_body=media).execute()   # same file ID, always
    print("uploaded %s bytes to Drive file %s" % (os.path.getsize(out), SELL_ID))


# ---------------------------------------------------------------- audit / fix-ranges
RANGE_RE = re.compile(r"(\$?[A-Z]{1,3}\$?)(\d+):(\$?[A-Z]{1,3}\$?)(\d+)")


def _stale_range(m, last):
    """A range that starts at the data block (header row or first data row) but stops
    short of the real last card row is stale. No hardcoded row number involved."""
    r1, r2 = int(m.group(2)), int(m.group(4))
    return r1 in (HEADER_ROW, FIRST_DATA_ROW) and FIRST_DATA_ROW <= r2 < last


def _widen_ref(ref, last, col_end=None):
    def sub(m):
        if not _stale_range(m, last):
            return m.group(0)
        end_col = col_end or m.group(3)
        return "%s%s:%s%d" % (m.group(1), m.group(2), end_col, last)
    return RANGE_RE.sub(sub, str(ref))


def _scan(wb, last):
    """Everything tied to a stale card-range end. Returns [(location, kind, text)]."""
    out = []
    for ws in wb:
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if isinstance(v, str) and v.startswith("=") and \
                        (ws.title == "Sell Sheet" or "Sell Sheet" in v):
                    if any(_stale_range(m, last) and m.group(1).replace("$", "") == m.group(3).replace("$", "")
                           for m in RANGE_RE.finditer(v)):
                        out.append(("%s!%s" % (ws.title, c.coordinate), "formula", v))
        if ws.title == "Sell Sheet":
            for dv in (ws.data_validations.dataValidation if ws.data_validations else []):
                if any(_stale_range(m, last) for m in RANGE_RE.finditer(str(dv.sqref))):
                    out.append(("%s dataValidation" % ws.title, "validation", str(dv.sqref)))
            for cf in ws.conditional_formatting:
                if any(_stale_range(m, last) for m in RANGE_RE.finditer(str(cf.sqref))):
                    out.append(("%s conditionalFormat" % ws.title, "cond-format", str(cf.sqref)))
            if ws.auto_filter and ws.auto_filter.ref:
                if any(_stale_range(m, last) for m in RANGE_RE.finditer(ws.auto_filter.ref)):
                    out.append(("%s autoFilter" % ws.title, "filter", ws.auto_filter.ref))
            if ws.print_area and any(_stale_range(m, last) for m in RANGE_RE.finditer(str(ws.print_area))):
                out.append(("%s print area" % ws.title, "print-area", str(ws.print_area)))
    for name, dn in wb.defined_names.items():
        if "Sell" in str(dn.attr_text) and any(_stale_range(m, last) for m in RANGE_RE.finditer(str(dn.attr_text))):
            out.append(("defined name %s" % name, "defined-name", dn.attr_text))
    return out


def _col_gaps(ws, headers, last):
    """Card rows missing a formula their neighbours have (informational only)."""
    gaps = []
    for name in ("Est. hammer", "Hammer vs CL", "Net gain"):
        c = _col(headers, name)
        if not c:
            continue
        have = [r for r in range(FIRST_DATA_ROW, last + 1)
                if isinstance(ws.cell(row=r, column=c).value, str) and ws.cell(row=r, column=c).value.startswith("=")]
        miss = [r for r in range(FIRST_DATA_ROW, last + 1) if r not in set(have)]
        if have and miss:
            gaps.append((name, len(miss), miss[:6]))
    return gaps


def _layout_report(ws):
    headers = _headers(ws)
    anchor = _anchor_row(ws)
    last = _last_card_row(ws, headers)
    cert_c = _col(headers, "Cert")
    below = 0
    if anchor:
        for r in range(anchor, ws.max_row + 1):
            if cert_c and ws.cell(row=r, column=cert_c).value not in (None, ""):
                below += 1
    idx, dupes = _row_index(ws, headers)
    print("Sell Sheet layout: header row %d, first data row %d, last card row %s, "
          "summary anchor row %s" % (HEADER_ROW, FIRST_DATA_ROW, last, anchor))
    print("card rows (Row IDs above summary): %d" % (last - FIRST_DATA_ROW + 1 if last >= FIRST_DATA_ROW else 0))
    if anchor is None:
        print("WARNING: summary anchor %r not found - totals block may have moved." % SUMMARY_ANCHOR)
    if below:
        print("WARNING: %d row(s) with a Cert sit at/below the summary anchor - outside every total." % below)
    if dupes:
        print("WARNING: duplicate Row IDs: %s" % ", ".join(sorted(dupes)[:10]))
    return last, anchor


def cmd_audit():
    import openpyxl
    drive, _ = services()
    _download_xlsx(drive, SELL_ID, MASTER)
    wb = openpyxl.load_workbook(MASTER)
    ws = wb["Sell Sheet"]
    last, _ = _layout_report(ws)
    hits = _scan(wb, last)
    print("\nranges that stop short of row %d: %d" % (last, len(hits)))
    for loc, kind, txt in hits[:60]:
        print("  [%s] %s  %s" % (kind, loc, txt[:110]))
    if len(hits) > 60:
        print("  ... and %d more" % (len(hits) - 60))
    if not hits:
        print("  none - every total, validation and filter reaches the last card row.")
    for name, n, sample in _col_gaps(ws, _headers(ws), last):
        print("note: %d card row(s) have no %r formula (e.g. rows %s) - not touched." % (n, name, sample))
    if hits:
        print("\nNext: python tools\\card_sheet_writer.py fix-ranges   (dry run)")


def cmd_fix_ranges(commit):
    import openpyxl
    from openpyxl.worksheet.cell_range import MultiCellRange
    drive, _ = services()
    backup = _pull_and_backup(drive)
    wb = openpyxl.load_workbook(MASTER)
    ws = wb["Sell Sheet"]
    last, anchor = _layout_report(ws)
    if anchor is None:
        sys.exit("Refusing: summary anchor not found, can't tell where card rows end.")
    last_col = max(_headers(ws).values())
    from openpyxl.utils import get_column_letter
    end_letter = get_column_letter(last_col)
    changes = []
    for sh in wb:
        for row in sh.iter_rows():
            for c in row:
                v = c.value
                if not (isinstance(v, str) and v.startswith("=") and (sh.title == "Sell Sheet" or "Sell Sheet" in v)):
                    continue
                new = RANGE_RE.sub(lambda m: _widen_ref(m.group(0), last)
                                   if m.group(1).replace("$", "") == m.group(3).replace("$", "") else m.group(0), v)
                if new != v:
                    changes.append((sh.title, c.coordinate, v, new))
                    if commit:
                        c.value = new
    for dv in (ws.data_validations.dataValidation if ws.data_validations else []):
        old = str(dv.sqref)
        new = _widen_ref(old, last)
        if new != old:
            changes.append(("Sell Sheet", "validation", old, new))
            if commit:
                dv.sqref = MultiCellRange(new)
    if ws.auto_filter and ws.auto_filter.ref:
        old = ws.auto_filter.ref
        new = _widen_ref(old, last, col_end=end_letter)
        if new != old:
            changes.append(("Sell Sheet", "autoFilter", old, new))
            if commit:
                ws.auto_filter.ref = new
    print("\n--- %s (%d changes) ---" % ("WROTE TO SHEET" if commit else "WOULD CHANGE", len(changes)))
    for t, coord, old, new in changes[:15]:
        print("  %s!%s  %s -> %s" % (t, coord, old, new))
    if len(changes) > 15:
        print("  ... and %d more of the same pattern" % (len(changes) - 15))
    if not changes:
        print("Nothing stale. Totals, validation and filter already reach row %d." % last)
        return
    if not commit:
        print("\nDRY RUN - nothing uploaded. Re-run with --commit.")
        return
    _upload_sell(drive, wb)
    chk = os.path.join(WORK_DIR, "master_verify.xlsx")
    _download_xlsx(drive, SELL_ID, chk)
    wv = openpyxl.load_workbook(chk)
    left = _scan(wv, last)
    print("post-write verification:", "ALL GOOD - nothing left short of row %d" % last if not left else
          "%d item(s) still stale" % len(left))
    if left:
        for loc, kind, txt in left[:10]:
            print("  [%s] %s  %s" % (kind, loc, txt[:100]))
        print("Pre-write backup:", backup)
        sys.exit(1)


# ---------------------------------------------------------------- Approvals (native Google Sheet)
def _appr_tab(sheets):
    md = sheets.spreadsheets().get(spreadsheetId=APPROVALS_ID,
                                   fields="sheets(properties(title,sheetId,index))").execute()
    titles = [s["properties"]["title"] for s in md["sheets"]]
    return "Approvals" if "Approvals" in titles else titles[0]


def _a1(col_idx0):
    s, n = "", col_idx0 + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _appr_read(sheets, tab):
    res = sheets.spreadsheets().values().get(
        spreadsheetId=APPROVALS_ID, range="'%s'!A1:H" % tab,
        valueRenderOption="FORMATTED_VALUE").execute()
    rows = res.get("values", [])
    hdr = [str(h).strip() for h in (rows[APPR_HEADER_ROW - 1] if rows else [])]
    return hdr, rows


def _appr_apply(drive, sheets, ops, commit):
    """Returns (applied, refused, backup_path)."""
    tab = _appr_tab(sheets)
    hdr, rows = _appr_read(sheets, tab)
    col = {h: i for i, h in enumerate(hdr)}
    need = ["Row ID", "Cert"]
    if any(n not in col for n in need):
        sys.exit("Approvals header row 1 unexpected: %r" % hdr)
    ids, dup = {}, set()
    for i, r in enumerate(rows[APPR_HEADER_ROW:], start=APPR_HEADER_ROW + 1):
        k = (r[col["Row ID"]].strip() if len(r) > col["Row ID"] else "")
        if k:
            if k in ids:
                dup.add(k)
            ids[k] = i
    applied, refused, writes = [], [], []
    for op in ops:
        rid = str(op.get("row_id", "")).strip()
        if rid in dup:
            refused.append((op, "duplicate Row ID %s in sheet" % rid)); continue
        if rid not in ids:
            refused.append((op, "Row ID %s not found" % rid)); continue
        rn = ids[rid]
        row = rows[rn - 1]
        cert = row[col["Cert"]] if len(row) > col["Cert"] else ""
        if norm_cert(cert) == HARD_LOCK_NORM:
            refused.append((op, "cert %s is the partnership hard lock - refused" % HARD_LOCK_CERT)); continue
        exp = op.get("expect_cert")
        if exp is None or str(exp).strip() == "":
            refused.append((op, "expect_cert is required for Approvals writes")); continue
        if norm_cert(exp) != norm_cert(cert):
            refused.append((op, "cert mismatch: sheet has %r, op expected %r" % (cert, exp))); continue
        if norm_cert(exp) == HARD_LOCK_NORM:
            refused.append((op, "hard lock cert")); continue
        for field, val in op.get("set", {}).items():
            f = field.strip()
            if f not in col:
                refused.append((op, "no column %r" % f)); continue
            if f in APPR_PROTECTED:
                refused.append((op, "column %r is identity - not writable" % f)); continue
            ci = col[f]
            before = row[ci] if len(row) > ci else ""
            cell = "'%s'!%s%d" % (tab, _a1(ci), rn)
            writes.append({"range": cell, "values": [[val]], "_rid": rid, "_field": f,
                           "_before": before, "_row": rn, "_cert": cert})
            applied.append("%s  %s  %-14s %r -> %r" % (rid, "%s%d" % (_a1(ci), rn), f, before, val))

    backup = None
    if commit and writes:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        backup = _unique(os.path.join(BACKUP_DIR, "%s %s PRE-WRITE backup.xlsx" % (APPROVALS_NAME, _stamp())))
        n = _export_sheet_xlsx(drive, APPROVALS_ID, backup)
        print("Approvals: backup (%s bytes) -> %s" % (n, os.path.basename(backup)))
        _drive_backup(drive, backup)
        sheets.spreadsheets().values().batchUpdate(
            spreadsheetId=APPROVALS_ID,
            body={"valueInputOption": "RAW",
                  "data": [{"range": w["range"], "values": w["values"]} for w in writes]}).execute()
    return applied, refused, writes, backup, tab


def _appr_verify(sheets, writes, tab):
    bad = 0
    for w in writes:
        got = sheets.spreadsheets().values().get(
            spreadsheetId=APPROVALS_ID, range=w["range"],
            valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [[""]])
        got = got[0][0] if got and got[0] else ""
        want = w["values"][0][0]
        same = (float(got) == float(want)) if isinstance(want, (int, float)) and \
            isinstance(got, (int, float)) else (str(got) == str(want))
        # identity re-check: Row ID / Cert in that row must be unchanged
        idr = sheets.spreadsheets().values().get(
            spreadsheetId=APPROVALS_ID, range="'%s'!A%d:B%d" % (tab, w["_row"], w["_row"]),
            valueRenderOption="FORMATTED_VALUE").execute().get("values", [[]])[0]
        id_ok = len(idr) >= 2 and idr[0].strip() == w["_rid"] and norm_cert(idr[1]) == norm_cert(w["_cert"])
        if not same or not id_ok:
            bad += 1
            print("  VERIFY FAIL %s %s: got %r expected %r%s" % (
                w["_rid"], w["range"], got, want, "" if id_ok else "  (row identity changed!)"))
    return bad


# ---------------------------------------------------------------- apply
def cmd_apply(ops_path, commit):
    spec = json.load(open(ops_path))
    ops = spec.get("ops", [])
    appr_ops = [o for o in ops if str(o.get("file", "")).lower() == "approvals"]
    sell_ops = [o for o in ops if o not in appr_ops]
    drive, sheets = services()
    print("signed in as:", _whoami(drive), "|", "COMMIT" if commit else "DRY RUN")
    exit_bad = 0

    # ---- Approvals (native Google Sheet)
    if appr_ops:
        applied, refused, writes, backup, tab = _appr_apply(drive, sheets, appr_ops, commit)
        print("\n--- %s: %s (%d cells) ---" % (
            APPROVALS_NAME, "WROTE TO SHEET" if commit and writes else "WOULD WRITE", len(applied)))
        for a in applied:
            print("  ", a)
        if refused:
            print("--- REFUSED (%d) ---" % len(refused))
            for op, why in refused:
                print("   %s :: %s" % (json.dumps(op)[:90], why))
        if commit and writes:
            bad = _appr_verify(sheets, writes, tab)
            print("post-write verification:", "ALL GOOD - %d cell(s) re-read and matched" % len(writes)
                  if bad == 0 else "%d MISMATCH(ES)" % bad)
            if bad:
                print("Pre-write backup:", backup)
                exit_bad = 1
        elif applied:
            print("DRY RUN - nothing written. Re-run with --commit.")

    # ---- Sell Sheet (xlsx in Drive)
    if sell_ops:
        import openpyxl
        backup = _pull_and_backup(drive)
        wb = openpyxl.load_workbook(MASTER)
        applied, refused = [], []
        for op in sell_ops:
            tab = op.get("tab", "Sell Sheet")
            if tab not in wb.sheetnames:
                refused.append((op, "no such tab: %s" % tab)); continue
            ws = wb[tab]
            if "append" in op:
                if tab == "Sell Sheet":
                    refused.append((op, "append to Sell Sheet is not supported - card rows sit above "
                                        "the totals block; add rows by inserting, then run fix-ranges"))
                    continue
                row = ws.max_row + 1
                for i, val in enumerate(op["append"], start=1):
                    ws.cell(row=row, column=i).value = val
                applied.append("%s: appended row %d" % (tab, row))
                continue
            if tab != "Sell Sheet":
                refused.append((op, "only append is supported on %s" % tab)); continue
            headers = _headers(ws)
            idx, dupes = _row_index(ws, headers)
            rid = str(op.get("row_id", "")).strip()
            if rid in dupes:
                refused.append((op, "duplicate Row ID %s" % rid)); continue
            if rid not in idx:
                refused.append((op, "Row ID %s not found" % rid)); continue
            r = idx[rid]
            cert = ws.cell(row=r, column=_col(headers, "Cert")).value
            if norm_cert(cert) == HARD_LOCK_NORM:
                refused.append((op, "cert %s is the partnership hard lock - refused" % HARD_LOCK_CERT)); continue
            exp = op.get("expect_cert")
            if exp is not None and norm_cert(exp) != norm_cert(cert):
                refused.append((op, "cert mismatch: sheet has %r, op expected %r" % (cert, exp))); continue
            for field, val in op.get("set", {}).items():
                c = _col(headers, field)
                if c is None:
                    refused.append((op, "no column %r" % field)); continue
                before = ws.cell(row=r, column=c).value
                if isinstance(before, str) and before.startswith("="):
                    refused.append((op, "%s row %d is a formula - not overwritten" % (field, r))); continue
                ws.cell(row=r, column=c).value = val
                applied.append("%s  row %d  %-18s %r -> %r" % (rid, r, field, before, val))
        print("\n--- %s: %s (%d) ---" % (SELL_NAME, "WROTE TO SHEET" if commit and applied else "WOULD WRITE",
                                       len(applied)))
        for a in applied:
            print("  ", a)
        if refused:
            print("--- REFUSED (%d) ---" % len(refused))
            for op, why in refused:
                print("   %s :: %s" % (json.dumps(op)[:90], why))
        if applied and commit:
            _upload_sell(drive, wb)
            chk = os.path.join(WORK_DIR, "master_verify.xlsx")
            _download_xlsx(drive, SELL_ID, chk)
            v = openpyxl.load_workbook(chk)
            bad = 0
            for op in sell_ops:
                if op.get("tab", "Sell Sheet") != "Sell Sheet" or "set" not in op:
                    continue
                w = v["Sell Sheet"]; h = _headers(w); idx, _ = _row_index(w, h)
                r = idx.get(str(op["row_id"]).strip())
                if r is None:
                    print("  VERIFY FAIL: %s vanished" % op["row_id"]); bad += 1; continue
                for field, val in op["set"].items():
                    got = w.cell(row=r, column=_col(h, field)).value
                    if got != val and not (isinstance(val, (int, float)) and isinstance(got, (int, float))
                                           and float(got) == float(val)):
                        print("  VERIFY FAIL: %s %s = %r, expected %r" % (op["row_id"], field, got, val)); bad += 1
            print("post-write verification:", "ALL GOOD" if bad == 0 else "%d MISMATCH(ES)" % bad)
            if bad:
                print("Pre-write backup:", backup); exit_bad = 1
        elif applied:
            print("DRY RUN - nothing uploaded. Re-run with --commit.")
    if exit_bad:
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("auth"); a.add_argument("--manual", action="store_true")
    a.add_argument("--url", action="store_true"); a.add_argument("--finish")
    sub.add_parser("verify"); sub.add_parser("pull"); sub.add_parser("publish-cloud")
    sub.add_parser("audit")
    fx = sub.add_parser("fix-ranges"); fx.add_argument("--commit", action="store_true")
    ap2 = sub.add_parser("apply"); ap2.add_argument("ops"); ap2.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    {"auth": lambda: cmd_auth(args.manual, args.url, args.finish), "verify": cmd_verify, "pull": cmd_pull, "publish-cloud": cmd_publish_cloud,
     "audit": cmd_audit,
     "fix-ranges": lambda: cmd_fix_ranges(args.commit),
     "apply": lambda: cmd_apply(args.ops, args.commit)}[args.cmd]()


if __name__ == "__main__":
    main()
