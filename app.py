"""
Nigeria Debt Clock — app.py
Economic dashboard tracking Nigeria's borrowing, reserves, exchange rates,
and fuel prices across presidential administrations since 1999.
"""
import os
import re
import secrets
from datetime import datetime, timezone
from flask import Flask, render_template, jsonify, Response, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

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


class Subscriber(db.Model):
    __tablename__ = 'subscribers'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), unique=True, nullable=False)
    subscribed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = db.Column(db.Boolean, default=True)


class ApiKey(db.Model):
    __tablename__ = 'api_keys'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False)
    name = db.Column(db.String(200))
    email = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = db.Column(db.Boolean, default=True)
    queries_used = db.Column(db.Integer, default=0)


# ══════════════════════════════════════════════════════════════════════════════
# STATIC DATA (hardcoded dicts — no DB models needed)
# ══════════════════════════════════════════════════════════════════════════════

AFRICA_PEERS = {
    'Nigeria': {'flag': '🇳🇬', 'total_debt_usd': 89.3, 'debt_to_gdp': 35.4,
                'external_reserves': 40.2, 'gdp_usd': 252, 'population': 225,
                'debt_per_capita': 397, 'inflation': 31.4, 'fx_dep_5yr': 378,
                'credit_rating': 'B- (S&P)'},
    'South Africa': {'flag': '🇿🇦', 'total_debt_usd': 260, 'debt_to_gdp': 72.2,
                     'external_reserves': 62.5, 'gdp_usd': 360, 'population': 62,
                     'debt_per_capita': 4194, 'inflation': 4.5, 'fx_dep_5yr': 25,
                     'credit_rating': 'BB- (S&P)'},
    'Egypt': {'flag': '🇪🇬', 'total_debt_usd': 310, 'debt_to_gdp': 92.0,
              'external_reserves': 46.7, 'gdp_usd': 337, 'population': 106,
              'debt_per_capita': 2925, 'inflation': 27.5, 'fx_dep_5yr': 210,
              'credit_rating': 'B- (Fitch)'},
    'Kenya': {'flag': '🇰🇪', 'total_debt_usd': 82, 'debt_to_gdp': 72.0,
              'external_reserves': 8.9, 'gdp_usd': 114, 'population': 56,
              'debt_per_capita': 1464, 'inflation': 6.3, 'fx_dep_5yr': 32,
              'credit_rating': 'B (Fitch)'},
    'Ghana': {'flag': '🇬🇭', 'total_debt_usd': 55, 'debt_to_gdp': 83.0,
              'external_reserves': 5.8, 'gdp_usd': 66, 'population': 34,
              'debt_per_capita': 1618, 'inflation': 23.2, 'fx_dep_5yr': 180,
              'credit_rating': 'SD (S&P)'},
}

DEBT_BREAKDOWN = {
    'by_creditor': {
        'Multilateral': {
            'amount_usd': 20.8, 'pct': 47.3,
            'details': [
                {'name': 'World Bank (IDA/IBRD)', 'amount': 13.1},
                {'name': 'AfDB/ADF', 'amount': 3.2},
                {'name': 'IMF', 'amount': 2.8},
                {'name': 'Other Multilateral', 'amount': 1.7},
            ]
        },
        'Bilateral': {
            'amount_usd': 5.2, 'pct': 11.8,
            'details': [
                {'name': 'China (Exim Bank)', 'amount': 3.8},
                {'name': 'France (AFD)', 'amount': 0.5},
                {'name': 'Japan (JICA)', 'amount': 0.4},
                {'name': 'India/Germany/Other', 'amount': 0.5},
            ]
        },
        'Commercial': {
            'amount_usd': 18.0, 'pct': 40.9,
            'details': [
                {'name': 'Eurobonds', 'amount': 15.6},
                {'name': 'Diaspora Bonds', 'amount': 0.3},
                {'name': 'Other Commercial', 'amount': 2.1},
            ]
        },
    },
    'external_total': 44.0,
    'domestic_total_ngn_tn': 65.7,
    'domestic_instruments': {
        'FGN Bonds': {'amount_ngn_tn': 32.5, 'pct': 49.5},
        'Treasury Bills': {'amount_ngn_tn': 10.8, 'pct': 16.4},
        'FGN Sukuk': {'amount_ngn_tn': 1.2, 'pct': 1.8},
        'FGN Savings Bond': {'amount_ngn_tn': 0.3, 'pct': 0.5},
        'Promissory Notes': {'amount_ngn_tn': 1.5, 'pct': 2.3},
        'Ways & Means (Securitized)': {'amount_ngn_tn': 19.4, 'pct': 29.5},
    }
}

# State debts — DMO Q3 2024 (domestic in NGN billions, external in USD millions)
# Sorted by total_ngn_bn descending
STATE_DEBTS = [
    {'name': 'Lagos', 'domestic': 920, 'external': 1280, 'total': 2780},
    {'name': 'Rivers', 'domestic': 380, 'external': 150, 'total': 598},
    {'name': 'Delta', 'domestic': 340, 'external': 130, 'total': 529},
    {'name': 'Akwa Ibom', 'domestic': 300, 'external': 210, 'total': 605},
    {'name': 'Cross River', 'domestic': 280, 'external': 320, 'total': 745},
    {'name': 'Ogun', 'domestic': 250, 'external': 80, 'total': 366},
    {'name': 'Imo', 'domestic': 220, 'external': 150, 'total': 438},
    {'name': 'Oyo', 'domestic': 210, 'external': 120, 'total': 384},
    {'name': 'Kaduna', 'domestic': 200, 'external': 280, 'total': 607},
    {'name': 'Bayelsa', 'domestic': 190, 'external': 130, 'total': 379},
    {'name': 'Edo', 'domestic': 180, 'external': 220, 'total': 500},
    {'name': 'FCT', 'domestic': 170, 'external': 100, 'total': 315},
    {'name': 'Osun', 'domestic': 165, 'external': 90, 'total': 296},
    {'name': 'Enugu', 'domestic': 155, 'external': 110, 'total': 315},
    {'name': 'Kano', 'domestic': 150, 'external': 60, 'total': 237},
    {'name': 'Plateau', 'domestic': 145, 'external': 85, 'total': 268},
    {'name': 'Ekiti', 'domestic': 140, 'external': 50, 'total': 213},
    {'name': 'Abia', 'domestic': 135, 'external': 55, 'total': 215},
    {'name': 'Ondo', 'domestic': 130, 'external': 70, 'total': 232},
    {'name': 'Bauchi', 'domestic': 125, 'external': 95, 'total': 263},
    {'name': 'Benue', 'domestic': 120, 'external': 60, 'total': 207},
    {'name': 'Niger', 'domestic': 115, 'external': 80, 'total': 231},
    {'name': 'Kwara', 'domestic': 110, 'external': 45, 'total': 175},
    {'name': 'Anambra', 'domestic': 105, 'external': 30, 'total': 149},
    {'name': 'Kogi', 'domestic': 100, 'external': 75, 'total': 209},
    {'name': 'Adamawa', 'domestic': 95, 'external': 65, 'total': 189},
    {'name': 'Nasarawa', 'domestic': 90, 'external': 50, 'total': 163},
    {'name': 'Taraba', 'domestic': 85, 'external': 45, 'total': 150},
    {'name': 'Sokoto', 'domestic': 80, 'external': 40, 'total': 138},
    {'name': 'Gombe', 'domestic': 78, 'external': 55, 'total': 158},
    {'name': 'Ebonyi', 'domestic': 75, 'external': 100, 'total': 220},
    {'name': 'Zamfara', 'domestic': 70, 'external': 30, 'total': 114},
    {'name': 'Katsina', 'domestic': 68, 'external': 35, 'total': 119},
    {'name': 'Kebbi', 'domestic': 65, 'external': 38, 'total': 120},
    {'name': 'Jigawa', 'domestic': 60, 'external': 25, 'total': 96},
    {'name': 'Yobe', 'domestic': 55, 'external': 35, 'total': 106},
    {'name': 'Borno', 'domestic': 50, 'external': 40, 'total': 108},
]

