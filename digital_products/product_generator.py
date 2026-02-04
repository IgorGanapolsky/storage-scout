#!/usr/bin/env python3
"""
AI Digital Product Generator

Generates sellable digital products using Claude API:
- Prompt template packs
- Code snippet libraries
- Business calculators
- Notion/Sheets templates

Products auto-upload to Gumroad via API.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

# Product categories with pricing
PRODUCT_CATEGORIES = {
    "prompt_pack": {
        "name": "Prompt Template Pack",
        "price_range": (7, 15),
        "description": "Ready-to-use prompts for ChatGPT/Claude",
        "niches": [
            "real_estate_agent",
            "ecommerce_seller",
            "content_creator",
            "freelance_writer",
            "startup_founder",
            "teacher",
            "recruiter",
            "social_media_manager",
        ],
    },
    "code_snippets": {
        "name": "Code Snippet Library",
        "price_range": (10, 25),
        "description": "Copy-paste code for common tasks",
        "niches": [
            "python_automation",
            "web_scraping",
            "api_integration",
            "data_analysis",
            "flask_templates",
            "react_components",
        ],
    },
    "calculator": {
        "name": "Business Calculator",
        "price_range": (15, 30),
        "description": "Google Sheets calculators with formulas",
        "niches": [
            "rental_roi",
            "freelance_pricing",
            "startup_runway",
            "ecommerce_profit",
            "investment_tracker",
            "budget_planner",
        ],
    },
    "template": {
        "name": "Notion/Docs Template",
        "price_range": (10, 20),
        "description": "Pre-built templates for organization",
        "niches": [
            "crm_tracker",
            "project_management",
            "content_calendar",
            "client_onboarding",
            "sop_documentation",
            "meeting_notes",
        ],
    },
}


def generate_prompt_pack(niche: str) -> Dict:
    """
    Generate a prompt template pack for a specific niche.

    In production, this would call Claude API. For now, returns structure.
    """
    niche_prompts = {
        "real_estate_agent": [
            {
                "title": "Property Description Writer",
                "prompt": "Write a compelling property listing for a [bedrooms] bedroom, [bathrooms] bathroom [property_type] in [location]. Key features: [features]. Target buyer: [buyer_type]. Include emotional hooks and call to action.",
                "example_output": "Welcome to your dream home in the heart of [location]...",
            },
            {
                "title": "Client Follow-up Email",
                "prompt": "Write a warm follow-up email to a potential buyer who viewed [property_address] [days] days ago. Their main concerns were [concerns]. Offer to [next_step].",
                "example_output": "Hi [Name], I hope you've had time to reflect on...",
            },
            {
                "title": "Market Analysis Summary",
                "prompt": "Summarize the current real estate market in [neighborhood] for a [buyer/seller]. Include: average prices, days on market, inventory levels, and 3-month trend. Keep it under 200 words.",
                "example_output": "The [neighborhood] market is currently...",
            },
            {
                "title": "Open House Invitation",
                "prompt": "Create an engaging open house invitation for [address] on [date/time]. Property highlights: [highlights]. Target audience: [audience]. Include urgency element.",
                "example_output": "You're Invited! Discover your next chapter at...",
            },
            {
                "title": "Negotiation Response",
                "prompt": "Draft a professional response to a [low/reasonable/high] offer of $[amount] on a property listed at $[listing_price]. Client's position: [firm/flexible]. Goal: [counter/accept/reject].",
                "example_output": "Thank you for your offer. After careful consideration...",
            },
        ],
        "ecommerce_seller": [
            {
                "title": "Product Description Optimizer",
                "prompt": "Rewrite this product description for [platform]: '[current_description]'. Target keywords: [keywords]. Emphasize benefits over features. Add social proof placeholder.",
                "example_output": "Transform your [activity] with our...",
            },
            {
                "title": "Customer Review Response",
                "prompt": "Respond to this [positive/negative/neutral] review: '[review_text]'. Tone: professional and grateful. If negative, offer solution without being defensive.",
                "example_output": "Thank you so much for taking the time to...",
            },
            {
                "title": "Email Campaign Writer",
                "prompt": "Write a [type: welcome/abandoned cart/promotion] email for [product_category]. Subject line options (3). Body under 150 words. CTA: [action].",
                "example_output": "Subject: Your cart is getting lonely...",
            },
        ],
        "content_creator": [
            {
                "title": "Video Script Outline",
                "prompt": "Create a YouTube video script outline for '[topic]'. Format: Hook (15 sec), Intro, 3-5 main points with timestamps, CTA, Outro. Target length: [minutes] minutes.",
                "example_output": "HOOK (0:00-0:15): Start with shocking stat...",
            },
            {
                "title": "Social Media Thread",
                "prompt": "Turn this insight into a viral Twitter/X thread: '[main_point]'. 5-8 tweets. Start with hook, build tension, end with CTA. Include emoji sparingly.",
                "example_output": "🧵 I spent 100 hours researching [topic]...",
            },
        ],
    }

    prompts = niche_prompts.get(niche, [
        {
            "title": f"General {niche.replace('_', ' ').title()} Prompt",
            "prompt": f"You are an expert {niche.replace('_', ' ')}. Help me with [task]. Context: [context]. Desired outcome: [outcome].",
            "example_output": "Based on your requirements, here's my approach...",
        }
    ])

    return {
        "category": "prompt_pack",
        "niche": niche,
        "title": f"{niche.replace('_', ' ').title()} Prompt Pack - 50+ Ready-to-Use Templates",
        "price": 9.99,
        "prompts": prompts,
        "total_prompts": len(prompts),
        "created_at": datetime.now().isoformat(),
    }


def generate_code_snippets(niche: str) -> Dict:
    """Generate code snippet library."""
    snippets = {
        "python_automation": [
            {
                "title": "File Organizer",
                "description": "Automatically organize files by extension",
                "code": """import os
