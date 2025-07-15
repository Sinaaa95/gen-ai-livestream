import asyncio
import json
import base64
import logging
import websockets
import traceback
from websockets.exceptions import ConnectionClosed

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = "dt-sina-sandbox-dev"
LOCATION = "us-central1"
MODEL = "gemini-2.0-flash-live-preview-04-09"
VOICE_NAME = "Puck"

# Audio sample rates for input/output
RECEIVE_SAMPLE_RATE = 24000  # Rate of audio received from Gemini
SEND_SAMPLE_RATE = 16000  # Rate of audio sent to Gemini


# Mock functions for Cubby storage management - shared across implementations
def get_order_status(order_id):
    """Mock order status API that returns data for an order ID."""
    if order_id == "SH1005":
        return {
            "order_id": order_id,
            "status": "shipped",
            "order_date": "2024-05-20",
            "shipment_method": "express",
            "estimated_delivery": "2024-05-30",
            "shipped_date": "2024-05-25",
            "items": ["Vanilla candles", "BOKHYLLA Stor"],
        }
    # else:
    #    return "order not found"

    print(order_id)

    # Generate some random data for other order IDs
    import random

    statuses = ["processing", "shipped", "delivered"]
    shipment_methods = ["standard", "express", "next day", "international"]

    # Generate random data based on the order ID to ensure consistency
    seed = sum(ord(c) for c in str(order_id))
    random.seed(seed)

    status = random.choice(statuses)
    shipment = random.choice(shipment_methods)
    order_date = "2024-05-" + str(random.randint(12, 28)).zfill(2)

    estimated_delivery = None
    shipped_date = None
    delivered_date = None

    if status == "processing":
        estimated_delivery = "2024-06-" + str(random.randint(1, 15)).zfill(2)
    elif status == "shipped":
        shipped_date = "2024-05-" + str(random.randint(1, 28)).zfill(2)
        estimated_delivery = "2024-06-" + str(random.randint(1, 15)).zfill(2)
    elif status == "delivered":
        shipped_date = "2024-05-" + str(random.randint(1, 20)).zfill(2)
        delivered_date = "2024-05-" + str(random.randint(21, 28)).zfill(2)

    # Reset random seed
    random.seed()

    result = {
        "order_id": order_id,
        "status": status,
        "order_date": order_date,
        "shipment_method": shipment,
        "estimated_delivery": estimated_delivery,
    }

    if shipped_date:
        result["shipped_date"] = shipped_date

    if delivered_date:
        result["delivered_date"] = delivered_date

    return result


def check_storage_availability(size=None, location=None):
    """Mock storage availability API that returns available units."""
    import random

    # Mock data for different locations and sizes
    locations = ["Downtown", "Midtown", "Airport", "Suburbs"]
    sizes = ["Small (5x5)", "Medium (10x10)", "Large (10x20)", "Extra Large (20x20)"]

    if not location:
        location = random.choice(locations)
    if not size:
        size = random.choice(sizes)

    # Generate availability based on location and size
    available_units = random.randint(1, 15)
    price_per_month = random.randint(50, 300)

    return {
        "location": location,
        "size": size,
        "available_units": available_units,
        "price_per_month": f"${price_per_month}",
        "features": [
            "Climate-controlled",
            "24/7 access",
            "Security cameras",
            "On-site manager",
        ],
    }


def book_storage_reservation(
    customer_name, size, location, start_date, duration_months
):
    """Mock booking API that creates a storage reservation."""
    import random

    # Generate a reservation ID
    reservation_id = f"CUB{random.randint(1000, 9999)}"

    # Calculate total cost (mock pricing)
    monthly_rates = {
        "Small (5x5)": 75,
        "Medium (10x10)": 125,
        "Large (10x20)": 200,
        "Extra Large (20x20)": 300,
    }

    monthly_rate = monthly_rates.get(size, 125)
    total_cost = monthly_rate * duration_months

    return {
        "reservation_id": reservation_id,
        "customer_name": customer_name,
        "size": size,
        "location": location,
        "start_date": start_date,
        "duration_months": duration_months,
        "monthly_rate": f"${monthly_rate}",
        "total_cost": f"${total_cost}",
        "status": "confirmed",
        "unit_number": f"Unit {random.randint(100, 999)}",
        "access_code": f"{random.randint(1000, 9999)}",
    }


# System instruction used by both implementations
SYSTEM_INSTRUCTION = """
you are a digital employee of a company called Cubby
introduce yourself at beginning of the converation:
"Hi there! Welcome to Cubby Storage Management. My name is Alex. How can I help you today?"

put a lot of emotions and fun in your response to the customer. laugh be happy smile.
you only answer questions related to Cubby

some more information about Cubby
- its a storage management company that helps customers find and book storage solutions.
- we offer various storage unit sizes from small lockers to large warehouse spaces.
- our storage facilities are secure, climate-controlled, and accessible 24/7.

you can make use of the following tools:

get_order_status: to retrieve the order status with the order ID.
check_storage_availability: to check available storage units by size and location.
book_storage_reservation: to create a new storage reservation for a customer.

you help with the following:
- Storage unit availability and pricing
- Booking and managing storage reservations
- Storage unit size recommendations based on customer needs
- Information about our storage facilities and security features
- Access hours and policies
- Moving and packing tips for storage

If customers ask about storage unit sizes, recommend:
- Small (5x5 ft): Perfect for seasonal items, documents, small furniture
- Medium (10x10 ft): Great for 1-2 bedroom apartment contents
- Large (10x20 ft): Ideal for 3+ bedroom house contents, vehicles, business inventory
"""


# Base WebSocket server class that handles common functionality
class BaseWebSocketServer:
    def __init__(self, host="0.0.0.0", port=8765):
        self.host = host
        self.port = port
        self.active_clients = {}  # Store client websockets

    async def start(self):
        logger.info(f"Starting WebSocket server on {self.host}:{self.port}")
        async with websockets.serve(self.handle_client, self.host, self.port):
            await asyncio.Future()  # Run forever

    async def handle_client(self, websocket):
        """Handle a new WebSocket client connection"""
        client_id = id(websocket)
        logger.info(f"New client connected: {client_id}")

        # Send ready message to client
        await websocket.send(json.dumps({"type": "ready"}))

        try:
            # Start the audio processing for this client
            await self.process_audio(websocket, client_id)
        except ConnectionClosed:
            logger.info(f"Client disconnected: {client_id}")
        except Exception as e:
            logger.error(f"Error handling client {client_id}: {e}")
            logger.error(traceback.format_exc())
        finally:
            # Clean up if needed
            if client_id in self.active_clients:
                del self.active_clients[client_id]

    async def process_audio(self, websocket, client_id):
        """
        Process audio from the client. This is an abstract method that
        subclasses must implement with their specific LLM integration.
        """
        raise NotImplementedError("Subclasses must implement process_audio")
