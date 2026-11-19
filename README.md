# ZeroSpill

A functional DWDM web application for banquet food surplus management, redistribution, OLAP and pattern mining.

## Stack
- Flask + SQLite
- Pandas / NumPy for ETL and warehouse analytics
- Plotly.js for charts and 3D OLAP visualization
- Vanilla HTML/CSS/JS

## Run
```bash
python -m venv .venv
.venv\\Scripts\\activate       # Windows
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000

## Demo authentication
If SMTP is not configured, the app runs in demo OTP mode and shows the OTP on the verification page. For a real email OTP, copy `.env.example` to `.env`, install/use your preferred environment-variable loader or set the variables in Windows, and configure a Gmail App Password.

## DWDM flow
ZEROSPILL_cleaned.csv → Extract → Transform → Validate → Load → Star Schema → Snowflake Schema → OLAP Cube → Pattern Mining → Insights

## Important
The source CSV contains 8,000 rows and 26 columns. It does not contain latitude/longitude or recipient-location fields. The app therefore keeps a separate application `locations` table for pickup/distribution locations and clearly labels demo locations instead of pretending those coordinates came from the CSV.
