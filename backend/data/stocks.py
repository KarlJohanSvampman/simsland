# =========================================================
# STOCK CATALOG
# 40 fictional publicly-traded companies across 8 sectors
# =========================================================

STOCK_CATALOG = [

    # -------------------------------------------------
    # TECH (8)
    # -------------------------------------------------
    {
        "ticker": "NXVT",
        "name": "Nexovate Technologies",
        "sector": "tech",
        "base_price": 142.50,
        "volatility": 0.022,
        "market_cap": "large",
        "news_sensitivity": 0.85,
        "description": "Cloud infrastructure and enterprise SaaS platform"
    },
    {
        "ticker": "CYLX",
        "name": "Cylux Semiconductors",
        "sector": "tech",
        "base_price": 88.30,
        "volatility": 0.028,
        "market_cap": "mid",
        "news_sensitivity": 0.90,
        "description": "AI accelerator chips and custom silicon"
    },
    {
        "ticker": "DRVM",
        "name": "Drivum Autonomous",
        "sector": "tech",
        "base_price": 210.00,
        "volatility": 0.032,
        "market_cap": "large",
        "news_sensitivity": 0.95,
        "description": "Self-driving vehicle software and sensor systems"
    },
    {
        "ticker": "QRIX",
        "name": "Qrix Analytics",
        "sector": "tech",
        "base_price": 55.80,
        "volatility": 0.020,
        "market_cap": "small",
        "news_sensitivity": 0.70,
        "description": "Business intelligence and data analytics SaaS"
    },
    {
        "ticker": "VLTX",
        "name": "Voltex Cybersecurity",
        "sector": "tech",
        "base_price": 76.40,
        "volatility": 0.018,
        "market_cap": "mid",
        "news_sensitivity": 0.80,
        "description": "Zero-trust network security and threat detection"
    },
    {
        "ticker": "PRXM",
        "name": "Proxima Robotics",
        "sector": "tech",
        "base_price": 34.20,
        "volatility": 0.035,
        "market_cap": "small",
        "news_sensitivity": 0.88,
        "description": "Industrial and domestic robotics systems"
    },
    {
        "ticker": "MNTH",
        "name": "Menthix Computing",
        "sector": "tech",
        "base_price": 128.90,
        "volatility": 0.016,
        "market_cap": "large",
        "news_sensitivity": 0.75,
        "description": "Consumer hardware and wearable computing devices"
    },
    {
        "ticker": "ELVN",
        "name": "Elven Networks",
        "sector": "tech",
        "base_price": 47.60,
        "volatility": 0.021,
        "market_cap": "mid",
        "news_sensitivity": 0.72,
        "description": "5G infrastructure and telecom equipment"
    },

    # -------------------------------------------------
    # RETAIL (6)
    # -------------------------------------------------
    {
        "ticker": "KRTN",
        "name": "Karton Group",
        "sector": "retail",
        "base_price": 62.10,
        "volatility": 0.014,
        "market_cap": "large",
        "news_sensitivity": 0.60,
        "description": "Discount retail chain with 4,000+ locations"
    },
    {
        "ticker": "VRDX",
        "name": "Verdaxa E-Commerce",
        "sector": "retail",
        "base_price": 318.50,
        "volatility": 0.018,
        "market_cap": "large",
        "news_sensitivity": 0.65,
        "description": "Online marketplace and same-day logistics"
    },
    {
        "ticker": "LMNR",
        "name": "Luminary Fashion",
        "sector": "retail",
        "base_price": 28.40,
        "volatility": 0.022,
        "market_cap": "small",
        "news_sensitivity": 0.55,
        "description": "Fast fashion and online apparel retail"
    },
    {
        "ticker": "HBTH",
        "name": "Hartbeck Home Goods",
        "sector": "retail",
        "base_price": 91.20,
        "volatility": 0.012,
        "market_cap": "mid",
        "news_sensitivity": 0.50,
        "description": "Furniture, décor, and home improvement retail"
    },
    {
        "ticker": "GRSL",
        "name": "Greensel Grocery",
        "sector": "retail",
        "base_price": 44.70,
        "volatility": 0.010,
        "market_cap": "mid",
        "news_sensitivity": 0.45,
        "description": "Supermarket and specialty food retail chain"
    },
    {
        "ticker": "SPKX",
        "name": "Sparkex Electronics Retail",
        "sector": "retail",
        "base_price": 38.90,
        "volatility": 0.016,
        "market_cap": "small",
        "news_sensitivity": 0.62,
        "description": "Consumer electronics retail and repair chain"
    },

    # -------------------------------------------------
    # ENERGY (5)
    # -------------------------------------------------
    {
        "ticker": "OXFL",
        "name": "Oxfall Petroleum",
        "sector": "energy",
        "base_price": 74.30,
        "volatility": 0.025,
        "market_cap": "large",
        "news_sensitivity": 0.90,
        "description": "Oil extraction, refining and distribution"
    },
    {
        "ticker": "SLRV",
        "name": "Solarvex Renewables",
        "sector": "energy",
        "base_price": 52.80,
        "volatility": 0.030,
        "market_cap": "mid",
        "news_sensitivity": 0.85,
        "description": "Solar panel manufacturing and energy grid projects"
    },
    {
        "ticker": "WNDP",
        "name": "Windport Energy",
        "sector": "energy",
        "base_price": 39.10,
        "volatility": 0.026,
        "market_cap": "mid",
        "news_sensitivity": 0.80,
        "description": "Offshore wind farm development and operation"
    },
    {
        "ticker": "NUCX",
        "name": "Nucleax Power",
        "sector": "energy",
        "base_price": 118.60,
        "volatility": 0.020,
        "market_cap": "large",
        "news_sensitivity": 0.95,
        "description": "Nuclear energy plants and small modular reactors"
    },
    {
        "ticker": "GRDX",
        "name": "Gridex Utilities",
        "sector": "energy",
        "base_price": 83.40,
        "volatility": 0.009,
        "market_cap": "large",
        "news_sensitivity": 0.55,
        "description": "National electricity grid distribution and smart meters"
    },

    # -------------------------------------------------
    # HEALTH (6)
    # -------------------------------------------------
    {
        "ticker": "MRVX",
        "name": "Marvex Pharmaceuticals",
        "sector": "health",
        "base_price": 167.20,
        "volatility": 0.030,
        "market_cap": "large",
        "news_sensitivity": 0.92,
        "description": "Drug development, oncology and rare disease treatments"
    },
    {
        "ticker": "BTRX",
        "name": "Biotrex Genomics",
        "sector": "health",
        "base_price": 41.50,
        "volatility": 0.040,
        "market_cap": "small",
        "news_sensitivity": 0.98,
        "description": "Gene therapy and CRISPR-based treatment research"
    },
    {
        "ticker": "MDIQ",
        "name": "Mediq Health Insurance",
        "sector": "health",
        "base_price": 295.80,
        "volatility": 0.012,
        "market_cap": "large",
        "news_sensitivity": 0.70,
        "description": "Health and dental insurance plans"
    },
    {
        "ticker": "CLNX",
        "name": "Clinnex Diagnostics",
        "sector": "health",
        "base_price": 58.90,
        "volatility": 0.022,
        "market_cap": "mid",
        "news_sensitivity": 0.82,
        "description": "Medical diagnostic devices and lab testing services"
    },
    {
        "ticker": "VRTN",
        "name": "Vertona Wellness",
        "sector": "health",
        "base_price": 22.30,
        "volatility": 0.018,
        "market_cap": "small",
        "news_sensitivity": 0.60,
        "description": "Supplements, wearables, and preventive health apps"
    },
    {
        "ticker": "HSPX",
        "name": "Hospex Hospital Group",
        "sector": "health",
        "base_price": 134.70,
        "volatility": 0.014,
        "market_cap": "large",
        "news_sensitivity": 0.75,
        "description": "Private hospital network and surgical centers"
    },

    # -------------------------------------------------
    # FINANCE (5)
    # -------------------------------------------------
    {
        "ticker": "ARCB",
        "name": "Arcadia Bank",
        "sector": "finance",
        "base_price": 48.20,
        "volatility": 0.016,
        "market_cap": "large",
        "news_sensitivity": 0.80,
        "description": "Retail and commercial banking services"
    },
    {
        "ticker": "VNTG",
        "name": "Vantage Capital",
        "sector": "finance",
        "base_price": 182.40,
        "volatility": 0.018,
        "market_cap": "large",
        "news_sensitivity": 0.85,
        "description": "Investment banking, asset management and trading"
    },
    {
        "ticker": "FNIX",
        "name": "Finix Payments",
        "sector": "finance",
        "base_price": 94.60,
        "volatility": 0.022,
        "market_cap": "mid",
        "news_sensitivity": 0.78,
        "description": "Digital payments infrastructure and crypto settlement"
    },
    {
        "ticker": "ISLR",
        "name": "Isolar Insurance",
        "sector": "finance",
        "base_price": 67.80,
        "volatility": 0.011,
        "market_cap": "mid",
        "news_sensitivity": 0.65,
        "description": "Life, home, and auto insurance underwriting"
    },
    {
        "ticker": "MRKF",
        "name": "Merkof Microfinance",
        "sector": "finance",
        "base_price": 15.40,
        "volatility": 0.028,
        "market_cap": "small",
        "news_sensitivity": 0.70,
        "description": "Peer-to-peer lending and micro-credit services"
    },

    # -------------------------------------------------
    # CONSUMER (5)
    # -------------------------------------------------
    {
        "ticker": "DLVX",
        "name": "Delvox Auto",
        "sector": "consumer",
        "base_price": 236.10,
        "volatility": 0.020,
        "market_cap": "large",
        "news_sensitivity": 0.80,
        "description": "Electric and hybrid vehicle manufacturer"
    },
    {
        "ticker": "BVRG",
        "name": "Beverage House",
        "sector": "consumer",
        "base_price": 72.90,
        "volatility": 0.010,
        "market_cap": "large",
        "news_sensitivity": 0.50,
        "description": "Non-alcoholic beverages, energy drinks and water brands"
    },
    {
        "ticker": "TRVX",
        "name": "Travex Hospitality",
        "sector": "consumer",
        "base_price": 58.30,
        "volatility": 0.025,
        "market_cap": "mid",
        "news_sensitivity": 0.75,
        "description": "Hotels, resorts and travel booking platform"
    },
    {
        "ticker": "FDBK",
        "name": "Foodback Restaurants",
        "sector": "consumer",
        "base_price": 31.60,
        "volatility": 0.016,
        "market_cap": "small",
        "news_sensitivity": 0.55,
        "description": "Fast casual restaurant chain and delivery service"
    },
    {
        "ticker": "ENTX",
        "name": "Entrix Gaming",
        "sector": "consumer",
        "base_price": 84.50,
        "volatility": 0.032,
        "market_cap": "mid",
        "news_sensitivity": 0.82,
        "description": "Video game publisher and esports platform"
    },

    # -------------------------------------------------
    # MEDIA (3)
    # -------------------------------------------------
    {
        "ticker": "STRM",
        "name": "Streamora Media",
        "sector": "media",
        "base_price": 148.20,
        "volatility": 0.022,
        "market_cap": "large",
        "news_sensitivity": 0.75,
        "description": "Video streaming platform with 80M subscribers"
    },
    {
        "ticker": "PBLX",
        "name": "Publixar News Group",
        "sector": "media",
        "base_price": 24.80,
        "volatility": 0.018,
        "market_cap": "small",
        "news_sensitivity": 0.85,
        "description": "Digital news, investigative journalism and podcasts"
    },
    {
        "ticker": "ADVX",
        "name": "Advexo Advertising",
        "sector": "media",
        "base_price": 67.30,
        "volatility": 0.020,
        "market_cap": "mid",
        "news_sensitivity": 0.70,
        "description": "Programmatic advertising and data-driven marketing"
    },

    # -------------------------------------------------
    # INDUSTRIAL (4)
    # -------------------------------------------------
    {
        "ticker": "BLDX",
        "name": "Buildex Construction",
        "sector": "industrial",
        "base_price": 54.70,
        "volatility": 0.015,
        "market_cap": "mid",
        "news_sensitivity": 0.65,
        "description": "Commercial and residential construction"
    },
    {
        "ticker": "MNFX",
        "name": "Manufex Systems",
        "sector": "industrial",
        "base_price": 88.10,
        "volatility": 0.013,
        "market_cap": "mid",
        "news_sensitivity": 0.60,
        "description": "Industrial automation and factory systems"
    },
    {
        "ticker": "TRNS",
        "name": "Transove Logistics",
        "sector": "industrial",
        "base_price": 42.50,
        "volatility": 0.017,
        "market_cap": "mid",
        "news_sensitivity": 0.68,
        "description": "Freight shipping, warehousing and last-mile delivery"
    },
    {
        "ticker": "CHMX",
        "name": "Chemex Materials",
        "sector": "industrial",
        "base_price": 36.80,
        "volatility": 0.019,
        "market_cap": "small",
        "news_sensitivity": 0.72,
        "description": "Specialty chemicals, polymers and advanced materials"
    },
]

# Fast lookup by ticker
STOCKS_BY_TICKER = {s["ticker"]: s for s in STOCK_CATALOG}

def get_stock(ticker):
    return STOCKS_BY_TICKER.get(ticker)

def stocks_by_sector(sector):
    return [s for s in STOCK_CATALOG if s["sector"] == sector]
