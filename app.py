"""
Nigeria Debt Clock — app.py
Economic dashboard tracking Nigeria's borrowing, reserves, exchange rates,
and fuel prices across presidential administrations since 1999.
"""
import os
from datetime import datetime, timezone
from flask import Flask, render_template, jsonify, Response, request
from flask_sqlalchemy import SQLAlchemy

# ══════════════════════════════════════════════════════════════════════════════
# APP CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'debt-clock-secret-2026')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///debt_clock.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


# ══════════════════════════════════════════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════════════════════════════════════════

class President(db.Model):
    __tablename__ = 'presidents'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    party = db.Column(db.String(20), nullable=False)
    party_color = db.Column(db.String(10), default='#666')
    start_year = db.Column(db.Integer, nullable=False)
    end_year = db.Column(db.Integer, nullable=True)  # None = incumbent
    photo_initials = db.Column(db.String(5), default='')
    note = db.Column(db.String(200), nullable=True)

    data_points = db.relationship('EconomicData', backref='president', lazy=True)


class EconomicData(db.Model):
    __tablename__ = 'economic_data'
    id = db.Column(db.Integer, primary_key=True)
    president_id = db.Column(db.Integer, db.ForeignKey('presidents.id'), nullable=False)
    year = db.Column(db.Integer, nullable=False)

    # Debt (USD billions)
    external_debt_usd = db.Column(db.Float, nullable=True)
    domestic_debt_ngn_tn = db.Column(db.Float, nullable=True)  # NGN trillions
    total_debt_usd = db.Column(db.Float, nullable=True)

    # Reserves (USD billions)
    external_reserves_usd = db.Column(db.Float, nullable=True)

    # Exchange Rate (NGN per USD)
    exchange_rate_official = db.Column(db.Float, nullable=True)
    exchange_rate_parallel = db.Column(db.Float, nullable=True)

    # Fuel Prices (NGN per litre)
    petrol_price = db.Column(db.Float, nullable=True)
    diesel_price = db.Column(db.Float, nullable=True)

    # GDP
    gdp_usd = db.Column(db.Float, nullable=True)  # USD billions
    gdp_growth = db.Column(db.Float, nullable=True)  # percentage

    # Population (millions) — for per-capita calculations
    population = db.Column(db.Float, nullable=True)

    # Debt to GDP ratio
    debt_to_gdp = db.Column(db.Float, nullable=True)

    # Revenue & Debt Service (NGN trillions)
    federal_revenue_ngn_tn = db.Column(db.Float, nullable=True)
    debt_service_ngn_tn = db.Column(db.Float, nullable=True)

    # Inflation (CPI annual %)
    inflation_rate = db.Column(db.Float, nullable=True)

    # Brent crude oil price (USD per barrel, annual average)
    oil_price_usd = db.Column(db.Float, nullable=True)

    # Minimum wage (NGN per month)
    minimum_wage = db.Column(db.Float, nullable=True)


# ══════════════════════════════════════════════════════════════════════════════
# SEED DATA
# ══════════════════════════════════════════════════════════════════════════════

