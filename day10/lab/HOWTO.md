# HOWTO — Lab Day 10: End-to-End Guide

## 1. Setup (chạy 1 lần)

```bash
cd "c:/VinAI/Lab coding/Lecture-Day10/day10/lab"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

---

## 2. Chạy pipeline (khi data thay đổi)

```bash
python etl_pipeline.py run
```

**Làm gì:** đọc `data/raw/policy_export_dirty.csv` → clean → validate 8 expectations → embed vào ChromaDB.

**Kết quả lưu vào:**

| File | Nội dung |
|------|----------|
| `artifacts/logs/run_<run-id>.log` | Toàn bộ output: số records, expectation results, embed count |
| `artifacts/cleaned/cleaned_<run-id>.csv` | 35 rows sạch sau 9 rules |
| `artifacts/quarantine/quarantine_<run-id>.csv` | 212 rows bị loại + cột `reason` |
| `artifacts/manifests/manifest_<run-id>.json` | Snapshot run: timestamp, record counts |
| `chroma_db/` | Vector store — 35 vectors được upsert |

**Pipeline HALT** nếu bất kỳ expectation `halt` nào fail — đọc log để tìm nguyên nhân.

---

## 3. Grading (khi giảng viên gửi câu hỏi)

```bash
python grading_run.py --questions data/grading_questions.json --out artifacts/eval/grading_run.jsonl
```

Thay `data/grading_questions.json` bằng file giảng viên gửi nếu khác.

**Kết quả lưu vào:** `artifacts/eval/grading_run.jsonl` — 10 dòng JSON, mỗi dòng 1 câu.

Xem nhanh kết quả:
```bash
python -c "
import json; from pathlib import Path
for l in Path('artifacts/eval/grading_run.jsonl').read_text('utf-8').splitlines():
    r=json.loads(l)
    ok=r['contains_expected'] and not r['hits_forbidden']
    print('PASS' if ok else 'FAIL', r['id'], '|', r['top1_doc_id'])
"
```

**PASS điều kiện:** `contains_expected=true` và `hits_forbidden=false` cho tất cả 10 câu.

---

## 4. Tự kiểm retrieval (21 câu — không nộp)

```bash
python eval_retrieval.py --out artifacts/eval/after_fix.csv
```

**Kết quả lưu vào:** `artifacts/eval/after_fix.csv` — để debug, không phải file grading.

---

## 5. Những gì đã làm trong lab này

### Pipeline baseline bị thiếu / sai — đã fix:

| Vấn đề | Fix | File |
|--------|-----|------|
| `access_control_sop` không có trong allowlist → gq_d10_10 fail | Thêm vào `ALLOWED_DOC_IDS` | `transform/cleaning_rules.py:20` |
| HR rows có `effective_date >= 2026` nhưng nội dung vẫn là bản 2025 ("10 ngày phép năm") | Rule 5: quarantine theo nội dung, không chỉ theo ngày | `cleaning_rules.py:153` |
| Prefix lồng nhau `"Nội dung không rõ ràng: !!!..."` — strip 1 lần không đủ | `_strip_noise_prefix` loop cho đến khi text ổn định | `cleaning_rules.py:69` |
| `all-MiniLM-L6-v2` (English-only) — P1 escalation chunk rank 8, P2 chunk rank 1 | Đổi sang `paraphrase-multilingual-MiniLM-L12-v2` | `.env` |
| HR cutoff `"2026-01-01"` hard-code trong Python | `load_hr_min_effective_date()` đọc từ `contracts/data_contract.yaml` | `cleaning_rules.py:16` |

### 3 rule mới thêm (yêu cầu ≥3):

| Rule | Function | Tác động |
|------|----------|----------|
| Rule 3 | `_strip_noise_prefix` | Loại prefix "Nội dung không rõ ràng:" và "!!!" |
| Rule 5 | `stale_hr_annual_leave_content` | Quarantine HR có "10 ngày phép năm" bất kể ngày |
| Rule 7 | `_has_excessive_repetition` | Quarantine chunk lặp lại đoạn ≥20 ký tự 3+ lần |

### 2 expectation mới thêm (yêu cầu ≥2):

| Expectation | Severity | Kiểm tra gì |
|-------------|----------|-------------|
| E7 `access_control_sop_present` | **halt** | Phải có ≥1 chunk từ access_control_sop |
| E8 `no_stale_hr_2025_marker` | **halt** | Không có "(bản HR 2025)" trong cleaned data |

### Distinction evidence (tiêu chí d):

Rule 4 đọc `hr_leave_min_effective_date` từ `contracts/data_contract.yaml` thay vì hard-code. Chứng minh: đổi contract thành `"2027-01-01"` → `cleaned_records` 35 → 29 (run-id `inject-hr-cutoff`, artifact: `artifacts/quarantine/quarantine_inject-hr-cutoff.csv`).

---

## 6. Cấu trúc artifact theo run

```
artifacts/
├── logs/
│   ├── run_fix-03.log          ← run production chính
│   └── run_inject-bad.log      ← run inject (bằng chứng before)
├── manifests/
│   ├── manifest_fix-03.json
│   └── manifest_inject-bad.json
├── cleaned/
│   └── cleaned_fix-03.csv      ← 35 rows
├── quarantine/
│   ├── quarantine_fix-03.csv   ← 212 rows + reason
│   └── quarantine_inject-hr-cutoff.csv  ← Distinction evidence
└── eval/
    ├── grading_run.jsonl        ← FILE NỘP CHO GIẢNG VIÊN (10 câu)
    ├── after_fix.csv            ← 21 câu tự kiểm (sau fix)
    └── after_inject_bad.csv     ← 21 câu tự kiểm (trước fix — bằng chứng before)
```

---

## 7. Key config

| Config | Giá trị | File |
|--------|---------|------|
| Embedding model | `paraphrase-multilingual-MiniLM-L12-v2` | `.env` |
| ChromaDB path | `./chroma_db` | `.env` |
| Collection name | `day10_kb` | `.env` |
| Freshness SLA | 24 giờ | `.env` |
| HR cutoff | `"2026-01-01"` | `contracts/data_contract.yaml` |

---

## 8. Kết quả cuối

```
raw_records   = 247
cleaned       = 35
quarantine    = 212
expectations  = 8/8 PASS (E1–E8)
grading       = 10/10 PASS (gq_d10_01 – gq_d10_10)
top_k         = 5
```
