import logging
from decimal import Decimal
from sqlalchemy.orm import Session
from backend.app.database import engine, Base
from backend.app.models import Product, MerchantPolicy

logger = logging.getLogger("setu.seed")

def seed_db(db: Session):
    """
    Seeds the database with default demo products and merchant policies.
    """
    # Create tables if they do not exist
    Base.metadata.create_all(bind=engine)

    # 1. Seed Merchant Policies if empty
    policy_count = db.query(MerchantPolicy).count()
    if policy_count == 0:
        policy = MerchantPolicy(
            max_discount_percent=Decimal("15.00"),  # max 15% discount for normal negotiations
            min_margin_percent=Decimal("15.00"),    # min 15% margin
            max_auto_order_amount=Decimal("2000.00"), # max ₹2000 for auto approval
            require_approval_above=Decimal("2000.00"), # require approval above ₹2000
            policy_version="policy_v1.0",
            active=True
        )
        db.add(policy)
        db.commit()
        logger.info("[SEED] Default merchant policy added.")

    # 2. Seed / Upsert Products
    products = [
            # --- WIRELESS EARBUDS ---
            Product(
                id=1,
                name="Wireless Earbuds Pro",
                category="Audio",
                description="High-fidelity audio earbuds with active noise cancellation and spatial sound.",
                price=Decimal("1599.00"),
                cost=Decimal("1050.00"),
                min_selling_price=Decimal("1399.00"),
                inventory=25,
                attributes={"brand": "SoundWave", "color": "Carbon Black"},
                related_product_ids=[2, 7, 8],
                active=True
            ),
            Product(
                id=2,
                name="Premium Charging Case",
                category="Accessories",
                description="Fast charging protective case for Wireless Earbuds.",
                price=Decimal("399.00"),
                cost=Decimal("200.00"),
                min_selling_price=Decimal("299.00"),
                inventory=20,
                attributes={"brand": "SoundWave", "output": "5W"},
                related_product_ids=[1],
                active=True
            ),
            Product(
                id=3,
                name="Earbuds & Charging Case Bundle",
                category="Bundles",
                description="Discounted bundle including Wireless Earbuds Pro and Premium Charging Case.",
                price=Decimal("1998.00"),
                cost=Decimal("1250.00"),
                min_selling_price=Decimal("1699.00"),
                inventory=20,
                attributes={"brand": "SoundWave", "bundle_components": [1, 2]},
                related_product_ids=[],
                active=True
            ),
            Product(
                id=4,
                name="Premium Soundbar",
                category="Audio",
                description="High-end immersive theater soundbar.",
                price=Decimal("5000.00"),
                cost=Decimal("3500.00"),
                min_selling_price=Decimal("4200.00"),
                inventory=10,
                attributes={"brand": "SoundWave", "channels": "5.1"},
                related_product_ids=[],
                active=True
            ),
            Product(
                id=5,
                name="Out of Stock Charger",
                category="Accessories",
                description="Temporary out of stock wall charger.",
                price=Decimal("499.00"),
                cost=Decimal("350.00"),
                min_selling_price=Decimal("420.00"),
                inventory=0,
                attributes={"brand": "SoundWave"},
                related_product_ids=[],
                active=True
            ),
            Product(
                id=6,
                name="Deactivated Speaker",
                category="Audio",
                description="Older active speaker - discontinued.",
                price=Decimal("999.00"),
                cost=Decimal("700.00"),
                min_selling_price=Decimal("850.00"),
                inventory=5,
                attributes={"brand": "SoundWave"},
                related_product_ids=[],
                active=False
            ),
            Product(
                id=7,
                name="USB-C Fast Charging Cable",
                category="Accessories",
                description="High-durability nylon-braided USB-C fast charging cable (1.2m).",
                price=Decimal("299.00"),
                cost=Decimal("100.00"),
                min_selling_price=Decimal("199.00"),
                inventory=50,
                attributes={"brand": "VoltCharge", "length": "1.2m"},
                related_product_ids=[1, 11, 12, 31],
                active=True
            ),
            Product(
                id=8,
                name="Extended Warranty for Earbuds",
                category="Accessories",
                description="1-year additional breakdown protection plan for Wireless Earbuds.",
                price=Decimal("199.00"),
                cost=Decimal("50.00"),
                min_selling_price=Decimal("149.00"),
                inventory=100,
                attributes={"brand": "SetuShield", "duration": "1 year"},
                related_product_ids=[1],
                active=True
            ),
            Product(
                id=9,
                name="Wireless Earbuds Lite",
                category="Audio",
                description="Budget-friendly wireless earbuds with reliable sound.",
                price=Decimal("999.00"),
                cost=Decimal("600.00"),
                min_selling_price=Decimal("799.00"),
                inventory=35,
                attributes={"brand": "SoundWave", "color": "Frost White"},
                related_product_ids=[2, 7, 8],
                active=True
            ),

            # --- MOBILE PHONES ---
            Product(
                id=11,
                name="Budget Smartphone",
                category="Mobile Phones",
                description="Affordable smartphone with 6.5 inch display and long battery life.",
                price=Decimal("9999.00"),
                cost=Decimal("7500.00"),
                min_selling_price=Decimal("8999.00"),
                inventory=15,
                attributes={"brand": "NovaTech", "ram": "4GB", "storage": "64GB"},
                related_product_ids=[13, 14, 15, 16],
                active=True
            ),
            Product(
                id=12,
                name="Mid-range Smartphone",
                category="Mobile Phones",
                description="Premium-tier mid-range phone with 5G connectivity and triple camera setup.",
                price=Decimal("18999.00"),
                cost=Decimal("14000.00"),
                min_selling_price=Decimal("16999.00"),
                inventory=12,
                attributes={"brand": "NovaTech", "ram": "8GB", "storage": "128GB"},
                related_product_ids=[13, 14, 15, 16, 17],
                active=True
            ),
            Product(
                id=13,
                name="Premium Phone Case",
                category="Accessories",
                description="Shockproof protective clear case for NovaTech smartphones.",
                price=Decimal("499.00"),
                cost=Decimal("150.00"),
                min_selling_price=Decimal("349.00"),
                inventory=40,
                attributes={"brand": "GuardX"},
                related_product_ids=[11, 12],
                active=True
            ),
            Product(
                id=14,
                name="Tempered Glass Screen Protector",
                category="Accessories",
                description="9H hardness ultra-clear tempered glass screen protector.",
                price=Decimal("299.00"),
                cost=Decimal("80.00"),
                min_selling_price=Decimal("199.00"),
                inventory=60,
                attributes={"brand": "GuardX"},
                related_product_ids=[11, 12],
                active=True
            ),
            Product(
                id=15,
                name="Super Fast Charger",
                category="Accessories",
                description="33W USB-C GaN fast wall charger.",
                price=Decimal("999.00"),
                cost=Decimal("400.00"),
                min_selling_price=Decimal("699.00"),
                inventory=25,
                attributes={"brand": "VoltCharge", "power": "33W"},
                related_product_ids=[11, 12],
                active=True
            ),
            Product(
                id=16,
                name="20000mAh Power Bank",
                category="Accessories",
                description="High-capacity external battery pack with dual USB ports.",
                price=Decimal("1999.00"),
                cost=Decimal("900.00"),
                min_selling_price=Decimal("1499.00"),
                inventory=20,
                attributes={"brand": "VoltCharge"},
                related_product_ids=[11, 12],
                active=True
            ),
            Product(
                id=17,
                name="Extended Warranty for Phones",
                category="Accessories",
                description="1-year protection plan covering damage and repairs for smartphones.",
                price=Decimal("999.00"),
                cost=Decimal("250.00"),
                min_selling_price=Decimal("799.00"),
                inventory=100,
                attributes={"brand": "SetuShield", "duration": "1 year"},
                related_product_ids=[11, 12],
                active=True
            ),

            # --- COMPUTING ---
            Product(
                id=21,
                name="Budget Laptop",
                category="Computing",
                description="Daily driver laptop powered by Intel Core i3, ideal for studies and tasks.",
                price=Decimal("29999.00"),
                cost=Decimal("23000.00"),
                min_selling_price=Decimal("27499.00"),
                inventory=8,
                attributes={"brand": "ApexTech", "ram": "8GB", "storage": "256GB SSD"},
                related_product_ids=[23, 24, 25, 26],
                active=True
            ),
            Product(
                id=22,
                name="Performance Laptop",
                category="Computing",
                description="High-speed laptop powered by Intel Core i7, suited for coding, design, and work.",
                price=Decimal("59999.00"),
                cost=Decimal("45000.00"),
                min_selling_price=Decimal("54999.00"),
                inventory=5,
                attributes={"brand": "ApexTech", "ram": "16GB", "storage": "512GB SSD"},
                related_product_ids=[23, 24, 25, 26],
                active=True
            ),
            Product(
                id=23,
                name="Wireless Optical Mouse",
                category="Accessories",
                description="Ergonomic 2.4GHz wireless mouse with adjustable DPI.",
                price=Decimal("699.00"),
                cost=Decimal("250.00"),
                min_selling_price=Decimal("499.00"),
                inventory=30,
                attributes={"brand": "ApexTech"},
                related_product_ids=[21, 22],
                active=True
            ),
            Product(
                id=24,
                name="Protective Laptop Bag",
                category="Accessories",
                description="Waterproof sleeve backpack for laptops up to 15.6 inches.",
                price=Decimal("1499.00"),
                cost=Decimal("600.00"),
                min_selling_price=Decimal("1099.00"),
                inventory=18,
                attributes={"brand": "ApexTech"},
                related_product_ids=[21, 22],
                active=True
            ),
            Product(
                id=25,
                name="Slim Mechanical Keyboard",
                category="Accessories",
                description="Tenkeyless mechanical gaming keyboard with tactile red switches.",
                price=Decimal("2499.00"),
                cost=Decimal("1100.00"),
                min_selling_price=Decimal("1899.00"),
                inventory=15,
                attributes={"brand": "ApexTech"},
                related_product_ids=[21, 22],
                active=True
            ),
            Product(
                id=26,
                name="Extended Warranty for Laptops",
                category="Accessories",
                description="1-year accidental and breakdown warranty for ApexTech laptops.",
                price=Decimal("2999.00"),
                cost=Decimal("1000.00"),
                min_selling_price=Decimal("2499.00"),
                inventory=50,
                attributes={"brand": "SetuShield", "duration": "1 year"},
                related_product_ids=[21, 22],
                active=True
            ),

            # --- WEARABLES ---
            Product(
                id=31,
                name="Fitness Smartwatch",
                category="Wearables",
                description="Fitness tracker smartwatch with heart rate monitor, GPS, and custom watch faces.",
                price=Decimal("4999.00"),
                cost=Decimal("3000.00"),
                min_selling_price=Decimal("3999.00"),
                inventory=12,
                attributes={"brand": "PulseFit", "waterproof": "IP68"},
                related_product_ids=[32, 33, 34],
                active=True
            ),
            Product(
                id=32,
                name="Sport Silicone Replacement Strap",
                category="Accessories",
                description="Soft, breathable sweatproof replacement strap for PulseFit smartwatch.",
                price=Decimal("499.00"),
                cost=Decimal("150.00"),
                min_selling_price=Decimal("349.00"),
                inventory=35,
                attributes={"brand": "PulseFit", "material": "Silicone"},
                related_product_ids=[31],
                active=True
            ),
            Product(
                id=33,
                name="Magnetic Watch Charging Cable",
                category="Accessories",
                description="USB magnetic replacement quick charging dock for PulseFit watches.",
                price=Decimal("599.00"),
                cost=Decimal("200.00"),
                min_selling_price=Decimal("449.00"),
                inventory=20,
                attributes={"brand": "PulseFit"},
                related_product_ids=[31],
                active=True
            ),
            Product(
                id=34,
                name="Accidental Damage Protection Plan",
                category="Accessories",
                description="1-year comprehensive accident and liquid damage replacement plan.",
                price=Decimal("699.00"),
                cost=Decimal("150.00"),
                min_selling_price=Decimal("499.00"),
                inventory=80,
                attributes={"brand": "SetuShield", "duration": "1 year"},
                related_product_ids=[31],
                active=True
            ),

            # --- EXPANDED CATALOG: MOBILE PHONES ---
            Product(
                id=41,
                name="Samsung Galaxy A15",
                category="Mobile Phones",
                description="Reliable smartphone with vibrant display and dual camera setup.",
                price=Decimal("12999.00"),
                cost=Decimal("10000.00"),
                min_selling_price=Decimal("11799.00"),
                inventory=15,
                attributes={"brand": "Samsung"},
                related_product_ids=[44, 45, 46],
                active=True
            ),
            Product(
                id=42,
                name="Redmi Note 13",
                category="Mobile Phones",
                description="Powerhouse smartphone with ultra-clear camera and fast charging.",
                price=Decimal("16999.00"),
                cost=Decimal("13000.00"),
                min_selling_price=Decimal("15499.00"),
                inventory=12,
                attributes={"brand": "Xiaomi"},
                related_product_ids=[44, 45, 46],
                active=True
            ),
            Product(
                id=43,
                name="Motorola G54",
                category="Mobile Phones",
                description="Sleek performance smartphone with long battery backup.",
                price=Decimal("14999.00"),
                cost=Decimal("11500.00"),
                min_selling_price=Decimal("13699.00"),
                inventory=10,
                attributes={"brand": "Motorola"},
                related_product_ids=[44, 45, 46],
                active=True
            ),
            Product(
                id=44,
                name="25W Fast Charger",
                category="Accessories",
                description="High-speed 25W wall charger adapter.",
                price=Decimal("1299.00"),
                cost=Decimal("500.00"),
                min_selling_price=Decimal("999.00"),
                inventory=50,
                attributes={"brand": "VoltCharge"},
                related_product_ids=[41, 42, 43],
                active=True
            ),
            Product(
                id=45,
                name="Mobile Protective Case",
                category="Accessories",
                description="Durable shockproof protective clear case.",
                price=Decimal("499.00"),
                cost=Decimal("150.00"),
                min_selling_price=Decimal("349.00"),
                inventory=40,
                attributes={"brand": "GuardX"},
                related_product_ids=[41, 42, 43],
                active=True
            ),
            Product(
                id=46,
                name="Tempered Glass",
                category="Accessories",
                description="Premium 9H hardness tempered glass screen protector.",
                price=Decimal("299.00"),
                cost=Decimal("80.00"),
                min_selling_price=Decimal("199.00"),
                inventory=60,
                attributes={"brand": "GuardX"},
                related_product_ids=[41, 42, 43],
                active=True
            ),

            # --- EXPANDED CATALOG: AUDIO ---
            Product(
                id=47,
                name="Wireless Earbuds",
                category="Audio",
                description="Comfortable fit true wireless stereo earbuds.",
                price=Decimal("1599.00"),
                cost=Decimal("1050.00"),
                min_selling_price=Decimal("1399.00"),
                inventory=25,
                attributes={"brand": "SoundWave"},
                related_product_ids=[49, 50],
                active=True
            ),
            Product(
                id=48,
                name="Premium Wireless Earbuds",
                category="Audio",
                description="High-fidelity audio earbuds with active noise cancellation.",
                price=Decimal("2999.00"),
                cost=Decimal("2000.00"),
                min_selling_price=Decimal("2499.00"),
                inventory=20,
                attributes={"brand": "SoundWave"},
                related_product_ids=[49, 50],
                active=True
            ),
            Product(
                id=49,
                name="Earbuds Charging Case",
                category="Accessories",
                description="Fast charging protective case for earbuds.",
                price=Decimal("499.00"),
                cost=Decimal("200.00"),
                min_selling_price=Decimal("399.00"),
                inventory=25,
                attributes={"brand": "SoundWave"},
                related_product_ids=[47, 48],
                active=True
            ),
            Product(
                id=50,
                name="Earbuds Protective Case",
                category="Accessories",
                description="Silicone protective sleeve for earbuds charging case.",
                price=Decimal("299.00"),
                cost=Decimal("100.00"),
                min_selling_price=Decimal("199.00"),
                inventory=30,
                attributes={"brand": "SoundWave"},
                related_product_ids=[47, 48],
                active=True
            ),
            Product(
                id=51,
                name="Bluetooth Speaker",
                category="Audio",
                description="Portable outdoor waterproof Bluetooth speaker.",
                price=Decimal("1999.00"),
                cost=Decimal("1200.00"),
                min_selling_price=Decimal("1699.00"),
                inventory=15,
                attributes={"brand": "SoundWave"},
                related_product_ids=[],
                active=True
            ),

            # --- EXPANDED CATALOG: COMPUTING ---
            Product(
                id=52,
                name="Wireless Keyboard",
                category="Computing",
                description="Sleek multi-device wireless chiclet keyboard.",
                price=Decimal("1499.00"),
                cost=Decimal("800.00"),
                min_selling_price=Decimal("1199.00"),
                inventory=20,
                attributes={"brand": "ApexTech"},
                related_product_ids=[53, 55],
                active=True
            ),
            Product(
                id=53,
                name="Wireless Mouse",
                category="Computing",
                description="Ergonomic silent optical wireless mouse.",
                price=Decimal("799.00"),
                cost=Decimal("300.00"),
                min_selling_price=Decimal("599.00"),
                inventory=30,
                attributes={"brand": "ApexTech"},
                related_product_ids=[52, 55],
                active=True
            ),
            Product(
                id=54,
                name="Laptop Backpack",
                category="Computing",
                description="Water-resistant laptop travel bag with USB charging port.",
                price=Decimal("1999.00"),
                cost=Decimal("800.00"),
                min_selling_price=Decimal("1499.00"),
                inventory=18,
                attributes={"brand": "ApexTech"},
                related_product_ids=[21, 22],
                active=True
            ),
            Product(
                id=55,
                name="USB-C Hub",
                category="Computing",
                description="5-in-1 multi-port adapter with HDMI, USB-A, and Power Delivery.",
                price=Decimal("999.00"),
                cost=Decimal("400.00"),
                min_selling_price=Decimal("799.00"),
                inventory=25,
                attributes={"brand": "ApexTech"},
                related_product_ids=[52, 53],
                active=True
            ),

            # --- EXPANDED CATALOG: WEARABLES ---
            Product(
                id=56,
                name="Smartwatch",
                category="Wearables",
                description="Advanced smartwatch with step tracker, heart rate monitor, and notifications.",
                price=Decimal("3999.00"),
                cost=Decimal("2500.00"),
                min_selling_price=Decimal("3299.00"),
                inventory=12,
                attributes={"brand": "PulseFit"},
                related_product_ids=[57],
                active=True
            ),
            Product(
                id=57,
                name="Watch Strap",
                category="Wearables",
                description="Breathable athletic replacement smartwatch watch strap.",
                price=Decimal("499.00"),
                cost=Decimal("150.00"),
                min_selling_price=Decimal("349.00"),
                inventory=35,
                attributes={"brand": "PulseFit"},
                related_product_ids=[56],
                active=True
            )
        ]
        
    # Safe Upsert Mechanism: Update if exists, insert if not.
    for p in products:
        existing = db.query(Product).filter(Product.id == p.id).first()
        if existing:
            existing.name = p.name
            existing.category = p.category
            existing.description = p.description
            existing.price = p.price
            existing.cost = p.cost
            existing.min_selling_price = p.min_selling_price
            existing.inventory = p.inventory
            existing.attributes = p.attributes
            existing.related_product_ids = p.related_product_ids
            existing.active = p.active
        else:
            db.add(p)
    db.commit()
    logger.info("[SEED] Catalog products synchronized successfully.")