QUIZ_QUESTIONS = [
    {'question': "What is Nigeria's total public debt as of 2025?",
     'options': ['$45 billion', '$99 billion', '$150 billion', '$200 billion'],
     'correct': 1, 'explanation': "Nigeria's total public debt is approximately $99 billion (DMO 2025)."},
    {'question': 'Which president oversaw the largest absolute increase in debt?',
     'options': ['Obasanjo', 'Jonathan', 'Buhari', 'Tinubu'],
     'correct': 2, 'explanation': 'Buhari added approximately $50B to the national debt between 2015-2023.'},
    {'question': "What percentage of Nigeria's revenue goes to debt servicing (2025)?",
     'options': ['25%', '44%', '64%', '92%'],
     'correct': 2, 'explanation': 'Approximately 64% of federal revenue is consumed by debt service payments.'},
    {'question': 'Which president achieved debt relief from the Paris Club?',
     'options': ["Yar'Adua", 'Obasanjo', 'Jonathan', 'Buhari'],
     'correct': 1, 'explanation': 'Obasanjo negotiated $18B in Paris Club debt relief in 2005-2006.'},
    {'question': "What was the Naira/Dollar official rate when Obasanjo took office in 1999?",
     'options': ['N22/$1', 'N92/$1', 'N150/$1', 'N306/$1'],
     'correct': 1, 'explanation': 'The CBN IFEM rate was approximately N92/$1 in 1999.'},
    {'question': 'What is the current petrol price per litre in Nigeria (2025)?',
     'options': ['N165', 'N617', 'N900', 'N1,050'],
     'correct': 3, 'explanation': 'Petrol price is approximately N1,050/litre as of 2025 after subsidy removal.'},
    {'question': "Nigeria's debt-to-GDP ratio is approximately:",
     'options': ['15%', '35%', '55%', '75%'],
     'correct': 1, 'explanation': "Nigeria's debt-to-GDP ratio is about 35%, the lowest among major African peers."},
    {'question': 'How much does China (Exim Bank) hold of Nigeria\'s external debt?',
     'options': ['$1.2 billion', '$3.8 billion', '$8.5 billion', '$15 billion'],
     'correct': 1, 'explanation': 'China Exim Bank holds approximately $3.8B (8.6% of external debt).'},
    {'question': 'Which president removed the fuel subsidy?',
     'options': ['Jonathan', 'Buhari', 'Tinubu', 'Obasanjo'],
     'correct': 2, 'explanation': 'Tinubu removed the petrol subsidy in June 2023, causing prices to triple.'},
    {'question': "Nigeria's peak inflation rate in 2024 was approximately:",
     'options': ['15%', '22%', '31%', '45%'],
     'correct': 2, 'explanation': 'Inflation peaked at approximately 31.4% in 2024.'},
    {'question': 'What are the "Ways & Means" advances that were securitized?',
     'options': ['Foreign loans', 'CBN overdraft to federal govt', 'State government bonds', 'Oil company debts'],
     'correct': 1, 'explanation': 'Ways & Means are CBN overdraft advances to the federal government, securitized at N22.7T in 2023.'},
    {'question': "What was Nigeria's external reserves at their peak?",
     'options': ['$28 billion', '$43 billion', '$53 billion', '$65 billion'],
     'correct': 2, 'explanation': 'External reserves peaked at approximately $53B in 2008 under Yar\'Adua.'},
    {'question': 'How much total debt does each Nigerian citizen carry?',
     'options': ['$150', '$430', '$800', '$1,200'],
     'correct': 1, 'explanation': 'With $99B debt and 230M people, each Nigerian carries approximately $430 in public debt.'},
    {'question': 'Which country has the highest debt-to-GDP ratio in Africa?',
     'options': ['Nigeria (35%)', 'Kenya (72%)', 'Egypt (92%)', 'Ghana (83%)'],
     'correct': 2, 'explanation': 'Egypt has the highest at approximately 92%, while Nigeria has the lowest among peers at 35%.'},
    {'question': 'How many litres of petrol could a minimum wage buy in 1999?',
     'options': ['50 litres', '100 litres', '150 litres', '250 litres'],
     'correct': 2, 'explanation': 'With N3,000 wage and N20/litre petrol, a worker could buy 150 litres in 1999.'},
]

