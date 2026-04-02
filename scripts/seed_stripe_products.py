#!/usr/bin/env python3
"""Seed Stripe products and prices for AscenAI subscription plans."""

import os
import stripe
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')
if not stripe.api_key:
    raise RuntimeError("STRIPE_SECRET_KEY not found in .env")

PLANS = [
    {
        "name": "AscenAI Text Growth",
        "plan_id": "text_growth",
        "price": 4900,
        "interval": "month",
    },
    {
        "name": "AscenAI Voice Growth",
        "plan_id": "voice_growth",
        "price": 9900,
        "interval": "month",
    },
    {
        "name": "AscenAI Voice Business",
        "plan_id": "voice_business",
        "price": 19900,
        "interval": "month",
    },
]

def seed_products():
    """Create products and prices in Stripe."""
    created = {}
    
    for plan in PLANS:
        product = stripe.Product.create(
            name=plan["name"],
            metadata={"plan_id": plan["plan_id"]},
        )
        
        price = stripe.Price.create(
            product=product.id,
            unit_amount=plan["price"],
            currency="usd",
            recurring={"interval": plan["interval"]},
        )
        
        created[plan["plan_id"]] = {
            "product_id": product.id,
            "price_id": price.id,
        }
        
        print(f"Created: {plan['name']}")
        print(f"  Product ID: {product.id}")
        print(f"  Price ID: {price.id}")
    
    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    
    env_vars = {}
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and '=' in line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    env_vars[key] = value
    
    for plan_id, data in created.items():
        env_vars[f"STRIPE_{plan_id.upper()}_PRODUCT_ID"] = data["product_id"]
        env_vars[f"STRIPE_{plan_id.upper()}_PRICE_ID"] = data["price_id"]
    
    with open(env_path, 'a') as f:
        f.write("\n# Stripe Price IDs (auto-generated)\n")
        for key, value in env_vars.items():
            if key.startswith("STRIPE_") and ("PRODUCT_ID" in key or "PRICE_ID" in key):
                f.write(f"{key}={value}\n")
    
    print("\n✅ All products created successfully!")
    print("Price IDs have been added to .env")

if __name__ == "__main__":
    seed_products()
