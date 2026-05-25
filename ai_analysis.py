import os
import re
import json
import requests
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Initialize the OpenAI Client
# It will automatically look for the OPENAI_API_KEY environment variable.
client = OpenAI()

def safe_parse(data):
    """Polymarket API sometimes returns JSON strings and sometimes lists. This handles both."""
    if isinstance(data, str):
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return []
    return data or []

def fetch_polymarket_data(url):
    """Extracts the event slug from the URL and fetches live data from the Gamma API."""
    match = re.search(r'/event/([^/?]+)', url)
    if not match:
        raise ValueError("Invalid Polymarket URL. Ensure it contains '/event/slug'")
    
    slug = match.group(1)
    
    # Polymarket's public API for event data
    api_url = f"https://gamma-api.polymarket.com/events?slug={slug}"
    headers = {"Accept": "application/json"}
    
    response = requests.get(api_url, headers=headers)
    response.raise_for_status()
    
    data = response.json()
    if not data:
        raise ValueError(f"No active data found for market slug: {slug}")
        
    return data[0]

def analyze_market_with_ai(url):
    print(f"Fetching live data for: {url}...")
    
    try:
        event_data = fetch_polymarket_data(url)
    except Exception as e:
        print(f"Error fetching Polymarket data: {e}")
        return None, None

    # Parse relevant market data to feed into the LLM context window
    title = event_data.get('title', 'Unknown Title')
    description = event_data.get('description', 'No description available.')
    markets = event_data.get('markets', [])
    
    market_summaries = []
    for market in markets:
        question = market.get('question', '')
        outcomes = safe_parse(market.get('outcomes', '[]'))
        prices = safe_parse(market.get('outcomePrices', '[]'))
        
        # Map each outcome to its current price/probability (e.g., {"Yes": "0.45", "No": "0.55"})
        outcome_data = {outcomes[i]: prices[i] for i in range(min(len(outcomes), len(prices)))}
        market_summaries.append({
            "market_question": question,
            "current_odds": outcome_data
        })

    # Construct the Prompt
    # We explicitly ask the model to output a strict JSON schema so we can extract the variables.
    prompt = f"""
    You are an expert prediction market analyst. Analyze the following live Polymarket event.
    
    Event Title: {title}
    Description: {description}
    Markets and Current Odds: {json.dumps(market_summaries, indent=2)}
    
    Provide a detailed analysis of the market conditions. Based on general knowledge, statistics, and the current odds, give fundamental reasons explaining why a trader should either 'hold', 'sell', or 'buy' each specific outcome.
    
    You must return your response in strict JSON format matching this exact schema:
    {{
        "analysis_text": "Your detailed explanation and analysis goes here...",
        "decisions": {{
            "Outcome 1 (e.g., Yes)": "buy",
            "Outcome 2 (e.g., No)": "sell",
            "Outcome 3 (if applicable)": "hold"
        }}
    }}
    """

    print("Requesting AI analysis...\n")
    
    # Call OpenAI (using JSON Object response format to guarantee variable parsing)
    response = client.chat.completions.create(
        model="gpt-4o", 
        response_format={ "type": "json_object" },
        messages=[
            {"role": "system", "content": "You are a data-driven financial AI. You always output valid JSON."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )

    # Parse the LLM's JSON response
    ai_output = json.loads(response.choices[0].message.content)
    
    analysis = ai_output.get("analysis_text", "No analysis provided.")
    decision_variable = ai_output.get("decisions", {})

    # 1. Print out the analysis
    print("=" * 60)
    print("📈 AI MARKET ANALYSIS")
    print("=" * 60)
    print(analysis)
    print("=" * 60)
    
    # 2. Return the parsed outputs so the broader script can use the decision variable
    return analysis, decision_variable

# --- Execution Block ---
if __name__ == "__main__":
    # Replace this with the Polymarket link you have
    polymarket_url = "https://polymarket.com/event/highest-temperature-in-tel-aviv-on-may-26-2026/highest-temperature-in-tel-aviv-on-may-26-2026-26c"
    
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY environment variable is not set.")
    else:
        # Run the analysis
        final_analysis, ai_decisions = analyze_market_with_ai(polymarket_url)
        
        if ai_decisions:
            print("\n⚙️  SCRIPT VARIABLE SET: 'ai_decisions'")
            print(json.dumps(ai_decisions, indent=2))
            
            # Example of how you would use this variable later in your script:
            # if ai_decisions.get("Yes") == "buy":
            #     execute_buy_order("Yes")