HISTORICAL_EVENTS = [
    {'year': 1999, 'event': 'Return to democracy — Obasanjo inaugurated', 'category': 'political', 'icon': 'flag'},
    {'year': 2000, 'event': 'Minimum wage raised to N5,500', 'category': 'economic', 'icon': 'cash'},
    {'year': 2003, 'event': 'Banking sector consolidation begins', 'category': 'economic', 'icon': 'bank'},
    {'year': 2005, 'event': 'Paris Club grants $18B debt relief', 'category': 'debt', 'icon': 'award'},
    {'year': 2006, 'event': 'Nigeria exits Paris Club debt — external debt drops to $3.5B', 'category': 'debt', 'icon': 'graph-down-arrow'},
    {'year': 2007, 'event': "Yar'Adua takes office; reserves near $53B peak", 'category': 'political', 'icon': 'flag'},
    {'year': 2008, 'event': 'Global financial crisis — oil crashes from $147 to $36', 'category': 'global', 'icon': 'globe'},
    {'year': 2010, 'event': "Yar'Adua dies in office; Jonathan becomes president", 'category': 'political', 'icon': 'flag'},
    {'year': 2011, 'event': 'Minimum wage raised to N18,000; fuel subsidy protests', 'category': 'economic', 'icon': 'megaphone'},
    {'year': 2012, 'event': 'Partial subsidy removal — petrol jumps to N97', 'category': 'economic', 'icon': 'fuel-pump'},
    {'year': 2014, 'event': "GDP rebased — Nigeria becomes Africa's largest economy", 'category': 'economic', 'icon': 'trophy'},
    {'year': 2015, 'event': 'Buhari elected; oil price collapse begins', 'category': 'political', 'icon': 'flag'},
    {'year': 2016, 'event': 'First recession in 25 years; naira devalued to N305', 'category': 'economic', 'icon': 'exclamation-triangle'},
    {'year': 2019, 'event': 'Minimum wage raised to N30,000', 'category': 'economic', 'icon': 'cash'},
    {'year': 2020, 'event': 'COVID-19 pandemic; second recession; oil crashes', 'category': 'global', 'icon': 'virus'},
    {'year': 2022, 'event': 'Ways & Means N22.7T securitized into public debt', 'category': 'debt', 'icon': 'exclamation-circle'},
    {'year': 2023, 'event': 'Tinubu removes fuel subsidy; naira floated; petrol triples', 'category': 'economic', 'icon': 'lightning'},
    {'year': 2024, 'event': 'Inflation hits 31.4%; minimum wage raised to N70,000', 'category': 'economic', 'icon': 'arrow-up-circle'},
    {'year': 2025, 'event': 'Total debt reaches $99B; reserves recover to $45.7B', 'category': 'debt', 'icon': 'graph-up-arrow'},
]

GLOSSARY = {
    'Total Public Debt': 'The sum of all money owed by the federal government, including both external (foreign) and domestic (local) borrowing.',
    'External Debt': 'Money borrowed from foreign sources — multilateral institutions (World Bank, IMF), bilateral lenders (China, France), and commercial creditors (Eurobond holders).',
    'Domestic Debt': 'Money borrowed within Nigeria through instruments like FGN Bonds, Treasury Bills, Sukuk, and the securitized Ways & Means advances from CBN.',
    'External Reserves': 'Foreign currency holdings maintained by the Central Bank of Nigeria (CBN) to back the naira and pay for imports.',
    'Debt-to-GDP Ratio': 'Total debt as a percentage of GDP. Nigeria\'s ~35% is low compared to peers, but the revenue-to-debt ratio is the bigger concern.',
    'Debt Service': 'Annual payments to service existing debt (principal + interest). Nigeria spends ~64% of revenue on debt service.',
    'Ways & Means': 'CBN overdraft to the federal government. N22.7T was securitized (converted to bonds) in 2023, instantly adding to official debt.',
    'Paris Club': 'A group of major creditor countries that coordinates debt relief. Nigeria received $18B relief in 2005-2006 under Obasanjo.',
    'Eurobonds': 'Dollar-denominated bonds issued in international capital markets. They carry higher interest rates but provide foreign currency.',
    'GDP': 'Gross Domestic Product — the total value of all goods and services produced in Nigeria in a year.',
    'Inflation Rate': 'The annual percentage increase in consumer prices (CPI). High inflation erodes purchasing power.',
    'Exchange Rate': 'The rate at which naira trades against the US dollar. The parallel (black market) rate often diverges significantly from the official CBN rate.',
    'Fuel Subsidy': 'Government payments to keep petrol prices artificially low. Removed by Tinubu in June 2023, causing prices to triple overnight.',
    'Debt Per Capita': 'Total public debt divided by population. Each Nigerian notionally carries ~$430 in public debt (2025).',
    'Fiscal Deficit': 'The gap between government revenue and spending. When spending exceeds revenue, the deficit is financed by borrowing.',
}

DEBT_FACTS = [
    "Nigeria's debt has grown 170% in the last 10 years.",
    "Each Nigerian carries approximately $430 in public debt.",
    "64% of federal revenue goes to servicing debt — not building roads or schools.",
    "Nigeria's debt doubles roughly every 5 years at current rates.",
    "The Ways & Means securitization added N22.7T to debt overnight in 2023.",
    "Nigeria pays more in debt service than it spends on health and education combined.",
    "At $99B, Nigeria's debt is larger than the GDP of 140+ countries.",
    "In 1999, Nigeria's total debt was $37B — it has nearly tripled in 26 years.",
    "Nigeria's debt-to-GDP ratio (35%) looks low, but debt-to-revenue is the real crisis.",
    "The naira has lost 94% of its value against the dollar since 1999.",
    "A minimum wage worker could buy 150 litres of petrol in 1999 — only 67 today.",
    "China holds $3.8B of Nigeria's external debt through Exim Bank loans.",
    "Nigeria's reserves peaked at $53B in 2008 — still haven't recovered 17 years later.",
    "Obasanjo is the only president who reduced Nigeria's total debt stock.",
    "Buhari added more debt ($50B) than all other presidents combined.",
]

GLOBAL_RANKINGS = [
    {'metric': 'Total Debt Stock', 'rank': 50, 'of': 195, 'value': '$99B',
     'top': 'USA ($34T)', 'bottom': 'Tuvalu ($24M)',
     'context': 'Mid-range globally but high for a lower-middle-income country'},
    {'metric': 'Debt-to-GDP Ratio', 'rank': 120, 'of': 195, 'value': '35%',
     'top': 'Japan (264%)', 'bottom': 'Brunei (2%)',
     'context': 'Low ratio — but misleading when revenue is the real constraint'},
    {'metric': 'Debt Service / Revenue', 'rank': 8, 'of': 195, 'value': '64%',
     'top': 'Sri Lanka (95%)', 'bottom': 'Norway (2%)',
     'context': 'Among the worst globally — most revenue services debt, not citizens'},
    {'metric': 'External Reserves', 'rank': 38, 'of': 195, 'value': '$45.7B',
     'top': 'China ($3.4T)', 'bottom': 'Sao Tome ($0.04B)',
     'context': 'Recovering but still below the 2008 peak of $53B'},
    {'metric': 'Inflation Rate', 'rank': 25, 'of': 195, 'value': '15.2%',
     'top': 'Venezuela (400%+)', 'bottom': 'Switzerland (0.4%)',
     'context': 'Falling from the 2024 peak of 31.4% but still elevated'},
    {'metric': 'Debt Per Capita', 'rank': 140, 'of': 195, 'value': '$430',
     'top': 'Japan ($75K)', 'bottom': 'Timor-Leste ($7)',
     'context': 'Low per person, but 230M people amplifies the total'},
    {'metric': 'GDP Size', 'rank': 40, 'of': 195, 'value': '$285B',
     'top': 'USA ($28T)', 'bottom': 'Tuvalu ($0.06B)',
     'context': "Africa's largest economy — dropped from 26th after naira devaluation"},
    {'metric': 'Population', 'rank': 6, 'of': 195, 'value': '230M',
     'top': 'India (1.44B)', 'bottom': 'Vatican City (800)',
     'context': "Africa's most populous — projected world #3 by 2050"},
]