def seed_data():
    """Seed all historical economic data."""
    # Presidents
    presidents = [
        President(id=1, name='Olusegun Obasanjo', party='PDP', party_color='#e31b23',
                  start_year=1999, end_year=2007, photo_initials='OO',
                  note='Negotiated Paris Club debt exit ($18bn relief)'),
        President(id=2, name="Umaru Musa Yar'Adua", party='PDP', party_color='#e31b23',
                  start_year=2007, end_year=2010, photo_initials='UY',
                  note='Died in office May 2010'),
        President(id=3, name='Goodluck Jonathan', party='PDP', party_color='#e31b23',
                  start_year=2010, end_year=2015, photo_initials='GJ',
                  note='GDP rebased to become Africa\'s largest economy'),
        President(id=4, name='Muhammadu Buhari', party='APC', party_color='#0066B3',
                  start_year=2015, end_year=2023, photo_initials='MB',
                  note='Two recessions (2016, 2020). Ways & Means securitization'),
        President(id=5, name='Bola Ahmed Tinubu', party='APC', party_color='#0066B3',
                  start_year=2023, end_year=None, photo_initials='BT',
                  note='Removed fuel subsidy. Unified exchange rate'),
    ]
    for p in presidents:
        db.session.add(p)

    # Economic data points — 19 fields per row
    # Format: (president_id, year, ext_debt, dom_debt_ngn_tn, total_debt_usd,
    #          reserves, fx_official, fx_parallel, petrol, diesel,
    #          gdp_usd, gdp_growth, population, debt_to_gdp,
    #          federal_revenue_ngn_tn, debt_service_ngn_tn,
    #          inflation_rate, oil_price_usd, minimum_wage)
    # ══════════════════════════════════════════════════════════════════════════
    # VERIFIED SOURCES (triple-checked April 2026):
    #   External debt:  DMO quarterly reports (dmo.gov.ng)
    #   Domestic debt:  DMO quarterly reports (NGN trillions)
    #   Total debt USD: Calculated = ext_debt + (dom_debt_ngn / fx_official)
    #   Reserves:       CBN gross external reserves, end-of-year (cbn.gov.ng)
    #   FX official:    CBN IFEM/I&E rate, end-of-year
    #   FX parallel:    Bureau de change / black market rate (Nairaland, abokiFX)
    #   Petrol (PMS):   PPPRA/NNPC official pump price (Autogirl, Energypedia)
    #   Diesel (AGO):   Deregulated market price (Energypedia, NBS)
    #   GDP:            World Bank / Worldometer (2014 rebased, current USD)
    #   GDP growth:     World Bank (NY.GDP.MKTP.KD.ZG) via IndexMundi
    #   Population:     World Bank / UN (IndexMundi)
    #   Debt-to-GDP:    Calculated = total_debt_usd / gdp_usd * 100
    #   Revenue:        Budget Office / BudgIT / CBN annual reports (NGN trillions)
    #   Debt service:   DMO / Budget Office (NGN trillions)
    #   Inflation:      NBS / World Bank CPI annual % (IndexMundi)
    #   Oil price:      Brent crude annual average (World Bank / IndexMundi)
    #   Minimum wage:   National Minimum Wage Act amendments
    # ══════════════════════════════════════════════════════════════════════════
    data = [
        # (pid, yr, ext_debt, dom_tn, total_usd, reserves, fx_off, fx_par,
        #  petrol, diesel, gdp, gdp_gr, pop, d2g,
        #  revenue, debt_svc, inflation, oil_price, min_wage)
        #
        # ── Obasanjo (1999-2007) ──
        (1, 1999, 28.0, 0.8, 36.7,   5.0,  92, 90,   20, None,   81, 0.6, 119, 45.3,  0.72, 0.58, 6.6, 18, 3000),
        (1, 2000, 28.3, 0.9, 37.1,   9.9, 102, 105,  22, None,   96, 5.0, 122, 38.6,  1.59, 0.64, 6.9, 29, 5500),
        (1, 2001, 28.4, 1.0, 37.3,  10.4, 112, 133,  22, None,  103, 5.9, 125, 36.2,  1.09, 0.65, 18.9, 25, 5500),
        (1, 2002, 30.0, 1.2, 39.9,   7.7, 121, 135,  26, None,  132, 3.8, 129, 30.2,  0.79, 0.36, 12.9, 25, 5500),
        (1, 2003, 32.0, 1.3, 42.1,   7.5, 129, 140,  42, None,  145, 7.4, 132, 29.0,  1.02, 0.32, 14.0, 29, 5500),
        (1, 2004, 31.0, 1.4, 41.5,  17.0, 133, 142,  50, None,  184, 9.3, 135, 22.6,  1.39, 0.30, 15.0, 38, 5500),
        (1, 2005, 20.0, 1.5, 31.4,  28.3, 132, 142,  65, None,  239, 6.4, 139, 13.1,  1.66, 0.28, 17.9, 55, 5500),
        (1, 2006, 3.5, 1.8, 17.6,   43.9, 128, 130,  65, None,  314, 6.1, 143, 5.6,   1.94, 0.25, 8.2, 65, 5500),
        # ── Yar'Adua (2007-2010) ──
        (2, 2007, 3.7, 2.2, 21.3,   52.5, 125, 128,  65, None,  375, 6.6, 146, 5.7,   1.85, 0.25, 5.4, 72, 5500),
        (2, 2008, 3.7, 2.3, 23.2,   53.0, 118, 150,  65, 135,  472, 6.8, 150, 4.9,   2.54, 0.38, 11.6, 97, 5500),
        (2, 2009, 3.9, 3.2, 25.4,   42.4, 149, 170,  65, 120,  426, 8.0, 154, 6.0,   1.85, 0.28, 12.6, 62, 5500),
        # ── Jonathan (2010-2015) ──
        (3, 2010, 4.6, 4.6, 35.3,   32.3, 150, 160,  65, 120,  527, 8.0, 159, 6.7,   2.29, 0.42, 13.7, 80, 5500),
        (3, 2011, 5.7, 5.6, 41.8,   32.6, 155, 165,  65, 140,  591, 5.3, 163, 7.1,   3.54, 0.53, 10.8, 111, 18000),
        (3, 2012, 6.5, 6.0, 44.7,   43.8, 157, 162,  97, 170,  658, 4.2, 167, 6.8,   3.33, 0.56, 12.2, 112, 18000),
        (3, 2013, 8.8, 6.5, 50.2,   43.6, 157, 165,  97, 160,  735, 6.7, 172, 6.8,   2.95, 0.65, 8.5, 109, 18000),
        (3, 2014, 9.7, 7.9, 59.7,   34.2, 158, 175,  97, 145,  811, 6.3, 176, 7.4,   3.47, 0.78, 8.1, 99, 18000),
        # ── Buhari (2015-2023) ──
        (4, 2015, 10.7, 8.8, 55.4,  28.3, 197, 240,  87, 150,  696, 2.7, 181, 8.0,   3.22, 1.06, 9.0, 52, 18000),
        (4, 2016, 11.4, 11.1, 47.8, 27.0, 305, 470, 145, 200,  570, -1.6, 186, 8.4,  2.69, 1.34, 15.7, 44, 18000),
        (4, 2017, 18.9, 12.6, 60.1, 38.8, 306, 365, 145, 220,  529, 0.8, 191, 11.4,  3.72, 1.66, 16.5, 54, 18000),
        (4, 2018, 25.3, 12.8, 67.1, 43.1, 306, 362, 145, 225,  594, 1.9, 196, 11.3,  5.32, 2.20, 12.1, 71, 18000),
        (4, 2019, 27.7, 14.3, 74.4, 38.6, 306, 360, 145, 230,  668, 2.2, 201, 11.1,  4.61, 2.45, 11.4, 64, 30000),
        (4, 2020, 33.3, 16.0, 75.3, 36.1, 381, 475, 162, 250,  599, -1.8, 206, 12.6, 3.94, 3.34, 13.3, 42, 30000),
        (4, 2021, 38.4, 18.0, 82.2, 40.5, 411, 565, 165, 280,  609, 3.6, 211, 13.5,  5.51, 5.28, 17.0, 71, 30000),
        (4, 2022, 41.7, 27.6, 105.1, 37.1, 435, 725, 185, 800, 646, 3.3, 216, 16.3,  7.46, 5.29, 18.9, 99, 30000),
        # ── Tinubu (2023-present) ──
        (5, 2023, 42.5, 46.3, 104.2, 33.2, 750, 1150, 617, 890, 487, 2.9, 220, 21.4, 9.56, 7.70, 25.0, 83, 30000),
        (5, 2024, 44.0, 65.7, 89.3,  40.2, 1450, 1600, 900, 1340, 252, 3.4, 225, 35.4, 14.2, 9.80, 31.4, 80, 70000),
        (5, 2025, 47.0, 80.6, 99.0,  45.7, 1550, 1650, 1050, 1440, 285, 3.5, 230, 34.7, 16.5, 10.5, 15.2, 75, 70000),
    ]

    for row in data:
        dp = EconomicData(
            president_id=row[0], year=row[1],
            external_debt_usd=row[2], domestic_debt_ngn_tn=row[3],
            total_debt_usd=row[4], external_reserves_usd=row[5],
            exchange_rate_official=row[6], exchange_rate_parallel=row[7],
            petrol_price=row[8], diesel_price=row[9],
            gdp_usd=row[10], gdp_growth=row[11],
            population=row[12], debt_to_gdp=row[13],
            federal_revenue_ngn_tn=row[14], debt_service_ngn_tn=row[15],
            inflation_rate=row[16], oil_price_usd=row[17],
            minimum_wage=row[18],
        )
        db.session.add(dp)

    db.session.commit()


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE INITIALIZATION
# ══════════════════════════════════════════════════════════════════════════════

