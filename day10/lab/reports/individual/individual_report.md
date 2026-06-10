# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Nguyễn Thái Dương
**Vai trò:** Cleaning & Quality Owner + Embed Owner
**Ngày nộp:** 2026-06-10
**Độ dài:** ~550 từ

---

## 1. Tôi phụ trách phần nào?

**File / module:**

- `transform/cleaning_rules.py` — toàn bộ logic cleaning: allowlist, date normalization, strip noise, HR stale filter, repetition filter, dedup, refund fix
- `quality/expectations.py` — toàn bộ expectation suite (E1–E8)
- `etl_pipeline.py` — embed logic (upsert + prune), manifest generation
- `.env` và `contracts/data_contract.yaml` — cấu hình pipeline

**Kết nối với thành viên khác:**

Pipeline output (`cleaned_*.csv`, `artifacts/manifests/`) được dùng bởi phần monitoring và docs. Grading JSONL được verify bởi toàn nhóm.

**Bằng chứng:**

- Thêm `access_control_sop` vào `ALLOWED_DOC_IDS` (dòng 20 `cleaning_rules.py`)
- 3 rule mới: `_strip_noise_prefix` (Rule 3), `stale_hr_annual_leave_content` (Rule 5), `_has_excessive_repetition` (Rule 7)
- 2 expectation mới: `access_control_sop_present` (E7, halt), `no_stale_hr_2025_marker` (E8, halt)

---

## 2. Một quyết định kỹ thuật

**Chọn `halt` cho E7 (`access_control_sop_present`) thay vì `warn`.**

Khi thiết kế expectation E7, tôi có hai lựa chọn: `warn` (pipeline vẫn tiếp tục embed dù không có access_control_sop) hoặc `halt` (dừng pipeline nếu thiếu nguồn này).

Tôi chọn `halt` vì: nếu `access_control_sop` vắng mặt trong cleaned data, bất kỳ câu hỏi nào về quyền truy cập Level 4 (IT Manager/CISO) sẽ không được trả lời đúng — đây là lỗi nghiêm trọng với impact trực tiếp lên người dùng. Một `warn` sẽ cho phép pipeline embed data thiếu mà không có signal rõ ràng.

Nếu đây là production, tôi sẽ kết hợp `halt` với alert để team data biết nguồn nào bị thiếu, thay vì âm thầm cho qua.

---

## 3. Một lỗi / anomaly đã xử lý

**Triệu chứng:** Pipeline halt với `hr_leave_no_stale_10d_annual FAIL (halt)` dù baseline đã có rule quarantine HR rows có `effective_date < 2026-01-01`.

**Phân tích:** Đọc raw CSV, tìm thấy các rows như:
```
row 9:  hr_leave_policy, "...10 ngày phép năm (bản HR 2025).", 2026-01-09
row 22: hr_leave_policy, "...10 ngày phép năm (bản HR 2025).", 2026-01-04
row 58: hr_leave_policy, "...10 ngày phép năm (bản HR 2025).", 2026-02-14
```

Các rows này có `effective_date >= 2026-01-01` nên thoát qua Rule 4 (date filter), nhưng nội dung vẫn là bản HR 2025 cũ. Expectation E6 phát hiện ra và halt.

**Fix:** Thêm Rule 5 — quarantine bất kỳ `hr_leave_policy` row nào có text chứa `"10 ngày phép năm"`, bất kể effective_date. Sau fix: tất cả HR stale rows bị quarantine, E6 và E8 đều PASS. Cleaned data chỉ giữ bản 2026 (`12 ngày phép năm`, `15 ngày`, `18 ngày`, v.v.).

---

## 4. Bằng chứng trước / sau

**run_id inject-bad** (Sprint 3 — `--no-refund-fix --skip-validate`):
```
question_id,contains_expected,hits_forbidden,top1_doc_id
q_refund_window,yes,yes,policy_refund_v4  ← top-1: "14 ngày làm việc"
```
Expectation E3 FAIL: `refund_no_stale_14d_window violations=1`

**run_id fix-01** (pipeline chuẩn, tất cả E1-E8 PASS):
```
question_id,contains_expected,hits_forbidden,top1_doc_id
q_refund_window,yes,no,policy_refund_v4   ← top-1: "7 ngày làm việc"
```

Delta: `hits_forbidden` từ `yes` → `no`; `embed_prune_removed=1` (xóa 1 vector stale từ inject run). Grading: 10/10 câu PASS.

---

## 5. Cải tiến tiếp theo

Nếu có thêm 2 giờ, tôi sẽ thêm **pydantic schema validation** trên cleaned rows (validate type + length + date range) trước bước embed, thay vì chỉ dùng custom expectation. Pydantic cho phép validate toàn bộ schema với một model duy nhất, error message rõ ràng hơn, và dễ mở rộng khi schema thay đổi. Hiện tại E5 chỉ check regex date format — một pydantic model sẽ check đồng thời tất cả fields.