DEBT_PURPOSE = {
    'Obasanjo': {'Capital Projects': 30, 'Recurrent Spending': 45, 'Debt Refinancing': 15, 'Social Services': 10},
    "Yar'Adua": {'Capital Projects': 35, 'Recurrent Spending': 40, 'Debt Refinancing': 10, 'Social Services': 15},
    'Jonathan': {'Capital Projects': 25, 'Recurrent Spending': 45, 'Debt Refinancing': 20, 'Social Services': 10},
    'Buhari': {'Capital Projects': 20, 'Recurrent Spending': 35, 'Debt Refinancing': 35, 'Social Services': 10},
    'Tinubu': {'Capital Projects': 15, 'Recurrent Spending': 40, 'Debt Refinancing': 35, 'Social Services': 10},
}

CALCULATOR_ITEMS = [
    {'name': 'Teacher Salaries (1 year)', 'cost_ngn': 1200000, 'icon': 'person-workspace'},
    {'name': 'Boreholes (Clean Water)', 'cost_ngn': 3000000, 'icon': 'droplet-half'},
    {'name': 'Primary Schools', 'cost_ngn': 50000000, 'icon': 'building'},
    {'name': 'Primary Health Centres', 'cost_ngn': 100000000, 'icon': 'hospital'},
    {'name': 'Affordable Homes', 'cost_ngn': 15000000, 'icon': 'house-door'},
    {'name': 'Solar Street Lights', 'cost_ngn': 500000, 'icon': 'lightbulb'},
    {'name': 'University Scholarships (4yr)', 'cost_ngn': 4000000, 'icon': 'mortarboard'},
    {'name': 'Ambulances', 'cost_ngn': 25000000, 'icon': 'truck'},
]

