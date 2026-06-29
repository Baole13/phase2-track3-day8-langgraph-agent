# Báo cáo Lab Day 08

## 1. Thông tin sinh viên / nhóm

- Họ và tên: Lê Quốc Bảo
- Ngày: 29/06/2026

## 2. Kiến trúc hệ thống

Lab này triển khai một `StateGraph` bằng LangGraph cho tác vụ xử lý ticket hỗ trợ. Đồ thị bắt đầu từ `intake`, phân loại yêu cầu người dùng bằng LLM thật, sau đó điều hướng vào một trong năm nhánh:

- `simple` -> trả lời trực tiếp
- `tool` -> gọi công cụ giả lập, đánh giá kết quả, rồi trả lời
- `missing_info` -> yêu cầu làm rõ thông tin và kết thúc an toàn
- `risky` -> chuẩn bị hành động, yêu cầu phê duyệt, rồi mới đi vào nhánh công cụ
- `error` -> đi vào vòng lặp retry có chặn và chuyển sang dead-letter khi vượt số lần thử

Tất cả các nhánh đều đi qua `finalize -> END`. Điều này được thiết kế có chủ đích để bảo đảm mọi scenario đều có audit event cuối cùng và giúp việc thu thập metrics ổn định, nhất quán.

Trách nhiệm của từng node được tách như sau:

- `classify_node`: phân loại bằng LLM với structured output
- `tool_node`: mô phỏng hành vi tool và lỗi tạm thời
- `evaluate_node`: quyết định có cần retry dựa trên kết quả tool gần nhất
- `answer_node`: sinh câu trả lời cuối cùng dựa trên ngữ cảnh bằng LLM
- `ask_clarification_node`: fallback an toàn cho truy vấn mơ hồ
- `risky_action_node`: tạo payload cho bước phê duyệt
- `approval_node`: phê duyệt HITL giả lập, có chuẩn bị nhánh interrupt thật
- `retry_or_fallback_node`: tăng số lần thử và ghi nhận lỗi retry
- `dead_letter_node`: fallback cuối cùng khi retry thất bại hoàn toàn
- `finalize_node`: phát audit event kết thúc workflow

## 3. Thiết kế state schema

Các field quan trọng và lựa chọn reducer:

| Field | Reducer | Lý do |
|---|---|---|
| `messages` | append | Lưu trace nhẹ ở mức node |
| `tool_results` | append | Giữ lịch sử tool qua các lần retry |
| `errors` | append | Lưu bằng chứng lỗi cho metrics và báo cáo |
| `events` | append | Phục vụ audit trail và đếm số node đã đi qua |
| `route` | overwrite | Chỉ cần route hiện tại |
| `risk_level` | overwrite | Được suy ra từ route hiện tại |
| `attempt` | overwrite | Biểu diễn trạng thái retry hiện tại |
| `evaluation_result` | overwrite | Một cổng quyết định retry duy nhất |
| `final_answer` | overwrite | Chỉ cần câu trả lời kết thúc mới nhất |
| `pending_question` | overwrite | Câu hỏi làm rõ chỉ có một giá trị hiện hành |
| `proposed_action` | overwrite | Chỉ giữ hành động rủi ro đang chờ xét |
| `approval` | overwrite | Chỉ giữ quyết định phê duyệt gần nhất |

Schema được giữ gọn và hoàn toàn serializable, nên phù hợp với cơ chế persistence của LangGraph và yêu cầu grading của bài lab.

## 4. Kết quả theo scenario

### Trạng thái hiện tại

Tại thời điểm viết báo cáo, phần code cho workflow đã được triển khai xong, nhưng lần chạy metrics cuối cùng bằng LLM thật vẫn chưa hoàn tất trong môi trường này vì Gemini key hiện tại trả về lỗi `API_KEY_INVALID`.

Vì vậy, `outputs/metrics.json` từ lần chạy bằng provider thật chưa được commit. Bảng dưới đây ghi lại hành vi đã được xác minh bằng một local deterministic smoke harness dùng để kiểm tra routing và persistence mà không phụ thuộc API bên ngoài.

| Scenario | Route kỳ vọng | Route quan sát | Thành công | Số retry | Số interrupt |
|---|---|---|---:|---:|---:|
| `S01_simple` | `simple` | `simple` | Có | 0 | 0 |
| `S02_tool` | `tool` | `tool` | Có | 0 | 0 |
| `S03_missing` | `missing_info` | `missing_info` | Có | 0 | 0 |
| `S04_risky` | `risky` | `risky` | Có | 0 | 1 |
| `S05_error` | `error` | `error` | Có | 2 | 0 |
| `S06_delete` | `risky` | `risky` | Có | 0 | 1 |
| `S07_dead_letter` | `error` | `error` | Có | 1 | 0 |

