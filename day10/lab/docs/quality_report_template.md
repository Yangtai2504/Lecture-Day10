# Quality report — Lab Day 10 (nhóm)

**run_id:** fix-03
**Ngày:** 2026-06-10

---

## 1. Tóm tắt số liệu

| Chỉ số | inject-bad (before) | fix-01 (after) | Ghi chú |
|--------|--------------------|--------------------|---------|
| raw_records | 247 | 247 | Cùng input CSV |
| cleaned_records | 36 | 35 | fix-03: strip_noise_prefix loop → 1 thêm duplicate bị quarantine |
| quarantine_records | 211 | 212 | fix-03: "!!!Ticket P1..." sau khi strip → duplicate → quarantine |
| Expectation halt? | YES — `refund_no_stale_14d_window FAIL` | NO — tất cả PASS | inject bypass với `--skip-validate` |
| embed_prune_removed | 0 | 29 | fix-03: flush toàn bộ stale vector từ run cũ + model thay đổi |

---

## 2. Before / after retrieval

File before: `artifacts/eval/after_inject_bad.csv`
File after: `artifacts/eval/after_fix.csv`

**Câu hỏi then chốt: refund window (`q_refund_window`)**

Trước (inject-bad):
```
q_refund_window,contains_expected=yes,hits_forbidden=yes,top1_doc_id=policy_refund_v4
top1_preview: "Yêu cầu hoàn tiền được chấp nhận trong vòng 14 ngày làm việc kể từ xác nhận đơn."
```

Sau (fix-01):
```
q_refund_window,contains_expected=yes,hits_forbidden=no,top1_doc_id=policy_refund_v4
top1_preview: "Yêu cầu được gửi trong vòng 7 ngày làm việc kể từ thời điểm xác nhận đơn hàng."
```

**Delta:** `hits_forbidden` từ `yes` → `no`. Pipeline fix đã loại chunk "14 ngày" ra khỏi vector store (via `embed_prune_removed=1`).

**HR version (`q_hr_annual_leave_under3`)**

Trước (inject-bad):
```
q_hr_annual_leave_under3,contains_expected=yes,hits_forbidden=no,top1_preview: "12 ngày phép năm theo chính sách 2026"
```

Sau (fix-01): Giống nhau — HR stale content đã bị quarantine bởi cả hai run (Rule 5 hoạt động trong cả inject và fix).

**Access Control (`q_access_level4`)**

Cả inject-bad và fix-01 đều PASS vì `access_control_sop` đã được thêm vào allowlist.

---

## 3. Freshness & monitor

Kết quả: `freshness_check=FAIL` cho cả hai run.

```json
{"latest_exported_at": "2026-04-10T00:00:00", "age_hours": 1469.551, "sla_hours": 24.0, "reason": "freshness_sla_exceeded"}
```

**Giải thích:** CSV mẫu lab có `exported_at` từ đầu tháng 4/2026 — cũ hơn 24h so với thời điểm chạy pipeline (2026-06-10). Đây là **hành vi đúng** cho data snapshot cũ. Freshness FAIL không ngăn pipeline tiếp tục (chỉ log, không halt). Trong production, FAIL sẽ trigger alert yêu cầu re-export.

---

## 4. Corruption inject (Sprint 3)

**Cách inject:** `python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate`

- `--no-refund-fix`: tắt rule fix refund window (giữ nguyên "14 ngày làm việc" trong cleaned text)
- `--skip-validate`: bypass `expectation[refund_no_stale_14d_window] FAIL (halt)` để vẫn embed

**Phát hiện corruption:**
1. Expectation E3 (`refund_no_stale_14d_window`) FAIL — phát hiện ngay khi run
2. Eval `q_refund_window`: `hits_forbidden=yes` — "14 ngày" lọt vào top-k retrieval
3. Grading `gq_d10_01`: `hits_forbidden=true` khi chạy với inject-bad data

**Recovery:** Rerun pipeline chuẩn (`python etl_pipeline.py run`) → `embed_prune_removed=1` xóa vector stale → `hits_forbidden=no`.

---

## 5. Hạn chế & việc chưa làm

- Freshness chỉ đo 1 boundary (publish). Bonus: thêm boundary ingest.
- Không có LLM-judge — eval thuần keyword matching.