STATE_ZONES = {
    'North West': ['Sokoto', 'Zamfara', 'Katsina', 'Kaduna', 'Kano', 'Jigawa', 'Kebbi'],
    'North East': ['Borno', 'Yobe', 'Bauchi', 'Gombe', 'Adamawa', 'Taraba'],
    'North Central': ['Niger', 'Kwara', 'Kogi', 'Benue', 'Plateau', 'Nasarawa', 'FCT'],
    'South West': ['Lagos', 'Ogun', 'Oyo', 'Osun', 'Ondo', 'Ekiti'],
    'South East': ['Anambra', 'Enugu', 'Ebonyi', 'Abia', 'Imo'],
    'South South': ['Edo', 'Delta', 'Bayelsa', 'Rivers', 'Cross River', 'Akwa Ibom'],
}


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

        label = f"{pres.start_year}–{pres.end_year or 'present'}"
        pres_summaries.append(build_pres_summary(pres, prev_last, last, label))

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

    # Ticker-by-year data for timeline slider
    ticker_by_year = []
    for d in all_data:
        per_cap = round(d.total_debt_usd * 1e9 / (d.population * 1e6)) if d.population else 0
        ds_pct = round(d.debt_service_ngn_tn / d.federal_revenue_ngn_tn * 100, 1) \
            if d.debt_service_ngn_tn and d.federal_revenue_ngn_tn else None
        ticker_by_year.append({
            'year': d.year, 'total_debt': d.total_debt_usd,
            'reserves': d.external_reserves_usd, 'fx': d.exchange_rate_official,
            'fx_parallel': d.exchange_rate_parallel or d.exchange_rate_official,
            'petrol': d.petrol_price, 'diesel': d.diesel_price,
            'debt_to_gdp': d.debt_to_gdp, 'inflation': d.inflation_rate,
            'oil_price': d.oil_price_usd, 'population': d.population,
            'per_capita': per_cap, 'debt_service_pct': ds_pct,
            'gdp': d.gdp_usd,
        })

    # Debt per second (based on last year's increase)
    debt_per_second = 0
    if len(all_data) >= 2:
        last_two = all_data[-2:]
        annual_increase_usd = (last_two[1].total_debt_usd - last_two[0].total_debt_usd) * 1e9
        debt_per_second = annual_increase_usd / (365.25 * 24 * 3600)

    # Milestone: days to $100B
    milestone_target = 100.0
    days_to_milestone = None
    if latest and latest.total_debt_usd < milestone_target and debt_per_second > 0:
        remaining_usd = (milestone_target - latest.total_debt_usd) * 1e9
        days_to_milestone = int(remaining_usd / (debt_per_second * 86400))

    return render_template('index.html',
                           presidents=presidents,
                           pres_summaries=pres_summaries,
                           latest=latest,
                           per_citizen_debt=per_citizen_debt,
                           debt_service_pct=debt_service_pct,
                           debt_per_second=debt_per_second,
                           days_to_milestone=days_to_milestone,
                           debt_facts=DEBT_FACTS,
                           timeline=timeline,
                           ticker_by_year=ticker_by_year,
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


# ══════════════════════════════════════════════════════════════════════════════
# HELPER: build presidential summary (reused by index and compare)
# ══════════════════════════════════════════════════════════════════════════════

def build_pres_summary(pres, prev_last, last, years_label):
    """Build a presidential summary dict from inherited/left data points."""
    debt_change = last.total_debt_usd - prev_last.total_debt_usd
    reserves_change = last.external_reserves_usd - prev_last.external_reserves_usd

    ds_pct_start = None
    if prev_last.debt_service_ngn_tn and prev_last.federal_revenue_ngn_tn:
        ds_pct_start = prev_last.debt_service_ngn_tn / prev_last.federal_revenue_ngn_tn * 100
    ds_pct_end = None
    if last.debt_service_ngn_tn and last.federal_revenue_ngn_tn:
        ds_pct_end = last.debt_service_ngn_tn / last.federal_revenue_ngn_tn * 100

    litres_start = prev_last.minimum_wage / prev_last.petrol_price if prev_last.minimum_wage and prev_last.petrol_price else None
    litres_end = last.minimum_wage / last.petrol_price if last.minimum_wage and last.petrol_price else None

    return {
        'president': pres,
        'first': prev_last, 'last': last,
        'years': years_label,
        'debt_inherited': prev_last.total_debt_usd,
        'debt_left': last.total_debt_usd,
        'debt_change': debt_change,
        'debt_change_pct': (debt_change / prev_last.total_debt_usd * 100) if prev_last.total_debt_usd else 0,
        'reserves_start': prev_last.external_reserves_usd,
        'reserves_end': last.external_reserves_usd,
        'reserves_change': reserves_change,
        'fx_start': prev_last.exchange_rate_official,
        'fx_end': last.exchange_rate_official,
        'fx_change_pct': ((last.exchange_rate_official - prev_last.exchange_rate_official) / prev_last.exchange_rate_official * 100) if prev_last.exchange_rate_official else 0,
        'petrol_start': prev_last.petrol_price,
        'petrol_end': last.petrol_price,
        'gdp_start': prev_last.gdp_usd,
        'gdp_end': last.gdp_usd,
        'inflation_start': prev_last.inflation_rate,
        'inflation_end': last.inflation_rate,
        'ds_pct_start': ds_pct_start,
        'ds_pct_end': ds_pct_end,
        'litres_start': litres_start,
        'litres_end': litres_end,
    }


@app.route('/borrowing')
def borrowing():
    presidents = President.query.order_by(President.start_year).all()
    all_data = EconomicData.query.order_by(EconomicData.year).all()
    latest_year = all_data[-1].year if all_data else 2025

    pres_data = {}
    for pres in presidents:
        pres_data[pres.id] = [d for d in all_data if d.president_id == pres.id]

    borrowing_list = []
    for i, pres in enumerate(presidents):
        pdata = pres_data[pres.id]
        if not pdata:
            continue

        # Inherited = previous president's last data point
        if i > 0 and pres_data.get(presidents[i-1].id):
            prev_last = pres_data[presidents[i-1].id][-1]
        else:
            prev_last = pdata[0]

        last = pdata[-1]
        inherited = prev_last.total_debt_usd
        left = last.total_debt_usd
        debt_added = left - inherited
        years_in_office = (pres.end_year or 2025) - pres.start_year
        if years_in_office < 1:
            years_in_office = 1
        annual_rate = debt_added / years_in_office
        growth_pct = (debt_added / inherited * 100) if inherited else 0

        # External vs domestic split
        ext_added = last.external_debt_usd - prev_last.external_debt_usd
        dom_inherited_usd = (prev_last.domestic_debt_ngn_tn * 1000 / prev_last.exchange_rate_official) if prev_last.exchange_rate_official else 0
        dom_left_usd = (last.domestic_debt_ngn_tn * 1000 / last.exchange_rate_official) if last.exchange_rate_official else 0
        dom_added_usd = dom_left_usd - dom_inherited_usd

        # Year-by-year
        yearly = []
        max_change = 0
        for j, d in enumerate(pdata):
            if j == 0:
                prev_total = inherited
            else:
                prev_total = pdata[j-1].total_debt_usd
            change = d.total_debt_usd - prev_total
            if abs(change) > max_change:
                max_change = abs(change)
            yearly.append({'year': d.year, 'total': d.total_debt_usd, 'change': round(change, 1)})

        is_incumbent = pres.end_year is None

        borrowing_list.append({
            'name': pres.name,
            'initials': pres.photo_initials,
            'party': pres.party,
            'party_color': pres.party_color,
            'start': pres.start_year,
            'end': pres.end_year or 'present',
            'years_in_office': years_in_office,
            'is_incumbent': is_incumbent,
            'inherited': round(inherited, 1),
            'left': round(left, 1),
            'debt_added': round(debt_added, 1),
            'annual_rate': round(annual_rate, 1),
            'growth_pct': round(growth_pct, 1),
            'ext_added': round(ext_added, 1),
            'dom_added_usd': round(dom_added_usd, 1),
            'd2g_inherited': prev_last.debt_to_gdp,
            'd2g_left': last.debt_to_gdp,
            'inherited_label': 'Inherited' if i > 0 else 'Start',
            'left_label': 'So Far' if is_incumbent else 'Left',
            'added_label': 'Added So Far' if is_incumbent else 'Net Added',
            'yearly': yearly,
            'max_change': round(max_change, 1),
        })

    # Ranked by debt added (highest first)
    borrowing_ranked = sorted(borrowing_list, key=lambda b: b['debt_added'], reverse=True)

    return render_template('borrowing.html',
                           borrowing=borrowing_list,
                           borrowing_ranked=borrowing_ranked,
                           borrowing_json=borrowing_list,
                           latest_year=latest_year,
                           debt_purpose=DEBT_PURPOSE)


@app.route('/compare')
def compare():
    presidents = President.query.order_by(President.start_year).all()
    all_data = EconomicData.query.order_by(EconomicData.year).all()

    p1_id = request.args.get('p1', 1, type=int)
    p2_id = request.args.get('p2', 5, type=int)

    pres_data = {}
    for pres in presidents:
        pres_data[pres.id] = [d for d in all_data if d.president_id == pres.id]

    summaries = {}
    yearly = {}
    for pid in [p1_id, p2_id]:
        pres = next((p for p in presidents if p.id == pid), presidents[0])
        pdata = pres_data.get(pres.id, [])
        if not pdata:
            continue
        idx = next((i for i, p in enumerate(presidents) if p.id == pres.id), 0)
        if idx > 0 and pres_data.get(presidents[idx-1].id):
            prev_last = pres_data[presidents[idx-1].id][-1]
        else:
            prev_last = pdata[0]
        last = pdata[-1]
        label = f"{pres.start_year}–{pres.end_year or 'present'}"
        summaries[pid] = build_pres_summary(pres, prev_last, last, label)
        yearly[pid] = [(d.year, d.total_debt_usd) for d in pdata]

    return render_template('compare.html',
                           presidents=presidents,
                           p1=summaries.get(p1_id, summaries.get(presidents[0].id)),
                           p2=summaries.get(p2_id, summaries.get(presidents[-1].id)),
                           p1_yearly=yearly.get(p1_id, []),
                           p2_yearly=yearly.get(p2_id, []))


@app.route('/africa')
def africa():
    return render_template('africa.html', peers=AFRICA_PEERS)


@app.route('/breakdown')
def breakdown():
    return render_template('breakdown.html', data=DEBT_BREAKDOWN)


@app.route('/states')
def states():
    sorted_states = sorted(STATE_DEBTS, key=lambda s: s['total'], reverse=True)
    top10 = [(s['name'], s['domestic'], s['external']) for s in sorted_states[:10]]
    # Build zone data for map
    state_lookup = {s['name']: s for s in sorted_states}
    zones_data = {}
    for zone, names in STATE_ZONES.items():
        zones_data[zone] = [state_lookup[n] for n in names if n in state_lookup]
    max_total = sorted_states[0]['total'] if sorted_states else 1
    return render_template('states.html', states=sorted_states, top10=top10,
                           zones_data=zones_data, max_total=max_total)


@app.route('/quiz')
def quiz():
    return render_template('quiz.html', questions=QUIZ_QUESTIONS)


@app.route('/embed')
def embed():
    latest = EconomicData.query.order_by(EconomicData.year.desc()).first()
    per_citizen = round(latest.total_debt_usd * 1e9 / (latest.population * 1e6)) if latest and latest.population else 0
    base_url = request.url_root.replace('http://', 'https://').rstrip('/')
    return render_template('embed.html', latest=latest, per_citizen=per_citizen, base_url=base_url)


@app.route('/embed-code')
def embed_code():
    base_url = request.url_root.replace('http://', 'https://').rstrip('/')
    return render_template('embed_code.html', base_url=base_url)


@app.route('/subscribe', methods=['POST'])
def subscribe():
    email = (request.form.get('email') or '').strip().lower()
    flash_msg = ''
    flash_type = 'error'
    if not email or not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        flash_msg = 'Please enter a valid email address.'
    else:
        existing = Subscriber.query.filter_by(email=email).first()
        if existing:
            flash_msg = 'You are already subscribed!'
            flash_type = 'success'
        else:
            db.session.add(Subscriber(email=email))
            db.session.commit()
            flash_msg = 'Subscribed successfully! You\'ll receive monthly updates.'
            flash_type = 'success'
    # Redirect back to referrer or home
    referrer = request.referrer or '/'
    # Pass flash via query params (simple approach, no session needed)
    sep = '&' if '?' in referrer else '?'
    return redirect(referrer)


@app.route('/robots.txt')
def robots_txt():
    lines = [
        "User-agent: *", "Allow: /", "Disallow: /api/",
        f"Sitemap: {request.url_root.replace('http://', 'https://').rstrip('/')}/sitemap.xml",
    ]
    return Response("\n".join(lines), mimetype="text/plain")


@app.route('/projection')
def projection():
    all_data = EconomicData.query.order_by(EconomicData.year).all()
    latest = all_data[-1]
    # Calculate 5-year CAGR for base growth rate
    recent = [d for d in all_data if d.year >= latest.year - 5]
    if len(recent) >= 2:
        first_val = recent[0].total_debt_usd
        last_val = recent[-1].total_debt_usd
        span = recent[-1].year - recent[0].year
        base_growth = round(((last_val / first_val) ** (1 / span) - 1) * 100, 1) if span > 0 and first_val > 0 else 10.0
    else:
        base_growth = 10.0
    return render_template('projection.html',
                           base_growth=base_growth,
                           current_debt=latest.total_debt_usd,
                           current_year=latest.year,
                           hist_years=[d.year for d in all_data],
                           hist_debt=[d.total_debt_usd for d in all_data])


@app.route('/timeline')
def timeline_page():
    all_data = EconomicData.query.order_by(EconomicData.year).all()
    presidents = President.query.order_by(President.start_year).all()
    eras = [{'name': p.name.split()[-1], 'start': p.start_year,
             'end': p.end_year or 2026, 'color': p.party_color} for p in presidents]
    tl = {
        'years': [d.year for d in all_data],
        'total_debt': [d.total_debt_usd for d in all_data],
        'reserves': [d.external_reserves_usd for d in all_data],
        'fx_official': [d.exchange_rate_official for d in all_data],
        'petrol': [d.petrol_price for d in all_data],
    }
    return render_template('timeline.html', events=HISTORICAL_EVENTS,
                           timeline=tl, eras=eras)


@app.route('/glossary')
def glossary():
    return render_template('glossary.html', glossary=GLOSSARY)


@app.route('/admin', methods=['GET', 'POST'])
def admin():
    admin_pw = os.environ.get('ADMIN_PASSWORD', 'debt-admin-2026')
    msg = None
    msg_type = None

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'login':
            if request.form.get('password') == admin_pw:
                # Simple cookie-based auth
                resp = redirect(url_for('admin'))
                resp.set_cookie('admin_auth', admin_pw, max_age=3600, httponly=True,
                                samesite='Lax')
                return resp
            msg = 'Incorrect password.'
            msg_type = 'error'

        elif request.cookies.get('admin_auth') == admin_pw:
            if action == 'add_data':
                try:
                    dp = EconomicData(
                        president_id=int(request.form['president_id']),
                        year=int(request.form['year']),
                        external_debt_usd=float(request.form.get('external_debt_usd') or 0),
                        domestic_debt_ngn_tn=float(request.form.get('domestic_debt_ngn_tn') or 0),
                        total_debt_usd=float(request.form.get('total_debt_usd') or 0),
                        external_reserves_usd=float(request.form.get('external_reserves_usd') or 0),
                        exchange_rate_official=float(request.form.get('exchange_rate_official') or 0),
                        exchange_rate_parallel=float(request.form.get('exchange_rate_parallel') or 0),
                        petrol_price=float(request.form.get('petrol_price') or 0),
                        diesel_price=float(request.form.get('diesel_price') or 0),
                        gdp_usd=float(request.form.get('gdp_usd') or 0),
                        gdp_growth=float(request.form.get('gdp_growth') or 0),
                        population=float(request.form.get('population') or 0),
                        debt_to_gdp=float(request.form.get('debt_to_gdp') or 0),
                        federal_revenue_ngn_tn=float(request.form.get('federal_revenue_ngn_tn') or 0),
                        debt_service_ngn_tn=float(request.form.get('debt_service_ngn_tn') or 0),
                        inflation_rate=float(request.form.get('inflation_rate') or 0),
                        oil_price_usd=float(request.form.get('oil_price_usd') or 0),
                        minimum_wage=float(request.form.get('minimum_wage') or 0),
                    )
                    db.session.add(dp)
                    db.session.commit()
                    msg = f'Data for {dp.year} added successfully.'
                    msg_type = 'success'
                except Exception as e:
                    msg = f'Error: {str(e)}'
                    msg_type = 'error'

            elif action == 'delete_data':
                dp_id = request.form.get('dp_id')
                dp = EconomicData.query.get(int(dp_id))
                if dp:
                    db.session.delete(dp)
                    db.session.commit()
                    msg = f'Data point for {dp.year} deleted.'
                    msg_type = 'success'

    authed = request.cookies.get('admin_auth') == admin_pw
    presidents = President.query.order_by(President.start_year).all() if authed else []
    data = EconomicData.query.order_by(EconomicData.year.desc()).all() if authed else []
    subscribers = Subscriber.query.order_by(Subscriber.subscribed_at.desc()).all() if authed else []

    return render_template('admin.html', authed=authed, presidents=presidents,
                           data=data, subscribers=subscribers, msg=msg, msg_type=msg_type)


@app.route('/admin/logout')
def admin_logout():
    resp = redirect(url_for('admin'))
    resp.delete_cookie('admin_auth')
    return resp


# ══════════════════════════════════════════════════════════════════════════════
# AI HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_ai_client():
    if not HAS_ANTHROPIC:
        return None
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    return anthropic.Anthropic(api_key=api_key) if api_key else None


def build_data_context():
    """Build text summary of all economic data for AI context."""
    all_data = EconomicData.query.order_by(EconomicData.year).all()
    presidents = President.query.order_by(President.start_year).all()
    lines = ["NIGERIA ECONOMIC DATA (1999-2025):\n"]
    for d in all_data:
        pres = next((p for p in presidents if p.id == d.president_id), None)
        pn = pres.name if pres else '?'
        lines.append(
            f"{d.year} ({pn}): Debt=${d.total_debt_usd}B (ext=${d.external_debt_usd}B, "
            f"dom=N{d.domestic_debt_ngn_tn}T), Reserves=${d.external_reserves_usd}B, "
            f"FX=N{d.exchange_rate_official}/$ (parallel N{d.exchange_rate_parallel}/$), "
            f"Petrol=N{d.petrol_price}/L, GDP=${d.gdp_usd}B ({d.gdp_growth}% growth), "
            f"Pop={d.population}M, Debt/GDP={d.debt_to_gdp}%, "
            f"Revenue=N{d.federal_revenue_ngn_tn}T, DebtSvc=N{d.debt_service_ngn_tn}T, "
            f"Inflation={d.inflation_rate}%, Oil=${d.oil_price_usd}/bbl, MinWage=N{d.minimum_wage}/mo"
        )
    lines.append("\nPRESIDENTS:")
    for p in presidents:
        lines.append(f"- {p.name} ({p.party}, {p.start_year}-{p.end_year or 'present'}): {p.note}")
    lines.append("\nKEY FACTS:")
    for fact in DEBT_FACTS:
        lines.append(f"- {fact}")
    return "\n".join(lines)


AI_SYSTEM_PROMPT = """You are the Nigeria Debt Clock AI Analyst — an expert on Nigerian public finance, debt management, and macroeconomics.

You have access to verified economic data from 1999 to 2025 covering 5 presidential administrations.

{context}

RULES:
- Answer questions accurately using the data provided
- Be concise but insightful — aim for 2-4 paragraphs max
- Use specific numbers and cite the year
- When comparing, use percentage changes and per-capita figures
- Clearly distinguish between data-backed statements and estimates
- Format: $XB for USD billions, NX for Naira amounts
- Use analogies Nigerians can relate to
- Be balanced and non-partisan — present facts, not political opinions
- If asked about something outside your data, say so clearly"""


def ask_ai(user_message, system_override=None, model="claude-haiku-4-5-20251001"):
    client = get_ai_client()
    if not client:
        return {"error": "AI features require ANTHROPIC_API_KEY to be configured."}
    context = build_data_context()
    system = (system_override or AI_SYSTEM_PROMPT).format(context=context)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content": user_message}]
        )
        return {"response": response.content[0].text}
    except Exception as e:
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# AI ROUTES
# ══════════════════════════════════════════════════════════════════════════════

