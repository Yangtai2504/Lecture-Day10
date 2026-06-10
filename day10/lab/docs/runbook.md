# Runbook — Lab Day 10 (incident tối giản)

---

## Symptom

Agent hoặc RAG system trả lời sai một trong các trường hợp sau:
- Trả lời "14 ngày" thay vì "7 ngày" cho câu hỏi hoàn tiền
- Trả lời "10 ngày phép năm" thay vì "12 ngày" cho HR policy 2026
- Không tìm được thông tin Level 4 Admin Access (IT Manager/CISO)
- Pipeline log in `PIPELINE_HALT` thay vì `PIPELINE_OK`

---

## Detection

| Signal | Nguồn | Threshold |
|--------|-------|-----------|
| `expectation[...] FAIL (halt)` | `artifacts/logs/run_*.log` | Bất kỳ 1 halt fail |
| `hits_forbidden=yes` | `artifacts/eval/grading_run.jsonl` | Bất kỳ 1 dòng |
| `contains_expected=no` | `artifacts/eval/grading_run.jsonl` | Bất kỳ 1 dòng |
| `freshness_check=FAIL` | manifest hoặc log | age_hours > SLA |
| `quarantine_records` tăng đột biến | manifest | > 80% raw_records |

---

## Diagnosis

| Bước | Việc làm | Kết quả mong đợi |
|------|----------|------------------|
| 1 | Mở `artifacts/manifests/manifest_<run_id>.json` | Kiểm tra `cleaned_records`, `quarantine_records`, `skipped_validate` |
| 2 | Đọc `artifacts/logs/run_<run_id>.log` | Tìm dòng `expectation[...] FAIL` hoặc `PIPELINE_HALT` |
| 3 | Mở `artifacts/quarantine/quarantine_<run_id>.csv` | Xem `reason` field — nguồn nào bị quarantine nhiều nhất |
| 4 | Chạy `python eval_retrieval.py --out artifacts/eval/debug_eval.csv` | Cột `hits_forbidden` và `contains_expected` |
| 5 | Kiểm tra `transform/cleaning_rules.py` `ALLOWED_DOC_IDS` | Đủ 5 doc_ids? |
| 6 | Kiểm tra raw CSV: `doc_id` trong CSV vs allowlist | Có nguồn mới nào bị thiếu? |

---

## Mitigation

**Trường hợp pipeline HALT do expectation:**
```bash
# Xem log để biết expectation nào fail
cat artifacts/logs/run_<run_id>.log | grep FAIL

# Sửa cleaning_rules.py hoặc data, rồi rerun
python etl_pipeline.py run
```

**Trường hợp refund window sai (14 ngày):**
- Kiểm tra `--no-refund-fix` không bị bật trong production
- Rerun: `python etl_pipeline.py run` (apply_refund_window_fix=True mặc định)

**Trường hợp HR stale content:**
- Kiểm tra rule `stale_hr_annual_leave_content` trong `cleaning_rules.py`
- Nếu upstream vẫn export bản 2025: escalate lên HR Data Owner

**Trường hợp access_control_sop thiếu:**
- Kiểm tra `access_control_sop` có trong `ALLOWED_DOC_IDS`
- Rerun pipeline

**Trường hợp freshness FAIL:**
- Nếu data mẫu cũ (> 24h): chấp nhận FAIL, ghi vào runbook SLA áp cho "data snapshot"
- Hoặc update `FRESHNESS_SLA_HOURS` trong `.env` nếu SLA thay đổi

---

## Prevention

1. **Expectation suite**: mọi thay đổi allowlist phải đi kèm expectation verify presence.
2. **Contract versioning**: cập nhật `contracts/data_contract.yaml` khi thêm nguồn mới.
3. **Freshness alert**: set `alert_channel` trong contract để nhận cảnh báo khi freshness FAIL.
4. **Dedup audit**: monitor `quarantine_records[duplicate_chunk_text]` — tăng đột biến là dấu hiệu upstream re-export bị lỗi.
5. **Before/after eval**: chạy `grading_run.py` trước và sau mỗi thay đổi rule để phát hiện regression.
