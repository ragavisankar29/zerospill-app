# ZeroSpill DWDM mapping

## Source
ZEROSPILL_cleaned.csv — 8,000 rows, 26 source columns.

## ETL
- Extract: read the CSV and validate required source columns.
- Transform: parse Date and derive Year, Month, Month_Name, Day, Weekday, Consumption_Rate, Surplus_Rate, Waste_Rate, Surplus_Band, Demand_Band, Shelf_Life_Band and Guest_Variance.
- Validate: missing cells, duplicate rows, invalid dates, negative quantities, unique events/food items/venues.
- Load: build Fact_Food_Surplus and dimension tables in SQLite.

## Star schema
Fact_Food_Surplus is connected to Dim_Event, Dim_Food, Dim_Date, Dim_Venue, Dim_Business, Dim_Weather and Dim_Inventory.

## Snowflake schema
The project also materializes normalized tables for food category, event type and month.

## OLAP
The 3D cube API groups warehouse rows by three selected dimensions and calculates count, sum and average for the selected measure.

## Pattern mining
The pattern page computes categorical pair associations and reports support, confidence and lift. It is deliberately domain-specific to food surplus rather than copying the FraudShield fraud rules.

## Location feature
The source CSV has no latitude/longitude or recipient-location fields. Therefore, pickup/distribution locations are stored in a separate application table and are labeled demo locations. Replace them with your professor-approved locations before final submission if required.
