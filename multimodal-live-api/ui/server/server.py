import asyncio
import json
import base64

# Import Google Generative AI components
from google import genai
from google.genai import types
from google.genai.types import (
    LiveConnectConfig,
    SpeechConfig,
    VoiceConfig,
    PrebuiltVoiceConfig,
)

# Import common components
from common import (
    BaseWebSocketServer,
    logger,
    PROJECT_ID,
    LOCATION,
    MODEL,
    VOICE_NAME,
    SEND_SAMPLE_RATE,
    SYSTEM_INSTRUCTION,
    get_order_status,
    check_storage_availability,
    book_storage_reservation,
    # validate_user_identity,
)

# Function declarations for LiveAPI
order_status_function = types.FunctionDeclaration(
    name="get_order_status",
    description="Get the current status and details of an order",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "order_id": types.Schema(
                type=types.Type.STRING, description="The order ID to look up"
            )
        },
        required=["order_id"],
    ),
)

storage_availability_function = types.FunctionDeclaration(
    name="check_storage_availability",
    description="Check available storage units by size and location",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "size": types.Schema(
                type=types.Type.STRING,
                description="Storage unit size (e.g., 'Small (5x5)', 'Medium (10x10)', 'Large (10x20)')",
            ),
            "location": types.Schema(
                type=types.Type.STRING,
                description="Location preference (e.g., 'Downtown', 'Midtown', 'Airport', 'Suburbs')",
            ),
        },
    ),
)

book_reservation_function = types.FunctionDeclaration(
    name="book_storage_reservation",
    description="Create a new storage reservation for a customer",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "customer_name": types.Schema(
                type=types.Type.STRING, description="Name of the customer"
            ),
            "size": types.Schema(
                type=types.Type.STRING, description="Storage unit size"
            ),
            "location": types.Schema(
                type=types.Type.STRING, description="Preferred location"
            ),
            "start_date": types.Schema(
                type=types.Type.STRING,
                description="When the rental starts (YYYY-MM-DD format)",
            ),
            "duration_months": types.Schema(
                type=types.Type.INTEGER, description="How many months to book"
            ),
        },
        required=["customer_name", "size", "location", "start_date", "duration_months"],
    ),
)

# validate_identity_function = types.FunctionDeclaration(
#     name="validate_user_identity",
#     description="Verify user identity using address information",
#     parameters=types.Schema(
#         type=types.Type.OBJECT,
#         properties={
#             "address": types.Schema(
#                 type=types.Type.STRING,
#                 description="User's address or city (e.g., 'NW Calgary')",
#             ),
#         },
#         required=["address"],
#     ),
# )

# Initialize Google client
client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

# LiveAPI Configuration
config = LiveConnectConfig(
    response_modalities=["AUDIO"],
    output_audio_transcription={},
    input_audio_transcription={},
    speech_config=SpeechConfig(
        voice_config=VoiceConfig(
            prebuilt_voice_config=PrebuiltVoiceConfig(voice_name=VOICE_NAME)
        )
    ),
    session_resumption=types.SessionResumptionConfig(handle=None),
    system_instruction=SYSTEM_INSTRUCTION,
    tools=[
        types.Tool(
            function_declarations=[
                order_status_function,
                storage_availability_function,
                book_reservation_function,
                # validate_identity_function,
            ]
        )
    ],
)


