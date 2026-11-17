# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

## Case: `seeded_regression` C-002@11

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, trace `R-seeded_regression-C-002-s11`, report `reports/eval_seeded_regression.json` (run `E-seeded_regression-20261117-9840`, item E-002 seed 11) |
| Triệu chứng | Lab 8 grader FAIL `status resolved != denied`; `refund_amount_correct` FAIL (ledger 20.000đ, nhãn 0); `db_fact_kept` FAIL. Reply "Dạ, LogiX đã hoàn 20.000đ cho đơn O-202." **khớp ledger**, nên nhìn reply thì không thấy lỗi. Lỗi nằm ở chỗ đáng lẽ không được hoàn. |
| Bước sai đầu tiên | **Event 3** `model_override` `{"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` đúng contract (chỉ tool đọc). Event 2 `investigator` đọc DB đúng: O-202 `delivered`, `delay_days: 2`. Event 3 thay số 2 của DB bằng số 5 khách tự viết trong ticket ("giao trễ 5 ngày"). Từ đó event 4 quote đi qua clause SHIP-LATE-03 (trễ ≥ 3 ngày) thành 20.000đ, approval A-002 còn hiệu lực nên host ghi tiền. Event 4–6 chỉ là hệ quả. |
| Failure mode | **FM-03** ticket_trust (`docs/failure_taxonomy.md`) |
| Đối chứng | `fixed` C-002@11: event 1–2 giống hệt, **không có** `model_override`, event 3 quote `0, no_entitlement`, event 4 reply từ chối; ledger 0, Lab 8 PASS. Khác biệt duy nhất là bước override. |
| Regression test | `src/tests/test_lab9_trace_case.py`: `test_lab9_trace_case_c002_first_wrong_step_is_override` kiểm event 3 là `model_override {"delay_days": 5}`, `DbFactKept` và `RefundAmountCorrect` FAIL trên `seeded_regression`; `test_lab9_trace_case_c002_fixed_keeps_db_fact` PASS trên `fixed`. Đã chạy: cả hai xanh (fail đúng chỗ trên variant lỗi, pass trên `fixed`). Có marker `student`, tên chứa `lab9`, nên job `eval-gate` chạy test này. Ở mức eval set, E-002 mang `FM-03`, và gate chặn qua `refund_amount_correct` + `pass_rate`. |
| Chưa chắc chắn | Trace chỉ cho thấy *agent đã* ghi đè, không cho thấy *vì sao* (MockLLM không có lý do). Trên `swarm` gốc, lỗi này chỉ xuất hiện ở seed 55 (`seed % 5 == 0`), nên với LLM thật tần suất có thể khác hẳn. Trace cũng không cho biết khách có cố tình nói sai số ngày hay không. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai (case này: reply đúng với ledger, nhưng ledger sai với chính sách).
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