FREE_DAILY_LIMIT = 10

@app.route('/chat')
def chat_page():
    return render_template('chat.html')


@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.get_json() or {}
    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({"error": "Please enter a question."}), 400
    if len(message) > 500:
        return jsonify({"error": "Question too long (max 500 characters)."}), 400
    # Rate limiting via cookie count (checked client-side, enforced here)
    result = ask_ai(message)
    return jsonify(result)


@app.route('/what-if')
def what_if_page():
    return render_template('what_if.html')


@app.route('/api/what-if', methods=['POST'])
def api_what_if():
    data = request.get_json() or {}
    scenario = (data.get('scenario') or '').strip()
    if not scenario:
        return jsonify({"error": "Please describe a scenario."}), 400
    prompt = f"""Analyze this economic scenario for Nigeria:

"{scenario}"

Provide a structured analysis with:
1. **Immediate Impact** — What happens in the first 6 months
2. **Debt Effect** — How this affects Nigeria's total debt trajectory
3. **Currency Impact** — Effect on naira exchange rate
4. **Inflation & Prices** — Impact on consumer prices and fuel costs
5. **Reserves** — Effect on external reserves
6. **Overall Assessment** — One-sentence verdict

Use specific numbers from the data to ground your analysis. Be realistic, not sensational."""
    system = """You are a Nigerian macroeconomic analyst. Analyze hypothetical scenarios using real data.

{context}

Give structured analysis with realistic projections based on historical patterns. Use markdown formatting."""
    result = ask_ai(prompt, system_override=system)
    return jsonify(result)


