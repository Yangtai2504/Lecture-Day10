# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Nguyễn Thái Dương
**Email:** kienvbhpgamail@gmail.com
**Vai trò:** Toàn bộ pipeline (bài làm cá nhân)
**Ngày nộp:** 2026-06-10

---

## 1. Phần phụ trách

Bài làm cá nhân — tôi sở hữu toàn bộ codebase.

| File / Module | Function / Rule cụ thể |
|---------------|------------------------|
| `transform/cleaning_rules.py` | `load_hr_min_effective_date()`, `_strip_noise_prefix()` (loop), `_has_excessive_repetition()`, Rule 3/5/7 mới, Rule 4 contract-driven |
| `quality/expectations.py` | E7 `access_control_sop_present` (halt), E8 `no_stale_hr_2025_marker` (halt) |
| `etl_pipeline.py` | embed upsert + prune idempotent, manifest generation |
| `contracts/data_contract.yaml` | `policy_versioning.hr_leave_min_effective_date` — nguồn sự thật cho Rule 4 |
| `.env` | `EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2` |

**Bằng chứng:** commit `f8568c2` (rule versioning), commit `4e394b5` (multilingual model + noise loop fix). Run IDs chính: `fix-03`, `fix-04`, `inject-hr-cutoff`.

---

## 2. Một quyết định kỹ thuật: rule versioning đọc từ contract

**Vấn đề:** Rule 4 (`stale_hr_policy_effective_date`) ban đầu hard-code chuỗi `"2026-01-01"` trong Python. Khi HR Team cập nhật policy, người vận hành phải sửa code → commit → deploy, dễ bỏ sót và không audit được.

**Quyết định:** Đọc cutoff từ `contracts/data_contract.yaml` tại runtime:

```python
def load_hr_min_effective_date(contract_path=_CONTRACT_PATH) -> str:
    data = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    return data["policy_versioning"]["hr_leave_min_effective_date"]
```

Contract đã có sẵn field `hr_leave_min_effective_date: "2026-01-01"` — tôi nối code vào nguồn đó. Tradeoff: thêm YAML parse lúc runtime; nếu contract bị xóa, pipeline fallback về default thay vì crash — chấp nhận vì pipeline vẫn cần chạy được trong môi trường thiếu file (CI, test).

**Bằng chứng inject:** Đổi contract cutoff `"2026-01-01"` → `"2027-01-01"`, chạy `run-id inject-hr-cutoff`: `cleaned_records` 35 → 29 (6 HR chunk 2026 bị quarantine thêm), `quarantine_records` 212 → 218. File `artifacts/quarantine/quarantine_inject-hr-cutoff.csv` ghi `hr_min_date_used=2027-01-01` trên mỗi dòng bị loại.

---

## 3. Một sự cố / anomaly đã xử lý

**Triệu chứng:** Sau khi thêm Rule 3 (`_strip_noise_prefix`), query P1 escalation vẫn trả về chunk bẩn `"!!!Ticket P1 có SLA phản hồi ban đầu 15 phút..."` ở rank #2, đẩy chunk đúng (`"Escalation P1: ... 10 phút"`) xuống rank 9 — `gq_d10_06` fail với top-k=5.

**Root cause:** Hàm `_strip_noise_prefix` chỉ gọi `re.sub` một lần. Row 56 trong raw CSV có prefix lồng nhau `"Nội dung không rõ ràng: !!!Ticket P1..."`: sau một lần strip còn `"!!!Ticket P1..."`, dedup coi đây là text khác với bản sạch → PASS qua dedup → được embed vào ChromaDB, chiếm slot rank 2.

**Fix:** Loop cho đến khi text không đổi:

```python
def _strip_noise_prefix(text: str) -> str:
    prev = None
    while prev != text:
        prev = text
        text = _NOISE_PREFIX.sub("", text).strip()
    return text
```

**Sau fix (`run-id fix-02`):** `cleaned_records` 36 → 35 (chunk bẩn nay là duplicate → quarantine), `embed_prune_removed=29`. Chunk `"!!!Ticket P1..."` biến mất khỏi KB.

---

## 4. Bằng chứng trước / sau

| Giai đoạn | cleaned | quarantine | gq_d10_06 (`10 phút`) | gq_d10_09 (`12 ngày`) |
|-----------|---------|------------|----------------------|----------------------|
| inject-bad (before) | 36 | 211 | contains=yes, forbidden=no | contains=no, **forbidden=yes** |
| fix-02 + English model | 35 | 212 | **FAIL** — rank 8 với top-k=5 | PASS |
| **fix-03** (multilingual) | 35 | 212 | **PASS** — rank 3 với top-k=5 | PASS |

`all-MiniLM-L6-v2` (English-only) không phân biệt ngữ nghĩa P1 vs P2 tiếng Việt: chunk P2 (`"Escalation sau 90 phút không phản hồi"`) luôn rank cao hơn P1. Switching sang `paraphrase-multilingual-MiniLM-L12-v2` đưa P1 escalation lên rank 3.

Kết quả cuối: `artifacts/eval/grading_run.jsonl` — **10/10 PASS**, top-k=5, không workaround.

---

## 5. Cải tiến nếu có thêm 2 giờ

Tôi sẽ thêm **pydantic schema validation** trên cleaned rows trước bước embed. Hiện tại các expectation E1–E8 chỉ check logic nghiệp vụ; một pydantic `ChunkRecord` model sẽ validate đồng thời type, min_length, date format, và required fields trong một lần — error message rõ ràng và dễ mở rộng khi schema thay đổi. Điều này cũng đáp ứng Bonus +2 (pydantic validate thật) nếu được implement đầy đủ.
