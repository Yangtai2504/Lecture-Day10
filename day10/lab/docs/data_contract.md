# Data contract — Lab Day 10

> Đồng bộ với `contracts/data_contract.yaml`.

---

## 1. Nguồn dữ liệu (source map)

| Nguồn | Phương thức ingest | Failure mode chính | Metric / alert |
|-------|-------------------|--------------------|----------------|
| `policy_refund_v4` | CSV export từ CS system | Stale refund window 14 ngày (bản v3 cũ lẫn vào export) | `expectation[refund_no_stale_14d_window] FAIL` |
| `sla_p1_2026` | CSV export từ ITSM | Chunk rỗng, missing effective_date | `quarantine_records` tăng; `expectation[min_one_row]` |
| `it_helpdesk_faq` | CSV export từ Helpdesk portal | Duplicate entries, mixed date formats (DD/MM/YYYY) | `quarantine_records[duplicate_chunk_text]` |
| `hr_leave_policy` | CSV export từ HR system | Version conflict 2025 vs 2026 (10 ngày vs 12 ngày phép năm) | `expectation[hr_leave_no_stale_10d_annual] FAIL` |
| `access_control_sop` | CSV export từ IT Security system | Không có trong allowlist baseline; row rỗng; date lạ | `expectation[access_control_sop_present] FAIL` |

---

## 2. Schema cleaned

| Cột | Kiểu | Bắt buộc | Ghi chú |
|-----|------|----------|---------|
| `chunk_id` | string | Có | `sha256(doc_id\|chunk_text\|seq)[:16]` — ổn định giữa các run |
| `doc_id` | string | Có | Một trong 5 giá trị trong `ALLOWED_DOC_IDS` |
| `chunk_text` | string | Có | Tối thiểu 8 ký tự; đã strip noise prefix |
| `effective_date` | date | Có | Format `YYYY-MM-DD`; parse từ ISO và `DD/MM/YYYY` |
| `exported_at` | datetime | Không (best-effort) | Dùng cho freshness SLA; có thể rỗng |

---

## 3. Quy tắc quarantine vs drop

**Quarantine** (lưu vào `artifacts/quarantine/quarantine_<run_id>.csv`):
- `unknown_doc_id`: doc_id không thuộc allowlist — không drop, giữ để audit trail
- `missing_effective_date`: không có ngày hiệu lực — cần data owner fix upstream
- `invalid_effective_date_format`: ngày sai format — pipeline tự parse DD/MM/YYYY; format khác cần fix
- `stale_hr_policy_effective_date`: HR row có effective_date < 2026-01-01 — chờ re-export bản mới
- `stale_hr_annual_leave_content`: HR row chứa "10 ngày phép năm" — bản HR 2025 lẫn vào export 2026
- `missing_chunk_text`: text rỗng sau strip — cần check upstream export
- `excessive_text_repetition`: text lặp lại ≥3 lần — lỗi migration/sync
- `duplicate_chunk_text`: nội dung trùng — giữ bản đầu, quarantine bản sau

**Ai approve merge lại**: Data Owner của nguồn tương ứng (xem `canonical_sources` trong YAML). Quarantine không tự động merge; cần pipeline rerun sau khi upstream fix.

---

## 4. Phiên bản & canonical

| Policy | Source of truth | Version hiện tại | Ghi chú |
|--------|----------------|-----------------|---------|
| Refund | `data/docs/policy_refund_v4.txt` | v4 (7 ngày làm việc) | v3 (14 ngày) là stale — pipeline fix tự động |
| SLA P1 | `data/docs/sla_p1_2026.txt` | 2026 | Phản hồi 15 phút, resolution 4h |
| IT FAQ | `data/docs/it_helpdesk_faq.txt` | 2026-01-20 | Khóa sau 5 lần sai, VPN 2 thiết bị |
| HR Leave | `data/docs/hr_leave_policy.txt` | 2026 (min effective 2026-01-01) | 12 ngày phép <3 năm; 15 ngày 3-5 năm; 18 ngày >5 năm |
| Access Control | `data/docs/access_control_sop.txt` | 2026-01-01 | Level 4 cần IT Manager + CISO |
