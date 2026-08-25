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
            max_discount_percent=Decimal("10.00"),  # max 10% discount
            min_margin_percent=Decimal("20.00"),    # min 20% margin
            max_auto_order_amount=Decimal("2000.00"), # max ₹2000 for auto approval
            require_approval_above=Decimal("2000.00"), # require approval above ₹2000
            policy_version="policy_v1.0",
            active=True
        )
        db.add(policy)
        db.commit()
        logger.info("[SEED] Default merchant policy added.")

    # 2. Seed Products if empty
    product_count = db.query(Product).count()
    if product_count == 0:
        products = [
            Product(
                id=1,
                name="Wireless Earbuds",
                category="Electronics",
                description="High-fidelity audio earbuds with noise cancellation.",
                price=Decimal("1599.00"),
                cost=Decimal("1050.00"),
                inventory=25,
                attributes={"brand": "SoundWave", "color": "Black"},
                related_product_ids=[2],
                active=True
            ),
            Product(
                id=2,
                name="Charging Case",
                category="Accessories",
                description="Fast charging protective case for Wireless Earbuds.",
                price=Decimal("399.00"),
                cost=Decimal("200.00"),
                inventory=20,
                attributes={"brand": "SoundWave", "output": "5W"},
                related_product_ids=[1],
                active=True
            ),
            Product(
                id=3,
                name="Earbuds & Charging Case Bundle",
                category="Bundles",
                description="Discounted bundle including Wireless Earbuds and Charging Case.",
                price=Decimal("1998.00"),
                cost=Decimal("1250.00"),
                inventory=20,
                attributes={"brand": "SoundWave", "bundle_components": [1, 2]},
                related_product_ids=[],
                active=True
            ),
            Product(
                id=4,
                name="Premium Soundbar",
                category="Electronics",
                description="High-end immersive theater soundbar.",
                price=Decimal("5000.00"),
                cost=Decimal("3500.00"),
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
                inventory=0,
                attributes={"brand": "SoundWave"},
                related_product_ids=[],
                active=True
            ),
            Product(
                id=6,
                name="Deactivated Speaker",
                category="Electronics",
                description="Older active speaker - discontinued.",
                price=Decimal("999.00"),
                cost=Decimal("700.00"),
                inventory=5,
                attributes={"brand": "SoundWave"},
                related_product_ids=[],
                active=False
            )
        ]
        for p in products:
            db.add(p)
        db.commit()
        logger.info("[SEED] Default catalog products added.")