### Tóm tắt metrics từ lần kiểm tra logic cục bộ

| Metric | Giá trị |
|---|---:|
| Tổng số scenario | 7 |
| Tỉ lệ thành công | 100% |
| Tổng số retry quan sát được | 3 |
| Số nhánh approval quan sát được | 2 |
| Số scenario đi vào dead-letter | 1 |

Các con số trên xác minh logic của graph, chưa phải xác minh provider LLM thật. Cần chạy lại quy trình grading sau khi thay Gemini API key hợp lệ.

## 5. Phân tích failure mode

### 1. Lỗi tool hoặc cần retry

Failure mode chính là lỗi tool tạm thời đối với các scenario thuộc route `error`. Hệ thống xử lý bằng cách:

- lưu kết quả tool vào `tool_results`
- đặt `evaluation_result="needs_retry"` khi kết quả gần nhất chứa `ERROR`
- tăng `attempt` ở node retry
- điều hướng sang `dead_letter` khi `attempt >= max_attempts`

Cách làm này ngăn vòng lặp vô hạn và giúp toàn bộ tiến trình lỗi được thể hiện rõ trong cả `errors` lẫn `events`.

### 2. Hành động rủi ro không qua phê duyệt

Các hành động như refund, delete hoặc tác động dữ liệu khách hàng không được phép đi thẳng đến bước thực thi tool. Graph cô lập chúng qua luồng:

```text
classify -> risky_action -> approval -> tool
```

Nếu bị từ chối phê duyệt, graph sẽ chuyển sang nhánh clarification thay vì tiếp tục âm thầm. Điều này giúp đảm bảo an toàn và làm cho quyết định phê duyệt được biểu diễn minh bạch trong state.

### 3. Vấn đề persistence trên đường dẫn Unicode

Trên máy hiện tại, đường dẫn workspace có chứa ký tự không phải ASCII. SQLite có thể phát sinh `disk I/O error` trong bối cảnh này. Để vẫn giữ được persistence, phần cài đặt đã fallback sang file SQLite trong thư mục temp khi đường dẫn resolve ra không an toàn cho ASCII hoặc khi bước khởi tạo WAL thất bại.

Đây là giải pháp thực dụng cho môi trường chạy, không phải thay đổi trong logic nghiệp vụ của graph.

## 6. Bằng chứng về persistence / recovery

Persistence được triển khai thông qua `build_checkpointer("sqlite", database_url=...)`.

Bằng chứng từ lần kiểm tra cục bộ:

- mỗi scenario sử dụng `thread_id = thread-{scenario.id}`
- graph compile được với `SqliteSaver`
- smoke validation cục bộ xác nhận SQLite checkpointer có thể khởi tạo và chạy scenario khi được chuyển sang file temp an toàn

Điều này đáp ứng yêu cầu extension về persistence và cung cấp một checkpoint backend cụ thể ngoài `MemorySaver`.

## 7. Phần mở rộng đã thực hiện

Extension đã hoàn thành:

- SQLite persistence qua `langgraph-checkpoint-sqlite`

Extension đã chuẩn bị một phần:

- real HITL qua `LANGGRAPH_INTERRUPT=true` trong `approval_node`

Chưa triển khai:

- time travel hoặc UI replay state history
- xuất graph diagram
- LLM-as-judge trong `evaluate_node`

## 8. Kế hoạch cải tiến

Nếu có thêm một ngày để hoàn thiện, mình sẽ ưu tiên theo thứ tự sau:

1. Sửa và xác minh đường chạy Gemini thật, sau đó sinh lại `outputs/metrics.json`.
2. Nạp `.env` tường minh ngay từ CLI để local run ít phụ thuộc shell hơn.
3. Thay heuristic trong `evaluate_node` bằng LLM-as-judge với confidence threshold.
4. Bổ sung demo interrupt/resume thật cho nhánh risky approval.
5. Xuất state history hoặc Mermaid graph làm bằng chứng cho báo cáo.

## 9. Checklist xác minh cuối

- [x] Đã thêm các field state cần thiết và nối chúng vào routing
- [x] Đã triển khai toàn bộ node function
- [x] Đã triển khai conditional edge cho graph
- [x] Retry loop có chặn
- [x] Đã có approval path cho risky action
- [x] Đã triển khai SQLite checkpointer
- [x] `ruff check src` pass
- [x] `pytest -q` pass khi smoke test phụ thuộc LLM được skip do chưa có key hợp lệ
- [ ] `make run-scenarios` với Gemini key hợp lệ
- [ ] `make grade-local` trên `outputs/metrics.json` thật