@app.route('/api/explain', methods=['POST'])
def api_explain():
    data = request.get_json() or {}
    metric = (data.get('metric') or '').strip()
    value = data.get('value', '')
    year = data.get('year', '')
    if not metric:
        return jsonify({"error": "No metric specified."}), 400
    prompt = (
        f"Explain this economic metric in simple terms for a Nigerian audience:\n\n"
        f"**{metric}**: {value} ({year})\n\n"
        f"In 3-4 sentences: What does this number mean? Is it good or bad? "
        f"How does it compare historically? What does it mean for ordinary Nigerians?"
    )
    result = ask_ai(prompt)
    return jsonify(result)


@app.route('/ai-report')
def ai_report_page():
    all_data = EconomicData.query.order_by(EconomicData.year).all()
    latest = all_data[-1] if all_data else None
    return render_template('ai_report.html', latest=latest)


@app.route('/api/ai-report', methods=['POST'])
def api_ai_report():
    prompt = """Generate a professional weekly debt briefing for Nigeria. Structure it as:

## Nigeria Debt Briefing — Weekly Update

### Key Numbers This Week
(Use the latest 2025 data)

### Trend Analysis
(Compare 2025 vs 2024 — what's improving, what's deteriorating)

### Debt Sustainability Warning Signs
(Highlight any concerning ratios or trajectories)

### What to Watch
(3 things that could change the debt trajectory in the next quarter)

### Bottom Line
(One-paragraph executive summary for busy readers)

Use specific data points. Be analytical, not sensational. Format with markdown."""
    system = """You are a senior economic analyst writing a professional debt briefing for institutional investors, journalists, and policy makers interested in Nigeria.

{context}

Write in a professional, Bloomberg-style tone. Use specific numbers and percentages."""
    result = ask_ai(prompt, system_override=system, model="claude-haiku-4-5-20251001")
    return jsonify(result)


@app.route('/ai-cards')
def ai_cards_page():
    return render_template('ai_cards.html')