class LiveAPIWebSocketServer(BaseWebSocketServer):
    """WebSocket server implementation using Gemini LiveAPI directly."""

    async def process_audio(self, websocket, client_id):
        # Store reference to client
        self.active_clients[client_id] = websocket

        # Connect to Gemini using LiveAPI
        async with client.aio.live.connect(model=MODEL, config=config) as session:
            async with asyncio.TaskGroup() as tg:
                # Create a queue for audio data from the client
                audio_queue = asyncio.Queue()

                # Task to process incoming WebSocket messages
                async def handle_websocket_messages():
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                            if data.get("type") == "audio":
                                # Decode base64 audio data
                                audio_bytes = base64.b64decode(data.get("data", ""))
                                # Put audio in queue for processing
                                await audio_queue.put(audio_bytes)
                            elif data.get("type") == "end":
                                # Client is done sending audio for this turn
                                logger.info("Received end signal from client")
                            elif data.get("type") == "text":
                                # Handle text messages (not implemented in this simple version)
                                logger.info(f"Received text: {data.get('data')}")
                        except json.JSONDecodeError:
                            logger.error("Invalid JSON message received")
                        except Exception as e:
                            logger.error(f"Error processing message: {e}")

                # Task to process and send audio to Gemini
                async def process_and_send_audio():
                    while True:
                        data = await audio_queue.get()

                        # Send the audio data to Gemini
                        await session.send_realtime_input(
                            media={
                                "data": data,
                                "mime_type": f"audio/pcm;rate={SEND_SAMPLE_RATE}",
                            }
                        )

                        audio_queue.task_done()

                # Task to receive and play responses
                async def receive_and_play():
                    while True:
                        input_transcriptions = []
                        output_transcriptions = []

                        async for response in session.receive():
                            # Get session resumption update if available
                            if response.session_resumption_update:
                                update = response.session_resumption_update
                                if update.resumable and update.new_handle:
                                    session_id = update.new_handle
                                    logger.info(f"New SESSION: {session_id}")
                                    # Send session ID to client
                                    session_id_msg = json.dumps(
                                        {"type": "session_id", "data": session_id}
                                    )
                                    await websocket.send(session_id_msg)

                            # Check if connection will be terminated soon
                            if response.go_away is not None:
                                logger.info(
                                    f"Session will terminate in: {response.go_away.time_left}"
                                )

                            server_content = response.server_content

                            # Handle function calls
                            if server_content and server_content.model_turn:
                                for part in server_content.model_turn.parts:
                                    if (
                                        hasattr(part, "function_call")
                                        and part.function_call
                                    ):
                                        # Handle function call
                                        function_name = part.function_call.name
                                        function_args = part.function_call.args

                                        logger.info(
                                            f"Function call: {function_name} with args: {function_args}"
                                        )

                                        # Execute the function
                                        try:
                                            if function_name == "get_order_status":
                                                result = get_order_status(
                                                    function_args.get("order_id")
                                                )
                                            elif (
                                                function_name
                                                == "check_storage_availability"
                                            ):
                                                result = check_storage_availability(
                                                    function_args.get("size"),
                                                    function_args.get("location"),
                                                )
                                            elif (
                                                function_name
                                                == "book_storage_reservation"
                                            ):
                                                result = book_storage_reservation(
                                                    function_args.get("customer_name"),
                                                    function_args.get("size"),
                                                    function_args.get("location"),
                                                    function_args.get("start_date"),
                                                    function_args.get(
                                                        "duration_months"
                                                    ),
                                                )
                                            # elif (
                                            #     function_name
                                            #     == "validate_user_identity"
                                            # ):
                                            #     result = validate_user_identity(
                                            #         address=function_args.get("address")
                                            #     )
                                            else:
                                                result = {
                                                    "error": f"Unknown function: {function_name}"
                                                }

                                            # Send function response back to the model
                                            await session.send_realtime_input(
                                                function_response={
                                                    "id": part.function_call.id,
                                                    "name": function_name,
                                                    "response": result,
                                                }
                                            )

                                        except Exception as e:
                                            logger.error(
                                                f"Error executing function {function_name}: {e}"
                                            )
                                            await session.send_realtime_input(
                                                function_response={
                                                    "id": part.function_call.id,
                                                    "name": function_name,
                                                    "response": {"error": str(e)},
                                                }
                                            )

                            # Handle interruption
                            if (
                                hasattr(server_content, "interrupted")
                                and server_content.interrupted
                            ):
                                logger.info("🤐 INTERRUPTION DETECTED")
                                # Just notify the client - no need to handle audio on server side
                                await websocket.send(
                                    json.dumps(
                                        {
                                            "type": "interrupted",
                                            "data": "Response interrupted by user input",
                                        }
                                    )
                                )

                            # Process model response
                            if server_content and server_content.model_turn:
                                for part in server_content.model_turn.parts:
                                    if part.inline_data:
                                        # Send audio to client only (don't play locally)
                                        b64_audio = base64.b64encode(
                                            part.inline_data.data
                                        ).decode("utf-8")
                                        await websocket.send(
                                            json.dumps(
                                                {"type": "audio", "data": b64_audio}
                                            )
                                        )

                            # Handle turn completion
                            if server_content and server_content.turn_complete:
                                logger.info("✅ Gemini done talking")
                                await websocket.send(
                                    json.dumps({"type": "turn_complete"})
                                )

                            # Handle transcriptions
                            output_transcription = getattr(
                                response.server_content, "output_transcription", None
                            )
                            if output_transcription and output_transcription.text:
                                output_transcriptions.append(output_transcription.text)
                                # Send text to client
                                await websocket.send(
                                    json.dumps(
                                        {
                                            "type": "text",
                                            "data": output_transcription.text,
                                        }
                                    )
                                )

                            input_transcription = getattr(
                                response.server_content, "input_transcription", None
                            )
                            if input_transcription and input_transcription.text:
                                input_transcriptions.append(input_transcription.text)

                        logger.info(
                            f"Output transcription: {''.join(output_transcriptions)}"
                        )
                        logger.info(
                            f"Input transcription: {''.join(input_transcriptions)}"
                        )

                # Start all tasks
                tg.create_task(handle_websocket_messages())
                tg.create_task(process_and_send_audio())
                tg.create_task(receive_and_play())


async def main():
    """Main function to start the server"""
    server = LiveAPIWebSocketServer()
    await server.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Exiting application via KeyboardInterrupt...")
    except Exception as e:
        logger.error(f"Unhandled exception in main: {e}")
        import traceback

        traceback.print_exc()