DATA_VERSION = 3  # Bump this to force a re-seed on next deploy

with app.app_context():
    db.create_all()
    # Re-seed if empty, forced, or missing new columns
    latest = EconomicData.query.order_by(EconomicData.year.desc()).first()
    needs_seed = (
        President.query.count() == 0
        or os.environ.get('FORCE_RESEED') == '1'
        or (latest and latest.inflation_rate is None)  # v3 columns missing
    )
    if needs_seed:
        db.drop_all()
        db.create_all()
        seed_data()


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    presidents = President.query.order_by(President.start_year).all()
    all_data = EconomicData.query.order_by(EconomicData.year).all()

    # Current (latest) data point
    latest = all_data[-1] if all_data else None

    # Build presidential summary cards
    # Group data by president
    pres_data = {}
    for pres in presidents:
        pres_data[pres.id] = [d for d in all_data if d.president_id == pres.id]

    pres_summaries = []
    for i, pres in enumerate(presidents):
        pdata = pres_data[pres.id]
        if not pdata:
            continue

        # "Inherited" = previous president's LAST data point (ensures continuity)
        # For the first president, use their own first data point
        if i > 0 and pres_data.get(presidents[i-1].id):
            prev_last = pres_data[presidents[i-1].id][-1]
        else:
            prev_last = pdata[0]

        last = pdata[-1]

        debt_inherited = prev_last.total_debt_usd
        debt_left = last.total_debt_usd
        debt_change = debt_left - debt_inherited
        reserves_start = prev_last.external_reserves_usd
        reserves_end = last.external_reserves_usd
        reserves_change = reserves_end - reserves_start
        fx_start = prev_last.exchange_rate_official
        fx_end = last.exchange_rate_official
        petrol_start = prev_last.petrol_price
        petrol_end = last.petrol_price
        gdp_start = prev_last.gdp_usd
        gdp_end = last.gdp_usd
        inflation_start = prev_last.inflation_rate
        inflation_end = last.inflation_rate

        # Debt service as % of revenue
        ds_pct_start = None
        if prev_last.debt_service_ngn_tn and prev_last.federal_revenue_ngn_tn:
            ds_pct_start = prev_last.debt_service_ngn_tn / prev_last.federal_revenue_ngn_tn * 100
        ds_pct_end = None
        if last.debt_service_ngn_tn and last.federal_revenue_ngn_tn:
            ds_pct_end = last.debt_service_ngn_tn / last.federal_revenue_ngn_tn * 100

        # Litres of petrol per minimum wage
        litres_start = None
        if prev_last.minimum_wage and prev_last.petrol_price:
            litres_start = prev_last.minimum_wage / prev_last.petrol_price
        litres_end = None
        if last.minimum_wage and last.petrol_price:
            litres_end = last.minimum_wage / last.petrol_price

        pres_summaries.append({
            'president': pres,
            'first': prev_last,
            'last': last,
            'years': f"{pres.start_year}–{pres.end_year or 'present'}",
            'debt_inherited': debt_inherited,
            'debt_left': debt_left,
            'debt_change': debt_change,
            'debt_change_pct': (debt_change / debt_inherited * 100) if debt_inherited else 0,
            'reserves_start': reserves_start,
            'reserves_end': reserves_end,
            'reserves_change': reserves_change,
            'fx_start': fx_start,
            'fx_end': fx_end,
            'fx_change_pct': ((fx_end - fx_start) / fx_start * 100) if fx_start else 0,
            'petrol_start': petrol_start,
            'petrol_end': petrol_end,
            'gdp_start': gdp_start,
            'gdp_end': gdp_end,
            'inflation_start': inflation_start,
            'inflation_end': inflation_end,
            'ds_pct_start': ds_pct_start,
            'ds_pct_end': ds_pct_end,
            'litres_start': litres_start,
            'litres_end': litres_end,
        })

    # Per-citizen debt
    per_citizen_debt = None
    if latest and latest.population:
        per_citizen_debt = (latest.total_debt_usd * 1e9) / (latest.population * 1e6)

    # Timeline data for charts (JSON)
    timeline = {
        'years': [d.year for d in all_data],
        'total_debt': [d.total_debt_usd for d in all_data],
        'external_debt': [d.external_debt_usd for d in all_data],
        'domestic_debt_ngn': [d.domestic_debt_ngn_tn for d in all_data],
        'reserves': [d.external_reserves_usd for d in all_data],
        'fx_official': [d.exchange_rate_official for d in all_data],
        'fx_parallel': [d.exchange_rate_parallel for d in all_data],
        'petrol': [d.petrol_price for d in all_data],
        'diesel': [d.diesel_price for d in all_data],
        'gdp': [d.gdp_usd for d in all_data],
        'gdp_growth': [d.gdp_growth for d in all_data],
        'debt_to_gdp': [d.debt_to_gdp for d in all_data],
        'population': [d.population for d in all_data],
        'revenue': [d.federal_revenue_ngn_tn for d in all_data],
        'debt_service': [d.debt_service_ngn_tn for d in all_data],
        'debt_service_pct': [
            round(d.debt_service_ngn_tn / d.federal_revenue_ngn_tn * 100, 1)
            if d.debt_service_ngn_tn and d.federal_revenue_ngn_tn else None
            for d in all_data
        ],
        'inflation': [d.inflation_rate for d in all_data],
        'oil_price': [d.oil_price_usd for d in all_data],
        'minimum_wage': [d.minimum_wage for d in all_data],
        'litres_per_wage': [
            round(d.minimum_wage / d.petrol_price, 1)
            if d.minimum_wage and d.petrol_price else None
            for d in all_data
        ],
        'naira_purchasing_power': [
            round(all_data[0].exchange_rate_official / d.exchange_rate_official * 100, 1)
            if d.exchange_rate_official else None
            for d in all_data
        ],
    }

    # Current debt service ratio
    debt_service_pct = None
    if latest and latest.debt_service_ngn_tn and latest.federal_revenue_ngn_tn:
        debt_service_pct = latest.debt_service_ngn_tn / latest.federal_revenue_ngn_tn * 100

    # Presidential era boundaries for chart annotations
    eras = []
    for pres in presidents:
        eras.append({
            'name': pres.name.split()[-1],  # Last name
            'start': pres.start_year,
            'end': pres.end_year or 2026,
            'color': pres.party_color,
        })

    return render_template('index.html',
                           presidents=presidents,
                           pres_summaries=pres_summaries,
                           latest=latest,
                           per_citizen_debt=per_citizen_debt,
                           debt_service_pct=debt_service_pct,
                           timeline=timeline,
                           eras=eras,
                           last_updated='April 2026')


