from pathlib import Path
import sqlite3, json, math
import pandas as pd
import numpy as np

BASE = Path(__file__).resolve().parent
CSV_PATH = BASE / 'data' / 'ZEROSPILL_cleaned.csv'
DB_PATH = BASE / 'zerospill.db'

SOURCE_COLUMNS = [
    'Event_ID','Event_Type','Venue_ID','Expected_Guests','Actual_Guests','Food_Item',
    'Quantity_Prepared','Quantity_Consumed','Surplus_Quantity','Surplus_Disposition',
    'Inventory_ID','Date','Business_Type','Food_Category','Purchase_Quantity','Units_Sold',
    'Remaining_Stock','Shelf_Life_Days','Storage_Temperature','Daily_Demand','Promotion',
    'Weather','Waste_Quantity','Waste_Reason','Donation_Made','Waste_Level'
]


def load_source():
    df = pd.read_csv(CSV_PATH)
    missing = [c for c in SOURCE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f'Missing source columns: {missing}')
    return df


def transform(df):
    out = df.copy()
    out['Date'] = pd.to_datetime(out['Date'], dayfirst=True, errors='coerce')
    out['Year'] = out['Date'].dt.year
    out['Month'] = out['Date'].dt.month
    out['Month_Name'] = out['Date'].dt.strftime('%B')
    out['Day'] = out['Date'].dt.day
    out['Weekday'] = out['Date'].dt.day_name()
    out['Consumption_Rate'] = np.where(out['Quantity_Prepared'] > 0, out['Quantity_Consumed'] / out['Quantity_Prepared'] * 100, 0).round(2)
    out['Surplus_Rate'] = np.where(out['Quantity_Prepared'] > 0, out['Surplus_Quantity'] / out['Quantity_Prepared'] * 100, 0).round(2)
    out['Waste_Rate'] = np.where(out['Quantity_Prepared'] > 0, out['Waste_Quantity'] / out['Quantity_Prepared'] * 100, 0).round(2)
    out['Surplus_Band'] = pd.cut(out['Surplus_Quantity'], [-1, 10, 30, 60, np.inf], labels=['Low','Medium','High','Very High'])
    out['Demand_Band'] = pd.qcut(out['Daily_Demand'].rank(method='first'), 4, labels=['Low','Medium','High','Very High'])
    out['Shelf_Life_Band'] = pd.cut(out['Shelf_Life_Days'], [-1,2,4,7,np.inf], labels=['Very Short','Short','Moderate','Long'])
    out['Guest_Variance'] = out['Actual_Guests'] - out['Expected_Guests']
    return out


def validate(df):
    checks = {
        'rows': int(len(df)),
        'columns': int(len(df.columns)),
        'missing_cells': int(df.isna().sum().sum()),
        'duplicate_rows': int(df.duplicated().sum()),
        'invalid_dates': int(df['Date'].isna().sum()),
        'negative_quantities': int((df[['Quantity_Prepared','Quantity_Consumed','Surplus_Quantity','Waste_Quantity']] < 0).sum().sum()),
        'unique_events': int(df['Event_ID'].nunique()),
        'unique_food_items': int(df['Food_Item'].nunique()),
        'unique_venues': int(df['Venue_ID'].nunique()),
    }
    return checks


