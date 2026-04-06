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
    data = [
        # ── Obasanjo (1999-2007) ──
        (1, 1999, 28.0, 0.8, 30.0,   4.0,  22, 88,   20, None,   35, 0.5, 120, 85.7),
        (1, 2000, 28.3, 0.9, 30.5,   9.9,  85, 100,  22, None,   46, 5.3, 123, 66.3),
        (1, 2001, 28.4, 1.0, 31.0,  10.4, 112, 133,  22, None,   44, 4.4, 126, 70.5),
        (1, 2002, 30.0, 1.2, 33.0,  7.7, 121, 135,  26, None,   59, 3.8, 130, 55.9),
        (1, 2003, 32.0, 1.3, 35.0,  7.5, 129, 140,  40, None,   68, 10.4, 133, 51.5),
        (1, 2004, 31.0, 1.4, 35.0,  17.0, 133, 140,  50, None,   88, 10.6, 137, 39.8),
        (1, 2005, 20.0, 1.5, 26.0,  28.3, 132, 140,  50, None,  112, 5.4, 140, 23.2),
        (1, 2006, 3.5, 1.8, 18.0,   42.3, 128, 132,  65, None,  147, 6.1, 144, 12.2),
        # ── Yar'Adua (2007-2010) ──
        (2, 2007, 3.7, 2.2, 18.0,   51.3, 125, 128,  65, None,  167, 6.4, 148, 10.8),
        (2, 2008, 3.7, 2.3, 18.5,   53.0, 117, 125,  65, None,  209, 6.3, 151, 8.9),
        (2, 2009, 3.9, 3.2, 25.0,   42.4, 149, 170,  65, None,  169, 6.9, 155, 14.8),
        # ── Jonathan (2010-2015) ──
        (3, 2010, 4.6, 4.6, 35.0,   32.3, 150, 160,  65, 120,  369, 7.8, 159, 9.5),
        (3, 2011, 5.7, 5.6, 42.0,   32.6, 154, 160,  65, 140,  411, 4.9, 164, 10.2),
        (3, 2012, 6.5, 6.0, 44.0,   44.2, 157, 162,  97, 150,  461, 4.3, 168, 9.5),
        (3, 2013, 8.8, 6.5, 49.0,   43.6, 157, 165,  97, 155,  515, 5.4, 173, 9.5),
        (3, 2014, 9.7, 7.9, 53.0,   34.5, 157, 175,  97, 165,  568, 6.3, 177, 9.3),
        # ── Buhari (2015-2023) ──
        (4, 2015, 10.7, 8.8, 56.0,  29.1, 197, 240,  87, 180,  486, 2.7, 181, 11.5),
        (4, 2016, 11.4, 11.1, 47.0, 26.5, 305, 470, 145, 200,  405, -1.6, 186, 11.6),
        (4, 2017, 15.0, 12.6, 62.0, 38.8, 306, 365, 145, 220,  376, 0.8, 191, 16.5),
        (4, 2018, 22.1, 12.8, 73.0, 42.5, 306, 362, 145, 225,  397, 1.9, 196, 18.4),
        (4, 2019, 27.7, 14.3, 84.0, 38.6, 306, 360, 145, 230,  448, 2.3, 201, 18.8),
        (4, 2020, 33.3, 16.0, 87.0, 35.4, 381, 475, 162, 250,  432, -1.8, 206, 20.1),
        (4, 2021, 38.4, 18.0, 92.0, 40.5, 411, 565, 165, 280,  441, 3.6, 211, 20.9),
        (4, 2022, 41.7, 27.6, 103.0, 37.1, 435, 725, 185, 800, 477, 3.3, 216, 21.6),
        # ── Tinubu (2023-present) ──
        (5, 2023, 42.5, 54.1, 114.0, 33.0, 750, 1150, 568, 1000, 363, 2.7, 220, 31.4),
        (5, 2024, 44.0, 68.0, 120.0, 34.0, 1450, 1600, 900, 1300, 253, 3.0, 225, 47.4),
        (5, 2025, 46.0, 75.0, 128.0, 37.0, 1550, 1650, 1050, 1400, 280, 3.2, 230, 45.7),
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

with app.app_context():
    db.create_all()
    if President.query.count() == 0:
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
    pres_summaries = []
    for pres in presidents:
        pdata = [d for d in all_data if d.president_id == pres.id]
        if not pdata:
            continue
        first = pdata[0]
        last = pdata[-1]

        debt_change = last.total_debt_usd - first.total_debt_usd
        reserves_change = last.external_reserves_usd - first.external_reserves_usd
        fx_start = first.exchange_rate_official
        fx_end = last.exchange_rate_official
        petrol_start = first.petrol_price
        petrol_end = last.petrol_price

        pres_summaries.append({
            'president': pres,
            'first': first,
            'last': last,
            'years': f"{pres.start_year}–{pres.end_year or 'present'}",
            'debt_inherited': first.total_debt_usd,
            'debt_left': last.total_debt_usd,
            'debt_change': debt_change,
            'debt_change_pct': (debt_change / first.total_debt_usd * 100) if first.total_debt_usd else 0,
            'reserves_start': first.external_reserves_usd,
            'reserves_end': last.external_reserves_usd,
            'reserves_change': reserves_change,
            'fx_start': fx_start,
            'fx_end': fx_end,
            'fx_change_pct': ((fx_end - fx_start) / fx_start * 100) if fx_start else 0,
            'petrol_start': petrol_start,
            'petrol_end': petrol_end,
            'gdp_start': first.gdp_usd,
            'gdp_end': last.gdp_usd,
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
