# Báo Cáo — Lab Day 10: Data Pipeline & Data Observability

**Họ và tên:** Nguyễn Thái Dương
**Vai trò:** Cleaning & Quality Owner · Embed Owner · Monitoring Owner
**Ngày nộp:** 2026-06-10
**Repo:** https://github.com/Yangtai2504/Lecture-Day10

---

## 1. Pipeline tổng quan

**Nguồn raw:** `data/raw/policy_export_dirty.csv` — **247 rows**, export từ 5 hệ thống nguồn (policy_refund_v4, sla_p1_2026, it_helpdesk_faq, hr_leave_policy, access_control_sop) cộng với ~12 doc_id không hợp lệ (invalid_doc_*, legacy_catalog_xyz_zzz, security_policy, data_privacy_guideline). Kết quả clean: **35 cleaned**, **212 quarantined**.

**Embedding model:** `paraphrase-multilingual-MiniLM-L12-v2` — model đa ngôn ngữ hiểu semantic tiếng Việt tốt hơn `all-MiniLM-L6-v2` (English-only). Fix root cause: P1 escalation chunk rank đúng top-3 thay vì rank 8 với model cũ.

**Chuỗi lệnh end-to-end:**
```bash
cd day10/lab
python etl_pipeline.py run
python eval_retrieval.py --out artifacts/eval/after_fix.csv
python grading_run.py --out artifacts/eval/grading_run.jsonl
```

**run_id:** Tự động sinh từ UTC timestamp (vd `2026-06-10T12-00Z`); ghi dòng đầu trong `artifacts/logs/run_*.log` và lưu trong `artifacts/manifests/manifest_*.json`.

**Luồng:**
1. `load_raw_csv()` → 247 raw_records
2. `clean_rows()` → cleaned + quarantine (xem bảng metric_impact)
3. `run_expectations()` → E1–E8; halt nếu bất kỳ `halt` fail
4. `cmd_embed_internal()` → upsert vào ChromaDB `day10_kb`; prune id cũ
5. `check_manifest_freshness()` → PASS/WARN/FAIL theo SLA 24h

---

## 2. Cleaning & expectation

**Baseline đã có (6 rules):** allowlist, date normalization, HR stale date, empty text, dedup, refund fix.

**3 rule mới thêm:**

| Rule | Tên | Mô tả |
|------|-----|-------|
| Rule 3 | `strip_noise_prefix` | Loại "Nội dung không rõ ràng: " và "!!!" — artifact của export hệ thống cũ |
| Rule 5 | `stale_hr_annual_leave_content` | Quarantine HR rows có "10 ngày phép năm" dù date >= 2026 |
| Rule 7 | `excessive_text_repetition` | Quarantine chunk lặp lại đoạn ≥20 ký tự 3+ lần |

**2 expectation mới (đều halt):**

| Expectation | Tên | Severity |
|-------------|-----|---------|
| E7 | `access_control_sop_present` | halt |
| E8 | `no_stale_hr_2025_marker` | halt |

### 2a. Bảng metric_impact

| Rule / Expectation mới | Trước (baseline) | Sau / khi inject | Chứng cứ |
|------------------------|------------------|-----------------|----------|
| `stale_hr_annual_leave_content` | HR rows với date ≥ 2026-01-01 nhưng có "10 ngày phép năm" pass qua → E6 FAIL halt | quarantine_records tăng thêm ~8 rows; E6 PASS | `artifacts/logs/run_*.log`: `quarantine[stale_hr_annual_leave_content]` |
| `access_control_sop_present` (E7) | access_control_sop không có trong allowlist → 0 chunks từ nguồn này | Sau fix: 5 chunks từ access_control_sop embed → E7 PASS | `artifacts/eval/grading_run.jsonl`: gq_d10_10 `contains_expected=true` |
| `no_stale_hr_2025_marker` (E8) | inject run: "(bản HR 2025)" lọt qua → E8 FAIL | pipeline chuẩn: E8 PASS | `artifacts/logs/run_inject-bad.log` vs `run_fix-01.log` |
| `strip_noise_prefix` | ~12 rows có prefix "Nội dung không rõ ràng:" → text bị lẫn prefix | Text được clean; một số trở thành duplicate → quarantine_records tăng | `artifacts/quarantine/*.csv`: `reason=duplicate_chunk_text` sau khi strip |
| `excessive_text_repetition` | ~4 rows lặp lại text 3-5 lần (copy-paste artifact) → embed nội dung spam | quarantine_records tăng ~4 | `artifacts/quarantine/*.csv`: `reason=excessive_text_repetition` |