def build_warehouse():
    src = load_source()
    t = transform(src)
    checks = validate(t)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript('''
    DROP TABLE IF EXISTS Fact_Food_Surplus;
    DROP TABLE IF EXISTS Dim_Event;
    DROP TABLE IF EXISTS Dim_Food;
    DROP TABLE IF EXISTS Dim_Date;
    DROP TABLE IF EXISTS Dim_Venue;
    DROP TABLE IF EXISTS Dim_Business;
    DROP TABLE IF EXISTS Dim_Weather;
    DROP TABLE IF EXISTS Dim_Inventory;
    DROP TABLE IF EXISTS Dim_Food_Category;
    DROP TABLE IF EXISTS Dim_Event_Type;
    DROP TABLE IF EXISTS Dim_Month;
    DROP TABLE IF EXISTS Dim_Venue_Type;
    ''')
    # Star dimensions
    events = t[['Event_ID','Event_Type','Expected_Guests','Actual_Guests']].drop_duplicates('Event_ID').copy(); events.insert(0,'Event_Key',range(1,len(events)+1))
    foods = t[['Food_Item','Food_Category']].drop_duplicates().copy(); foods.insert(0,'Food_Key',range(1,len(foods)+1))
    dates = t[['Date','Year','Month','Month_Name','Day','Weekday']].drop_duplicates('Date').sort_values('Date').copy(); dates.insert(0,'Date_Key',range(1,len(dates)+1))
    venues = t[['Venue_ID']].drop_duplicates().copy(); venues.insert(0,'Venue_Key',range(1,len(venues)+1))
    biz = t[['Business_Type']].drop_duplicates().copy(); biz.insert(0,'Business_Key',range(1,len(biz)+1))
    weather = t[['Weather','Storage_Temperature','Promotion']].drop_duplicates().copy(); weather.insert(0,'Weather_Key',range(1,len(weather)+1))
    inv = t[['Inventory_ID','Shelf_Life_Days']].drop_duplicates('Inventory_ID').copy(); inv.insert(0,'Inventory_Key',range(1,len(inv)+1))
    # Fact
    fact = t.merge(events, on=['Event_ID','Event_Type','Expected_Guests','Actual_Guests'], how='left') \
            .merge(foods, on=['Food_Item','Food_Category'], how='left') \
            .merge(dates, on=['Date','Year','Month','Month_Name','Day','Weekday'], how='left') \
            .merge(venues, on='Venue_ID', how='left') \
            .merge(biz, on='Business_Type', how='left') \
            .merge(weather, on=['Weather','Storage_Temperature','Promotion'], how='left') \
            .merge(inv, on=['Inventory_ID','Shelf_Life_Days'], how='left')
    fact = fact[['Event_ID','Food_Key','Date_Key','Venue_Key','Business_Key','Weather_Key','Inventory_Key',
                 'Quantity_Prepared','Quantity_Consumed','Surplus_Quantity','Waste_Quantity','Purchase_Quantity',
                 'Units_Sold','Remaining_Stock','Daily_Demand','Consumption_Rate','Surplus_Rate','Waste_Rate',
                 'Surplus_Disposition','Waste_Reason','Donation_Made','Waste_Level','Surplus_Band','Demand_Band','Shelf_Life_Band']]
    # Write warehouse tables
    events.to_sql('Dim_Event', con, index=False)
    foods.to_sql('Dim_Food', con, index=False)
    dates.to_sql('Dim_Date', con, index=False)
    venues.to_sql('Dim_Venue', con, index=False)
    biz.to_sql('Dim_Business', con, index=False)
    weather.to_sql('Dim_Weather', con, index=False)
    inv.to_sql('Dim_Inventory', con, index=False)
    fact.to_sql('Fact_Food_Surplus', con, index=False)
    # Snowflake normalization tables
    pd.DataFrame({'Category_Key':range(1,t.Food_Category.nunique()+1),'Food_Category':sorted(t.Food_Category.dropna().unique())}).to_sql('Dim_Food_Category', con, index=False)
    pd.DataFrame({'Event_Type_Key':range(1,t.Event_Type.nunique()+1),'Event_Type':sorted(t.Event_Type.dropna().unique())}).to_sql('Dim_Event_Type', con, index=False)
    pd.DataFrame({'Month_Key':range(1,t.Month.nunique()+1),'Month':sorted(t.Month.dropna().astype(int).unique()),'Month_Name':[pd.Timestamp(2000,m,1).strftime('%B') for m in sorted(t.Month.dropna().astype(int).unique())]}).to_sql('Dim_Month', con, index=False)
    con.commit(); con.close()
    return checks


