# Kiến trúc pipeline — Lab Day 10

**Tác giả:** Nguyễn Thái Dương
**Cập nhật:** 2026-06-10

---

## 1. Sơ đồ luồng

```
┌─────────────────────────────────────────────────────────────────────┐
│                         ETL PIPELINE                                │
│                                                                     │
│  data/raw/                                                          │
│  policy_export_dirty.csv                                            │
│        │                                                            │
│        ▼  [INGEST]                                                  │
│  load_raw_csv()          → raw_records logged + run_id assigned     │
│        │                                                            │
│        ▼  [TRANSFORM]                                               │
│  clean_rows()                                                       │
│   ├── Rule 1: allowlist (5 doc_ids hợp lệ)                          │
│   ├── Rule 2: normalize effective_date → ISO YYYY-MM-DD             │
│   ├── Rule 3: strip noise prefix ("Nội dung không rõ ràng:", "!!!") │
│   ├── Rule 4: quarantine HR stale date (< 2026-01-01)               │
│   ├── Rule 5: quarantine HR stale content ("10 ngày phép năm")      │
│   ├── Rule 6: quarantine empty chunk_text                           │
│   ├── Rule 7: quarantine excessive repetition (≥3× ≥20 chars)      │
│   ├── Rule 8: deduplicate by normalized text                        │
│   └── Rule 9: fix refund window 14→7 ngày làm việc                 │
│        │                           │                                │
│        ▼                           ▼                                │
│  cleaned_*.csv              quarantine_*.csv                        │
│  (artifacts/cleaned/)       (artifacts/quarantine/)                 │
│        │                                                            │
│        ▼  [VALIDATE]                                                │
│  run_expectations()                                                 │
│   ├── E1 min_one_row                    [halt]                      │
│   ├── E2 no_empty_doc_id               [halt]                      │
│   ├── E3 refund_no_stale_14d_window    [halt]                      │
│   ├── E4 chunk_min_length_8            [warn]                      │
│   ├── E5 effective_date_iso_yyyy_mm_dd [halt]                      │
│   ├── E6 hr_leave_no_stale_10d_annual  [halt]                      │
│   ├── E7 access_control_sop_present    [halt]  ← NEW               │
│   └── E8 no_stale_hr_2025_marker       [halt]  ← NEW               │
│        │                                                            │
│        ▼  [EMBED]  (nếu expectations PASS)                         │
│  ChromaDB PersistentClient                                          │
│   ├── upsert by chunk_id (idempotent)                               │
│   ├── prune orphan ids (snapshot index)                             │
│   └── collection: day10_kb                                         │
│        │                                                            │
│        ▼  [MANIFEST + FRESHNESS]                                    │
│  manifest_<run_id>.json          ← run_id, counts, timestamps       │
│  (artifacts/manifests/)                                             │
│  check_manifest_freshness()      ← SLA 24h từ latest_exported_at   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

              ▼
       ChromaDB day10_kb
              ▼
    eval_retrieval.py / grading_run.py
    (query top-k → keyword check)
```

---

## 2. Ranh giới trách nhiệm

| Thành phần | Input | Output | Owner nhóm |
|------------|-------|--------|------------|
| Ingest | `data/raw/policy_export_dirty.csv` | List[Dict] rows | Ingestion Owner |
| Transform | raw rows | cleaned rows + quarantine rows | Cleaning Owner |
| Quality | cleaned rows | ExpectationResult list + halt flag | Quality Owner |
| Embed | cleaned CSV + Chroma client | vectors trong `day10_kb` | Embed Owner |
| Monitor | `artifacts/manifests/*.json` | PASS/WARN/FAIL + age_hours | Monitoring Owner |

---

## 3. Idempotency & rerun

Pipeline embed theo chiến lược **upsert + prune**:
- `chunk_id` được tính từ `sha256(doc_id|chunk_text|seq)[:16]` — ổn định giữa các run với cùng data.
- Mỗi lần `run`, pipeline lấy tất cả id hiện có trong collection, xóa các id không còn trong `cleaned_*.csv` lần này (`embed_prune_removed` trong log).
- Kết quả: chạy 2 lần với cùng input → vector count không thay đổi, không phình tài nguyên.

---

## 4. Liên hệ Day 09

Pipeline Day 10 xử lý cùng corpus `data/docs/` với Day 08/09 nhưng qua lớp ETL:
- Day 08/09 embed trực tiếp từ file `.txt`.
- Day 10 embed từ cleaned CSV export → phát hiện và loại bỏ stale/duplicate/corrupt trước khi vào vector store.
- Collection tách biệt (`day10_kb` vs collection của Day 09) để không làm ảnh hưởng agent Day 09.
- Khi Day 10 pipeline chạy thành công, có thể swap collection trong agent Day 09 sang `day10_kb` để dùng data đã clean.

---

## 5. Điểm đo freshness

- **Ingest boundary**: `exported_at` trong từng row CSV — timestamp khi hệ thống nguồn export.
- **Publish boundary**: `run_timestamp` trong manifest — khi pipeline hoàn thành embed.
- Freshness SLA (`FRESHNESS_SLA_HOURS=24`) đo từ `latest_exported_at` trong manifest.
- CSV mẫu có `exported_at` cũ → **FAIL freshness là hành vi đúng** cho data snapshot cũ.

---

## 6. Rủi ro đã biết

- `exported_at` trong raw CSV không phải lúc nào cũng ISO chuẩn (có format `YYYY/MM/DDTHH:MM:SS`) → freshness parse có thể bỏ qua một số rows.
- Dedup theo nội dung text: nếu upstream sửa text nhỏ (whitespace, dấu), chunk cũ sẽ được giữ và chunk mới bị quarantine.
- SentenceTransformer `paraphrase-multilingual-MiniLM-L12-v2` chạy CPU → embed ~100 chunks mất vài giây, chấp nhận được cho lab scale.
