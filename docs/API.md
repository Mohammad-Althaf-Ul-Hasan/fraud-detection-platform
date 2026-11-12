# Fraud Detection Platform — API Reference

Base URL: `http://127.0.0.1:8000`

## Scoring

### `POST /predict`
Score a single transaction synchronously.
```json
{
  "txn_id": "12345", "step": 372, "type": "CASH_OUT",
  "amount": 381003.49, "nameOrig": "C398621182",
  "oldbalanceOrg": 9422.0, "newbalanceOrig": 0.0,
  "nameDest": "C1011451177",
  "oldbalanceDest": 986468.77, "newbalanceDest": 1367472.26
}