def cube(dim1, dim2, dim3, measure='Surplus_Quantity'):
    con = sqlite3.connect(DB_PATH)
    q = '''SELECT f.*, d.Food_Item, d.Food_Category, e.Event_Type, v.Venue_ID, b.Business_Type,
                  dt.Date, dt.Year, dt.Month_Name, w.Weather
           FROM Fact_Food_Surplus f
           JOIN Dim_Food d ON f.Food_Key=d.Food_Key
           JOIN Dim_Event e ON f.Event_ID=e.Event_ID
           JOIN Dim_Venue v ON f.Venue_Key=v.Venue_Key
           JOIN Dim_Business b ON f.Business_Key=b.Business_Key
           JOIN Dim_Date dt ON f.Date_Key=dt.Date_Key
           JOIN Dim_Weather w ON f.Weather_Key=w.Weather_Key'''
    df = pd.read_sql_query(q, con); con.close()
    allowed = {
        'Food Category':'Food_Category','Food Item':'Food_Item','Event Type':'Event_Type','Business Type':'Business_Type',
        'Venue':'Venue_ID','Weather':'Weather','Month':'Month_Name','Year':'Year','Waste Level':'Waste_Level'
    }
    if dim1 not in allowed or dim2 not in allowed or dim3 not in allowed or len({dim1,dim2,dim3})<3:
        raise ValueError('Choose three distinct valid dimensions.')
    if measure not in ['Surplus_Quantity','Waste_Quantity','Quantity_Consumed','Quantity_Prepared','Daily_Demand','Remaining_Stock']:
        raise ValueError('Invalid measure')
    g = df.groupby([allowed[dim1],allowed[dim2],allowed[dim3]], dropna=False)[measure].agg(['count','sum','mean']).reset_index()
    g.columns = ['x','y','z','count','sum','avg']
    return g.replace({np.nan:None}).to_dict(orient='records')


def pattern_mining():
    con=sqlite3.connect(DB_PATH)
    q='''SELECT d.Food_Item,d.Food_Category,e.Event_Type,b.Business_Type,w.Weather,
                f.Surplus_Band,f.Waste_Level,f.Donation_Made,f.Surplus_Quantity,f.Waste_Quantity
         FROM Fact_Food_Surplus f
         JOIN Dim_Food d ON f.Food_Key=d.Food_Key
         JOIN Dim_Event e ON f.Event_ID=e.Event_ID
         JOIN Dim_Business b ON f.Business_Key=b.Business_Key
         JOIN Dim_Weather w ON f.Weather_Key=w.Weather_Key'''
    df=pd.read_sql_query(q,con); con.close()
    # Deterministic Apriori-like association rules over categorical tokens.
    cols=['Event_Type','Food_Category','Business_Type','Weather','Surplus_Band','Waste_Level','Donation_Made']
    tx=[]
    for _,r in df[cols].iterrows():
        tx.append({f'{c}={r[c]}' for c in cols if pd.notna(r[c])})
    n=len(tx)
    from collections import Counter
    one=Counter(item for row in tx for item in row)
    pairs=Counter()
    for row in tx:
        items=sorted(row)
        for i in range(len(items)):
            for j in range(i+1,len(items)): pairs[(items[i],items[j])]+=1
    rules=[]
    for (a,b),cnt in pairs.items():
        support=cnt/n
        ca=one[a]; cb=one[b]
        if support < 0.05: continue
        # a -> b
        conf=cnt/ca; lift=conf/(cb/n)
        rules.append({'antecedent':a,'consequent':b,'support':round(support,4),'confidence':round(conf,4),'lift':round(lift,3),'count':cnt})
    rules=sorted(rules,key=lambda x:(x['lift'],x['confidence']),reverse=True)[:20]
    return rules
