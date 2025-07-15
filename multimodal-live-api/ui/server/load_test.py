import asyncio
import websockets
import json
import base64
import time
import logging
import wave
import os
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Test configuration
NUM_CLIENTS = 100
WEBSOCKET_URL = "ws://localhost:8765"
SAMPLE_AUDIO_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "test_audio.wav"
)
CONNECTION_TIMEOUT = 30  # Connection timeout in seconds


async def simulate_client(client_id):
    """Simulate a single client connection and audio streaming."""
    try:
        # Configure WebSocket with optimized settings for real-time streaming
        async with websockets.connect(
            WEBSOCKET_URL,
            ping_interval=20,
            ping_timeout=20,
            max_size=2**23,  # 8MB max message size
            compression=None,  # Disable compression for better real-time performance
            close_timeout=10,
        ) as websocket:
            logger.info(f"Client {client_id} connected")

            # Read and process audio file
            if Path(SAMPLE_AUDIO_PATH).exists():
                with wave.open(SAMPLE_AUDIO_PATH, "rb") as wav_file:
                    audio_data = wav_file.readframes(wav_file.getnframes())
            else:
                # Use dummy audio if no file exists
                audio_data = bytes([0] * 16000)  # 1 second of silence
                logger.warning(
                    f"Client {client_id} using dummy audio (no WAV file found)"
                )

            # Base64 encode the audio data
            b64_audio = base64.b64encode(audio_data).decode("utf-8")

            # Send audio data
            await websocket.send(json.dumps({"type": "audio", "data": b64_audio}))

            # Listen for responses with timeout
            try:
                while True:
                    try:
                        response = await asyncio.wait_for(
                            websocket.recv(), timeout=CONNECTION_TIMEOUT
                        )
                        data = json.loads(response)

                        if data.get("type") == "turn_complete":
                            logger.info(f"Client {client_id} received turn complete")
                            break
                        elif data.get("type") == "text":
                            logger.debug(
                                f"Client {client_id} received text: {data.get('data')}"
                            )
                        elif data.get("type") == "audio":
                            logger.debug(f"Client {client_id} received audio response")

                    except asyncio.TimeoutError:
                        logger.warning(
                            f"Client {client_id} timeout waiting for response"
                        )
                        break
                    except websockets.exceptions.ConnectionClosed:
                        logger.warning(f"Client {client_id} connection closed")
                        break

            except Exception as e:
                logger.error(f"Client {client_id} error during response handling: {e}")

    except Exception as e:
        logger.error(f"Client {client_id} connection error: {e}")


async def run_load_test():
    """Run the load test with true concurrent connections."""
    start_time = time.time()

    # Create all client tasks at once for true concurrency
    tasks = [simulate_client(i) for i in range(NUM_CLIENTS)]

    # Run all tasks concurrently
    logger.info(
        f"Starting load test with {NUM_CLIENTS} concurrent real-time connections"
    )
    await asyncio.gather(*tasks)

    end_time = time.time()
    duration = end_time - start_time

    logger.info(f"Load test completed in {duration:.2f} seconds")
    logger.info(f"Average response time per client: {duration/NUM_CLIENTS:.2f} seconds")


if __name__ == "__main__":
    # Check audio file
    if not Path(SAMPLE_AUDIO_PATH).exists():
        logger.warning(
            f"Test audio file {SAMPLE_AUDIO_PATH} not found. Will use dummy audio data."
        )
    else:
        logger.info(f"Found WAV file: {SAMPLE_AUDIO_PATH}")

    try:
        # Increase the maximum number of open files for the process
        import resource

        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(resource.RLIMIT_NOFILE, (hard, hard))
        logger.info(f"Increased file limit from {soft} to {hard}")

        asyncio.run(run_load_test())
    except KeyboardInterrupt:
        logger.info("Load test interrupted by user")
    except Exception as e:
        logger.error(f"Load test failed: {e}")
