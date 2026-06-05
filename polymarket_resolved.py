import asyncio
import websockets
import json
from datetime import datetime

# Polymarket CLOB Market Channel WebSocket URL
WSS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

async def send_heartbeat(websocket):
    """
    Send the required string 'PING' every 10 seconds to keep the connection alive.
    The CLOB Market Channel expects literal text rather than a JSON action object.
    """
    while True:
        try:
            await websocket.send("PING")
            await asyncio.sleep(10)
        except websockets.ConnectionClosed:
            break
        except Exception as e:
            print(f"⚠️ Heartbeat error: {e}")
            break

async def monitor_market_resolutions():
    async with websockets.connect(WSS_URL) as websocket:
        # Create a background task for the heartbeat
        asyncio.create_task(send_heartbeat(websocket))

        # Build the subscription message
        # Passing an empty array [] to assets_ids subscribes to all global market events.
        # custom_feature_enabled: True is REQUIRED to activate market_resolved events.
        subscribe_msg = {
            "type": "market",
            "assets_ids": [],
            "custom_feature_enabled": True
        }
        
        await websocket.send(json.dumps(subscribe_msg))
        print("🚀 Connected to Polymarket Market Channel!")
        print("Listening for live market resolutions...")
        print("-" * 50)

        while True:
            try:
                message = await websocket.recv()
                
                # Filter out the server's PONG response or empty frames
                if message == "PONG" or not message.strip():
                    continue
                
                if not message.strip().startswith('{'):
                    continue
                
                data = json.loads(message)
                event_type = data.get("event_type")

                # Target 'market_resolved' events specifically
                print(event_type)
                condition_id = data.get("market")
                winning_asset_id = data.get("winning_asset_id")
                winning_outcome = data.get("winning_outcome")
                
                # Parse millisecond timestamp safely
                ts_raw = data.get("timestamp")
                try:
                    timestamp = datetime.fromtimestamp(int(ts_raw) / 1000) if ts_raw else datetime.now()
                except (ValueError, TypeError):
                    timestamp = datetime.now()
                # Extract parent event/group metadata if available natively in payload
                event_msg = data.get("event_message", {})
                title = event_msg.get("title", "Unknown Market / Conditionally Isolated")
                slug = event_msg.get("slug", "N/A")
                tags = data.get("tags", [])
                # --- Formatting and Printing ---
                print(f"🏁 Market Resolved!")
                print(f"📈 Title: {title}")
                print(f"✨ Winning Outcome: {winning_outcome}")
                print(f"Winner Asset ID: {winning_asset_id}")
                print(f"Condition ID: {condition_id}")
                print(f"Timestamp: {timestamp}")
                
                if slug != "N/A":
                    print(f"Slug: {slug}")
                if tags:
                    print(f"🏷️ Tags: {', '.join(tags)}")
                    
                print("-" * 50)

            except json.JSONDecodeError:
                continue
            except websockets.ConnectionClosed:
                print("⚠️ Connection Closed by Server.")
                break
            except Exception as e:
                print(f"⚠️ Error: {e}")
                break

if __name__ == "__main__":
    try:
        asyncio.run(monitor_market_resolutions())
    except KeyboardInterrupt:
        print("\nStopped by user.")