"""
Cleaning rules — raw export → cleaned rows + quarantine.

Baseline gồm các failure mode mở rộng (allowlist doc_id, parse ngày, HR stale version).
Sinh viên thêm ≥3 rule mới: mỗi rule phải ghi `metric_impact` (xem README — chống trivial).
"""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

_CONTRACT_PATH = Path(__file__).resolve().parent.parent / "contracts" / "data_contract.yaml"
_DEFAULT_HR_MIN_DATE = "2026-01-01"


def load_hr_min_effective_date(contract_path: Path = _CONTRACT_PATH) -> str:
    """
    Đọc hr_leave_min_effective_date từ data_contract.yaml → policy_versioning.
    Rule 4 dùng giá trị này thay vì hard-code, để thay đổi contract là đủ để
    thay đổi quyết định clean mà không cần sửa code.
    Fallback về _DEFAULT_HR_MIN_DATE nếu file không tồn tại hoặc field vắng mặt.
    """
    try:
        import yaml  # pyyaml
        data = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
        val = (data or {}).get("policy_versioning", {}).get("hr_leave_min_effective_date")
        if val:
            return str(val)
    except Exception:
        pass
    return _DEFAULT_HR_MIN_DATE


# Khớp export hợp lệ trong lab (mở rộng khi nhóm thêm doc mới — phải đồng bộ contract).
ALLOWED_DOC_IDS = frozenset(
    {
        "policy_refund_v4",
        "sla_p1_2026",
        "it_helpdesk_faq",
        "hr_leave_policy",
        "access_control_sop",  # thêm mới: cần cho gq_d10_10 (IT Manager/CISO)
    }
)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DMY_SLASH = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_NOISE_PREFIX = re.compile(r"^(Nội dung không rõ ràng:\s*|!+\s*)")
_REPEATED_SEGMENT = re.compile(r"(.{20,}?)\1{2,}")


def _norm_text(s: str) -> str:
    return " ".join((s or "").strip().split()).lower()


def _stable_chunk_id(doc_id: str, chunk_text: str, seq: int) -> str:
    h = hashlib.sha256(f"{doc_id}|{chunk_text}|{seq}".encode("utf-8")).hexdigest()[:16]
    return f"{doc_id}_{seq}_{h}"


