import requests
import json
from duckduckgo_search import DDGS
import os
from dotenv import load_dotenv
load_dotenv()

# Configuration
POLYMARKET_GAMMA_API = "https://gamma-api.polymarket.com/markets"

# Get a FREE API key from Google AI Studio (https://aistudio.google.com/)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

def fetch_polymarket_market(slug):
    """Fetches target market data from Polymarket (Free & Public)."""
    try:
        response = requests.get(f"{POLYMARKET_GAMMA_API}?slug={slug}")
        if response.status_code == 200 and response.json():
            market_data = response.json()[0]
            prices = json.loads(market_data.get("outcomePrices", "[]"))
            
            return {
                "title": market_data.get("title"),
                "resolution_rules": market_data.get("resolutionCriteria"),
                "yes_price": float(prices[0]) if prices else None
            }
    except Exception as e:
        print(f"Error fetching Polymarket data: {e}")
    return None

def fetch_free_news(query):
    """Fetches the latest web data using DuckDuckGo (100% Free, No Key)."""
    try:
        print(f"Searching the live web for: '{query}'...")
        with DDGS() as ddgs:
            # Get the top 5 latest text results from the web
            results = [r['body'] for r in ddgs.text(query, max_results=5)]
            return "\n".join(results)
    except Exception as e:
        print(f"Failed to fetch live news: {e}")
        return "No recent news context available."

def analyze_with_free_ai(market_info, context_data):
    """Uses Gemini's free tier to analyze the market and return JSON."""
    
    prompt = f"""
    You are an expert prediction market analyst. 
    Analyze the following Polymarket contract and the recent real-world data provided.
    
    Market: {market_info['title']}
    Rules: {market_info['resolution_rules']}
    Current Market Price for YES: ${market_info['yes_price']} (implies a {market_info['yes_price']*100}% chance)
    
    Recent Live Web Context:
    {context_data}
    
    Based strictly on the data, what is the actual mathematical probability (0.0 to 1.0) that this resolves to YES?
    You must reply ONLY with a raw JSON object. Do not include markdown formatting like ```json. 
    Format: {{"estimated_probability": 0.75, "reasoning": "your short explanation"}}
    """
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    
    try:
        response = requests.post(GEMINI_API_URL, json=payload, headers={"Content-Type": "application/json"})
        result = response.json()
        
        # Extract text response from Gemini's structure
        raw_text = result['candidates'][0]['content']['parts'][0]['text'].strip()
        
        # Parse it into a python dictionary
        analysis = json.loads(raw_text)
        return analysis
    except Exception as e:
        print(f"AI Analysis failed: {e}")
        return None

def evaluate_trading_edge(slug, min_edge=0.05):
    """Calculates your mathematical edge for $0 cost."""
    market = fetch_polymarket_market(slug)
    if not market or market['yes_price'] is None:
        print("Could not retrieve valid market data.")
        return

    # 1. Gather 100% free live web data
    context = fetch_free_news(market['title'])
    
    # 2. Get Free AI analysis
    ai_analysis = analyze_with_free_ai(market, context)
    if not ai_analysis:
        return
        
    p_ai = ai_analysis["estimated_probability"]
    p_market = market["yes_price"]
    edge = p_ai - p_market
    
    print(f"\n--- Free AI Analysis Results ---")
    print(f"Market Price (Implied): {p_market*100:.1f}%")
    print(f"AI Estimated Price:     {p_ai*100:.1f}%")
    print(f"Calculated Edge:        {edge*100:+.1f}%")
    print(f"AI Reasoning: {ai_analysis['reasoning']}")
    
    # 3. Output Trade Signal
    if edge >= min_edge:
        print(f"🚀 SIGNAL: BUY YES. Market underpricing by {edge*100:.1f}%.")
    elif edge <= -min_edge:
        print(f"📉 SIGNAL: BUY NO. Market overpricing by {abs(edge)*100:.1f}%.")
    else:
        print("⏸️ SIGNAL: NO EDGE. Market is efficient.")

# Example Usage
if __name__ == "__main__":
    # Paste an active market slug here (the end part of a Polymarket URL)
    example_slug = "will-bitcoin-hit-100k-in-2026" 
    evaluate_trading_edge(example_slug)