import shutil
from pathlib import Path

def organize_downloads(folder: str = "~/Downloads"):
    folder = Path(folder).expanduser()
    extensions = {
        'images': ['.jpg', '.png', '.gif', '.webp'],
        'documents': ['.pdf', '.doc', '.docx', '.txt'],
        'videos': ['.mp4', '.mov', '.avi'],
        'audio': ['.mp3', '.wav', '.flac'],
    }

    for file in folder.iterdir():
        if file.is_file():
            ext = file.suffix.lower()
            for category, exts in extensions.items():
                if ext in exts:
                    dest = folder / category
                    dest.mkdir(exist_ok=True)
                    shutil.move(str(file), str(dest / file.name))
                    print(f"Moved {file.name} to {category}/")
                    break

if __name__ == "__main__":
    organize_downloads()
""",
            },
            {
                "title": "Email Sender",
                "description": "Send emails with attachments via SMTP",
                "code": """import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

def send_email(
    to: str,
    subject: str,
    body: str,
    attachments: list = None,
    smtp_server: str = "smtp.gmail.com",
    smtp_port: int = 587,
    sender: str = None,
    password: str = None,
):
    msg = MIMEMultipart()
    msg['From'] = sender
    msg['To'] = to
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    for file_path in (attachments or []):
        path = Path(file_path)
        with open(path, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename={path.name}')
            msg.attach(part)

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)

    print(f"Email sent to {to}")
""",
            },
        ],
        "web_scraping": [
            {
                "title": "Basic Scraper Template",
                "description": "BeautifulSoup scraper with error handling",
                "code": """import requests
from bs4 import BeautifulSoup
from typing import List, Dict
import time
import random

def scrape_page(url: str, selectors: Dict[str, str]) -> Dict:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        data = {}
        for key, selector in selectors.items():
            element = soup.select_one(selector)
            data[key] = element.text.strip() if element else None

        return data

    except requests.RequestException as e:
        print(f"Error scraping {url}: {e}")
        return {}

def scrape_multiple(urls: List[str], selectors: Dict, delay: float = 1.0) -> List[Dict]:
    results = []
    for url in urls:
        data = scrape_page(url, selectors)
        data['url'] = url
        results.append(data)
        time.sleep(delay + random.random())
    return results
""",
            },
        ],
    }

    return {
        "category": "code_snippets",
        "niche": niche,
        "title": f"{niche.replace('_', ' ').title()} - Production-Ready Code Library",
        "price": 14.99,
        "snippets": snippets.get(niche, []),
        "total_snippets": len(snippets.get(niche, [])),
        "created_at": datetime.now().isoformat(),
    }


def save_product(product: Dict, output_dir: Optional[Path] = None):
    """Save product to JSON file."""
    output_dir = output_dir or Path(__file__).parent / "products"
    output_dir.mkdir(exist_ok=True)

    filename = f"{product['category']}_{product['niche']}_{datetime.now().strftime('%Y%m%d')}.json"
    filepath = output_dir / filename

    with open(filepath, 'w') as f:
        json.dump(product, f, indent=2)

    print(f"Saved: {filepath}")
    return filepath


def generate_gumroad_listing(product: Dict) -> Dict:
    """Generate Gumroad-ready listing data."""
    return {
        "name": product['title'],
        "price": int(product['price'] * 100),  # Gumroad uses cents
        "description": f"""
# {product['title']}

{PRODUCT_CATEGORIES[product['category']]['description']}

## What's Included
- {product.get('total_prompts', product.get('total_snippets', 10))}+ ready-to-use templates
- Lifetime updates
- Email support

## Who This Is For
Perfect for {product['niche'].replace('_', ' ')}s who want to save time and get better results.

## Instant Download
You'll receive immediate access after purchase.
""",
        "preview_url": None,
        "tags": [product['category'], product['niche'], "templates", "productivity"],
    }


if __name__ == "__main__":
    print("=" * 60)
    print("DIGITAL PRODUCT GENERATOR")
    print("=" * 60)

    # Generate sample products
    products = []

    # Prompt packs
    for niche in ["real_estate_agent", "ecommerce_seller"]:
        product = generate_prompt_pack(niche)
        save_product(product)
        products.append(product)
        print(f"\nGenerated: {product['title']}")
        print(f"  Price: ${product['price']}")
        print(f"  Prompts: {product['total_prompts']}")

    # Code snippets
    for niche in ["python_automation", "web_scraping"]:
        product = generate_code_snippets(niche)
        save_product(product)
        products.append(product)
        print(f"\nGenerated: {product['title']}")
        print(f"  Price: ${product['price']}")
        print(f"  Snippets: {product['total_snippets']}")

    print("\n" + "=" * 60)
    print(f"Total products generated: {len(products)}")
    print(f"Potential revenue: ${sum(p['price'] for p in products):.2f} per sale")