def _normalize_effective_date(raw: str) -> Tuple[str, str]:
    """
    Trả về (iso_date, error_reason).
    iso_date rỗng nếu không parse được.
    """
    s = (raw or "").strip()
    if not s:
        return "", "empty_effective_date"
    if _ISO_DATE.match(s):
        return s, ""
    m = _DMY_SLASH.match(s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{yyyy}-{mm}-{dd}", ""
    return "", "invalid_effective_date_format"


def _strip_noise_prefix(text: str) -> str:
    """
    Rule mới 1: Loại bỏ prefix nhiễu từ upstream export.
    "Nội dung không rõ ràng: " và "!!!" là artifact của hệ thống ingest cũ.
    Một số row có prefix lồng nhau ("Nội dung không rõ ràng: !!!...") nên cần
    loop cho đến khi ổn định — sub một lần không đủ.
    metric_impact: thay đổi chunk_text của ~12 rows; một số trở thành duplicate
    và bị quarantine bởi rule dedup, giảm cleaned_records.
    """
    prev = None
    while prev != text:
        prev = text
        text = _NOISE_PREFIX.sub("", text).strip()
    return text


def _has_excessive_repetition(text: str) -> bool:
    """
    Rule mới 2: Phát hiện text bị copy-paste lặp lại (≥3 lần, đoạn ≥20 ký tự).
    Đây là lỗi migration — cùng câu xuất hiện 3-5 lần trong một chunk.
    metric_impact: quarantine ~4 rows có repetition khi inject; khi pipeline chuẩn
    giảm quarantine nếu data sạch.
    """
    return bool(_REPEATED_SEGMENT.search(text))


def load_raw_csv(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({k: (v or "").strip() for k, v in r.items()})
    return rows


def clean_rows(
    rows: List[Dict[str, str]],
    *,
    apply_refund_window_fix: bool = True,
    hr_min_date: str | None = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Trả về (cleaned, quarantine).

    Rules (baseline + mở rộng):
    1) Quarantine: doc_id không thuộc allowlist (export lạ / catalog sai).
    2) Chuẩn hoá effective_date sang YYYY-MM-DD; quarantine nếu không parse được.
    3) [NEW] Strip prefix nhiễu: "Nội dung không rõ ràng: " và "!!!".
    4) Quarantine: chunk hr_leave_policy có effective_date < hr_min_date
       (đọc từ data_contract.yaml → policy_versioning.hr_leave_min_effective_date,
       không hard-code — thay đổi contract là đủ để thay đổi quyết định clean).
    5) [NEW] Quarantine: hr_leave_policy chứa "10 ngày phép năm" (marker bản HR 2025 stale).
    6) Quarantine: chunk_text rỗng hoặc effective_date rỗng sau chuẩn hoá.
    7) [NEW] Quarantine: text lặp lại quá mức (cùng đoạn ≥20 ký tự xuất hiện ≥3 lần).
    8) Loại trùng nội dung chunk_text (giữ bản đầu).
    9) Fix stale refund: policy_refund_v4 chứa '14 ngày làm việc' → 7 ngày.
    """
    effective_hr_min = hr_min_date or load_hr_min_effective_date()
    quarantine: List[Dict[str, Any]] = []
    seen_text: set[str] = set()
    cleaned: List[Dict[str, Any]] = []
    seq = 0

    for raw in rows:
        doc_id = raw.get("doc_id", "")
        text = raw.get("chunk_text", "")
        eff_raw = raw.get("effective_date", "")
        exported_at = raw.get("exported_at", "")

        # Rule 1: allowlist
        if doc_id not in ALLOWED_DOC_IDS:
            quarantine.append({**raw, "reason": "unknown_doc_id"})
            continue

        # Rule 2: normalize date
        eff_norm, eff_err = _normalize_effective_date(eff_raw)
        if eff_err == "empty_effective_date":
            quarantine.append({**raw, "reason": "missing_effective_date"})
            continue
        if eff_err == "invalid_effective_date_format":
            quarantine.append({**raw, "reason": eff_err, "effective_date_raw": eff_raw})
            continue

        # Rule 3 (NEW): strip noise prefix trước mọi kiểm tra nội dung
        text = _strip_noise_prefix(text)

        # Rule 4: HR stale date filter — cutoff đọc từ contract, không hard-code
        if doc_id == "hr_leave_policy" and eff_norm < effective_hr_min:
            quarantine.append(
                {
                    **raw,
                    "reason": "stale_hr_policy_effective_date",
                    "effective_date_normalized": eff_norm,
                    "hr_min_date_used": effective_hr_min,
                }
            )
            continue

        # Rule 5 (NEW): HR stale annual leave content — quarantine bất kể date
        if doc_id == "hr_leave_policy" and "10 ngày phép năm" in text:
            quarantine.append(
                {
                    **raw,
                    "reason": "stale_hr_annual_leave_content",
                    "effective_date_normalized": eff_norm,
                }
            )
            continue

        # Rule 6: empty text after strip
        if not text:
            quarantine.append({**raw, "reason": "missing_chunk_text"})
            continue

        # Rule 7 (NEW): excessive repetition
        if _has_excessive_repetition(text):
            quarantine.append({**raw, "reason": "excessive_text_repetition"})
            continue

        # Rule 8: dedup by normalized text
        key = _norm_text(text)
        if key in seen_text:
            quarantine.append({**raw, "reason": "duplicate_chunk_text"})
            continue
        seen_text.add(key)

        # Rule 9: fix stale refund window
        fixed_text = text
        if apply_refund_window_fix and doc_id == "policy_refund_v4":
            if "14 ngày làm việc" in fixed_text:
                fixed_text = fixed_text.replace(
                    "14 ngày làm việc",
                    "7 ngày làm việc",
                )
                fixed_text += " [cleaned: stale_refund_window]"

        seq += 1
        cleaned.append(
            {
                "chunk_id": _stable_chunk_id(doc_id, fixed_text, seq),
                "doc_id": doc_id,
                "chunk_text": fixed_text,
                "effective_date": eff_norm,
                "exported_at": exported_at or "",
            }
        )

    return cleaned, quarantine


def write_cleaned_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at\n", encoding="utf-8")
        return
    fieldnames = ["chunk_id", "doc_id", "chunk_text", "effective_date", "exported_at"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def write_quarantine_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at,reason\n", encoding="utf-8")
        return
    keys: List[str] = []
    seen_k: set[str] = set()
    for r in rows:
        for k in r.keys():
            if k not in seen_k:
                seen_k.add(k)
                keys.append(k)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore", restval="")
        w.writeheader()
        for r in rows:
            w.writerow(r)