@app.route('/api/ai-cards', methods=['POST'])
def api_ai_cards():
    prompt = """Generate exactly 6 shareable social media insights about Nigeria's debt. Each should be:
- One punchy sentence (under 140 characters)
- Include a specific number
- Be surprising or thought-provoking
- Suitable for Twitter/X

Return them as a JSON array of strings. Only return the JSON array, nothing else.
Example format: ["Insight 1", "Insight 2", ...]"""
    result = ask_ai(prompt)
    if 'response' in result:
        # Try to parse JSON from the response
        text = result['response'].strip()
        # Extract JSON array if wrapped in markdown
        if '```' in text:
            text = text.split('```')[1].strip()
            if text.startswith('json'):
                text = text[4:].strip()
        try:
            import json
            cards = json.loads(text)
            return jsonify({"cards": cards})
        except Exception:
            return jsonify({"cards": [text]})
    return jsonify(result)


# ══════════════════════════════════════════════════════════════════════════════
# API v1 (Public API + AI Query Layer)
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/docs')
def api_docs():
    return render_template('api_docs.html')


@app.route('/api/v1/data')
def api_v1_data():
    """Public JSON API — no key required for raw data."""
    all_data = EconomicData.query.order_by(EconomicData.year).all()
    year = request.args.get('year', type=int)
    if year:
        all_data = [d for d in all_data if d.year == year]
    return jsonify([{
        'year': d.year, 'total_debt_usd': d.total_debt_usd,
        'external_debt_usd': d.external_debt_usd,
        'domestic_debt_ngn_tn': d.domestic_debt_ngn_tn,
        'external_reserves_usd': d.external_reserves_usd,
        'exchange_rate_official': d.exchange_rate_official,
        'exchange_rate_parallel': d.exchange_rate_parallel,
        'petrol_price': d.petrol_price, 'diesel_price': d.diesel_price,
        'gdp_usd': d.gdp_usd, 'gdp_growth': d.gdp_growth,
        'population': d.population, 'debt_to_gdp': d.debt_to_gdp,
        'inflation_rate': d.inflation_rate, 'oil_price_usd': d.oil_price_usd,
        'federal_revenue_ngn_tn': d.federal_revenue_ngn_tn,
        'debt_service_ngn_tn': d.debt_service_ngn_tn,
        'minimum_wage': d.minimum_wage,
    } for d in all_data])


@app.route('/api/v1/query', methods=['POST'])
def api_v1_query():
    """AI-powered natural language query — requires API key."""
    api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
    if not api_key:
        return jsonify({"error": "Missing API key. Include X-API-Key header or api_key param.",
                        "docs": "/api/docs"}), 401
    key_record = ApiKey.query.filter_by(key=api_key, is_active=True).first()
    if not key_record:
        return jsonify({"error": "Invalid or inactive API key."}), 403
    data = request.get_json() or {}
    query = (data.get('query') or '').strip()
    if not query:
        return jsonify({"error": "Missing 'query' field in request body."}), 400
    # Track usage
    key_record.queries_used = (key_record.queries_used or 0) + 1
    db.session.commit()
    result = ask_ai(query)
    result['usage'] = {'queries_used': key_record.queries_used}
    return jsonify(result)


@app.route('/api/v1/keys', methods=['POST'])
def api_v1_create_key():
    """Self-service API key generation."""
    data = request.get_json() or request.form
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip()
    if not email or not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
        return jsonify({"error": "Valid email required."}), 400
    # Check if email already has a key
    existing = ApiKey.query.filter_by(email=email).first()
    if existing:
        return jsonify({"key": existing.key, "message": "Existing key returned.",
                        "note": "Store this key securely — it won't be shown again."})
    new_key = f"ndc_{secrets.token_hex(24)}"
    db.session.add(ApiKey(key=new_key, name=name, email=email))
    db.session.commit()
    return jsonify({"key": new_key, "message": "API key created.",
                    "note": "Store this key securely — it won't be shown again."})


@app.route('/calculator')
def calculator():
    sorted_states = sorted(STATE_DEBTS, key=lambda s: s['total'], reverse=True)
    return render_template('calculator.html', states=sorted_states,
                           items=CALCULATOR_ITEMS)


@app.route('/chart-builder')
def chart_builder():
    all_data = EconomicData.query.order_by(EconomicData.year).all()
    tl = {
        'years': [d.year for d in all_data],
        'total_debt': [d.total_debt_usd for d in all_data],
        'external_debt': [d.external_debt_usd for d in all_data],
        'reserves': [d.external_reserves_usd for d in all_data],
        'fx_official': [d.exchange_rate_official for d in all_data],
        'fx_parallel': [d.exchange_rate_parallel for d in all_data],
        'petrol': [d.petrol_price for d in all_data],
        'gdp': [d.gdp_usd for d in all_data],
        'debt_to_gdp': [d.debt_to_gdp for d in all_data],
        'inflation': [d.inflation_rate for d in all_data],
        'oil_price': [d.oil_price_usd for d in all_data],
        'population': [d.population for d in all_data],
        'revenue': [d.federal_revenue_ngn_tn for d in all_data],
        'debt_service': [d.debt_service_ngn_tn for d in all_data],
    }
    return render_template('chart_builder.html', timeline=tl)


@app.route('/rankings')
def rankings():
    return render_template('rankings.html', rankings=GLOBAL_RANKINGS)


@app.route('/report')
def report():
    year = request.args.get('year', None, type=int)
    all_data = EconomicData.query.order_by(EconomicData.year).all()
    years = [d.year for d in all_data]
    selected = None
    prev = None
    if year and year in years:
        idx = years.index(year)
        selected = all_data[idx]
        prev = all_data[idx - 1] if idx > 0 else None
    else:
        selected = all_data[-1]
        prev = all_data[-2] if len(all_data) >= 2 else None
        year = selected.year
    pres = President.query.filter(
        President.start_year <= year,
        db.or_(President.end_year >= year, President.end_year.is_(None))
    ).first()
    return render_template('report.html', selected=selected, prev=prev,
                           year=year, president=pres, all_years=years)


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.route('/sitemap.xml')
def sitemap_xml():
    base = request.url_root.replace('http://', 'https://').rstrip('/')
    pages = ['/', '/borrowing', '/compare', '/breakdown', '/states', '/africa',
             '/quiz', '/projection', '/timeline', '/glossary', '/calculator',
             '/chart-builder', '/rankings', '/report']
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for page in pages:
        pri = '1.0' if page == '/' else '0.8'
        xml.append(f'<url><loc>{base}{page}</loc><changefreq>weekly</changefreq><priority>{pri}</priority></url>')
    xml.append('</urlset>')
    return Response("\n".join(xml), mimetype="application/xml")


if __name__ == '__main__':
    app.run(debug=True, port=5001)