**Rule baseline chính:**
- `unknown_doc_id`: ~110 rows từ invalid_doc_*, legacy_*, security_policy, data_privacy_guideline bị quarantine
- `stale_hr_policy_effective_date`: HR rows có effective_date < `hr_leave_min_effective_date` quarantine (cutoff đọc từ contract — xem mục 2b)
- `refund_no_stale_14d_window` (E3): khi inject `--no-refund-fix`, E3 FAIL halt

### 2b. Rule versioning không hard-code (Distinction evidence — tiêu chí d)

Rule 4 (`stale_hr_policy_effective_date`) **không** dùng giá trị ngày cố định trong code. Cutoff được đọc từ `contracts/data_contract.yaml → policy_versioning.hr_leave_min_effective_date`.

**Cơ chế:**
```python
# transform/cleaning_rules.py — load_hr_min_effective_date()
data = yaml.safe_load(contract_path.read_text())
return data["policy_versioning"]["hr_leave_min_effective_date"]  # "2026-01-01"
```

**Chứng minh inject làm đổi quyết định clean:**

| Contract cutoff | cleaned_records | quarantine_records | HR chunk trong KB |
|-----------------|----------------|--------------------|-------------------|
| `"2026-01-01"` (production) | 35 | 212 | Có (6 chunk HR 2026) |
| `"2027-01-01"` (inject) | **29** | **218** | **Không** — HR 2026 quarantined |

Inject run: `python etl_pipeline.py run --run-id inject-hr-cutoff --skip-validate`
Artifact: `artifacts/quarantine/quarantine_inject-hr-cutoff.csv` — 218 rows, có `reason=stale_hr_policy_effective_date, hr_min_date_used=2027-01-01`

Với cutoff inject, query "12 ngày phép năm" trả về kết quả từ policy_refund_v4 (sai hoàn toàn) — thay đổi contract một dòng làm hỏng toàn bộ HR retrieval. Lý do: thay đổi ngưỡng version trong contract phải được test bằng inject trước khi triển khai thật.

**Ví dụ expectation fail (Sprint 3 inject):**
```
expectation[hr_leave_no_stale_10d_annual] FAIL (halt) :: violations=2
expectation[no_stale_hr_2025_marker] FAIL (halt) :: stale_hr_2025_chunks=2
WARN: expectation failed but --skip-validate → tiếp tục embed (chỉ dùng cho demo Sprint 3).
```

---

## 3. Before / after ảnh hưởng retrieval

**Kịch bản inject (Sprint 3):**
```bash
python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate
python eval_retrieval.py --out artifacts/eval/after_inject_bad.csv
```
Cờ `--no-refund-fix` tắt rule fix refund (giữ nguyên "14 ngày làm việc"), `--skip-validate` bypass halt để embed data corrupt.

**Kết quả định lượng:**

| Question | inject-bad (before) | fix-01 (after) |
|----------|--------------------|--------------------|
| gq_d10_01 (refund 7 ngày) | contains_expected=no, hits_forbidden=yes | contains_expected=yes, hits_forbidden=no |
| gq_d10_09 (HR 12 ngày) | contains_expected=no, hits_forbidden=yes | contains_expected=yes, hits_forbidden=no |
| gq_d10_10 (access control) | contains_expected=no | contains_expected=yes |

File đối chiếu: `artifacts/eval/after_inject_bad.csv` vs `artifacts/eval/after_fix.csv`.

---

## 4. Freshness & monitoring

SLA chọn: `FRESHNESS_SLA_HOURS=24` (mặc định từ `.env`).

CSV mẫu có `exported_at` từ tháng 4/2026 → age_hours > 24 → **freshness_check=FAIL là hành vi đúng** cho data snapshot cũ. Đây không phải lỗi pipeline mà là đặc tính của data mẫu lab.

Interpretation trong context thực:
- **PASS**: data được export trong 24h qua — pipeline có thể phục vụ agent với data mới nhất
- **WARN**: không có timestamp trong manifest — cần kiểm tra upstream export
- **FAIL**: data quá cũ — cần rerun pipeline với export mới hoặc nới SLA nếu batch ít thường xuyên hơn

---

## 5. Liên hệ Day 09

Pipeline Day 10 xử lý cùng corpus `data/docs/` nhưng qua lớp ETL trước khi embed. Collection `day10_kb` tách với collection Day 09 để không ảnh hưởng agent đang chạy. Khi cần, có thể swap `CHROMA_COLLECTION=day10_kb` trong agent Day 09 để dùng data đã clean.

---

## 6. Rủi ro còn lại & việc chưa làm

- Freshness chỉ đo 1 boundary (publish). Đo thêm boundary ingest (`exported_at`) sẽ cho biết độ trễ end-to-end.
- Chưa có pydantic schema validation — expectation suite chỉ check logic, không check type safety.
- Dedup dựa trên text đã normalize: nếu upstream thay đổi ký tự whitespace nhỏ, chunk cũ vẫn được giữ và chunk mới bị quarantine — có thể gây stale embed.
