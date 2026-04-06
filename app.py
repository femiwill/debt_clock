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

    # Economic data points
    # Format: (president_id, year, ext_debt, dom_debt_ngn_tn, total_debt_usd,
    #          reserves, fx_official, fx_parallel, petrol, diesel,
    #          gdp_usd, gdp_growth, population, debt_to_gdp)
    # Sources: DMO (debt), CBN (reserves, FX), World Bank (GDP, population),
    #          NBS (fuel prices), Worldometer, IndexMundi
    # GDP uses World Bank rebased figures (2014 rebasing applied retroactively)
    # FX: official = CBN/IFEM rate; parallel = bureau de change / black market
    # Reserves: CBN gross external reserves (end-of-year)
    data = [
        # ── Obasanjo (1999-2007) ──
        (1, 1999, 28.0, 0.8, 30.0,   5.5,  92, 88,   20, None,   81, 0.6, 119, 37.0),
        (1, 2000, 28.3, 0.9, 30.5,   9.9, 102, 105,  22, None,   96, 5.0, 122, 31.8),
        (1, 2001, 28.4, 1.0, 31.0,  10.4, 112, 133,  22, None,  103, 5.9, 125, 30.1),
        (1, 2002, 30.0, 1.2, 33.0,   7.7, 121, 135,  26, None,  132, 3.8, 129, 25.0),
        (1, 2003, 32.0, 1.3, 35.0,   7.5, 129, 140,  40, None,  145, 7.4, 132, 24.1),
        (1, 2004, 31.0, 1.4, 35.0,  17.0, 133, 140,  50, None,  184, 9.3, 135, 19.0),
        (1, 2005, 20.0, 1.5, 26.0,  28.3, 132, 134,  50, None,  239, 6.4, 139, 10.9),
        (1, 2006, 3.5, 1.8, 18.0,   43.9, 128, 130,  65, None,  314, 6.1, 143, 5.7),
        # ── Yar'Adua (2007-2010) ──
        (2, 2007, 3.7, 2.2, 18.0,   52.5, 125, 128,  65, None,  375, 6.6, 146, 4.8),
        (2, 2008, 3.7, 2.3, 18.5,   53.0, 118, 150,  65, None,  472, 6.8, 150, 3.9),
        (2, 2009, 3.9, 3.2, 25.0,   42.4, 149, 170,  65, None,  426, 8.0, 154, 5.9),
        # ── Jonathan (2010-2015) ──
        (3, 2010, 4.6, 4.6, 35.0,   32.3, 150, 160,  65, 120,  527, 8.0, 159, 6.6),
        (3, 2011, 5.7, 5.6, 42.0,   32.6, 155, 165,  65, 140,  591, 5.3, 163, 7.1),
        (3, 2012, 6.5, 6.0, 44.0,   43.8, 157, 162,  97, 150,  658, 4.2, 167, 6.7),
        (3, 2013, 8.8, 6.5, 49.0,   43.6, 157, 165,  97, 155,  735, 6.7, 172, 6.7),
        (3, 2014, 9.7, 7.9, 53.0,   34.2, 158, 175,  97, 165,  811, 6.3, 176, 6.5),
        # ── Buhari (2015-2023) ──
        (4, 2015, 10.7, 8.8, 56.0,  28.3, 197, 240,  87, 180,  696, 2.7, 181, 8.0),
        (4, 2016, 11.4, 11.1, 47.0, 27.0, 305, 470, 145, 200,  570, -1.6, 186, 8.2),
        (4, 2017, 18.9, 12.6, 62.0, 38.8, 306, 365, 145, 220,  529, 0.8, 191, 11.7),
        (4, 2018, 25.3, 12.8, 73.0, 43.1, 306, 362, 145, 225,  594, 1.9, 196, 12.3),
        (4, 2019, 27.7, 14.3, 84.0, 38.6, 306, 360, 145, 230,  668, 2.2, 201, 12.6),
        (4, 2020, 33.3, 16.0, 87.0, 36.1, 381, 475, 162, 250,  599, -1.8, 206, 14.5),
        (4, 2021, 38.4, 18.0, 92.0, 40.5, 411, 565, 165, 280,  609, 3.6, 211, 15.1),
        (4, 2022, 41.7, 27.6, 103.0, 37.1, 435, 725, 185, 800, 646, 3.3, 216, 15.9),
        # ── Tinubu (2023-present) ──
        (5, 2023, 42.5, 46.3, 108.0, 33.2, 750, 1150, 617, 890, 487, 2.9, 220, 22.2),
        (5, 2024, 44.0, 65.7, 91.0,  40.2, 1450, 1600, 900, 1340, 252, 3.4, 225, 36.1),
        (5, 2025, 47.0, 80.6, 99.0,  40.9, 1550, 1650, 1050, 1440, 285, 3.5, 230, 34.7),
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
        )
        db.session.add(dp)

    db.session.commit()


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE INITIALIZATION
# ══════════════════════════════════════════════════════════════════════════════

DATA_VERSION = 2  # Bump this to force a re-seed on next deploy

with app.app_context():
    db.create_all()
    # Re-seed if empty or data version changed
    latest = EconomicData.query.order_by(EconomicData.year.desc()).first()
    needs_seed = (
        President.query.count() == 0
        or os.environ.get('FORCE_RESEED') == '1'
        or (latest and latest.gdp_usd and latest.year == 1999 and latest.gdp_usd < 50)  # old pre-rebased data
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
    }

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