@app.route('/api/data')
def api_data():
    """JSON API for all economic data."""
    all_data = EconomicData.query.order_by(EconomicData.year).all()
    return jsonify([{
        'year': d.year,
        'external_debt_usd': d.external_debt_usd,
        'domestic_debt_ngn_tn': d.domestic_debt_ngn_tn,
        'total_debt_usd': d.total_debt_usd,
        'external_reserves_usd': d.external_reserves_usd,
        'exchange_rate_official': d.exchange_rate_official,
        'exchange_rate_parallel': d.exchange_rate_parallel,
        'petrol_price': d.petrol_price,
        'diesel_price': d.diesel_price,
        'gdp_usd': d.gdp_usd,
        'gdp_growth': d.gdp_growth,
        'population': d.population,
        'debt_to_gdp': d.debt_to_gdp,
        'federal_revenue_ngn_tn': d.federal_revenue_ngn_tn,
        'debt_service_ngn_tn': d.debt_service_ngn_tn,
        'inflation_rate': d.inflation_rate,
        'oil_price_usd': d.oil_price_usd,
        'minimum_wage': d.minimum_wage,
    } for d in all_data])


@app.route('/robots.txt')
def robots_txt():
    lines = [
        "User-agent: *", "Allow: /", "Disallow: /api/",
        f"Sitemap: {request.url_root.replace('http://', 'https://').rstrip('/')}/sitemap.xml",
    ]
    return Response("\n".join(lines), mimetype="text/plain")


@app.route('/sitemap.xml')
def sitemap_xml():
    base = request.url_root.replace('http://', 'https://').rstrip('/')
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
           f'<url><loc>{base}/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>',
           '</urlset>']
    return Response("\n".join(xml), mimetype="application/xml")


if __name__ == '__main__':
    app.run(debug=True, port=5001)
