import httpx
from typing import AsyncGenerator, Optional
import os

BACKEND_BASE_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# Reuse the client instance if possible, or create a new one for SSE
_sse_client = httpx.AsyncClient(base_url=BACKEND_BASE_URL, timeout=None) # No timeout for SSE stream

async def stream_chat_responses(stream_id: str, cookies: Optional[dict] = None) -> AsyncGenerator[str, None]:
    """Connects to SSE endpoint and yields tokens."""
    url = f"/api/chat/stream/{stream_id}"
    headers = {"Accept": "text/event-stream"}
    # Pass cookies explicitly if needed and not automatically handled by client instance
    request_cookies = cookies or _sse_client.cookies

    try:
        async with _sse_client.stream("GET", url, headers=headers, cookies=request_cookies) as response:
            print(f"SSE: Connected to {url}, Status: {response.status_code}")
            response.raise_for_status() # Check for initial connection errors

            async for line in response.aiter_lines():

                if line.startswith("data:"):
                    prefix = "data: "
                    if line.startswith(prefix):
                        data = line[len(prefix):]
                    elif line.startswith("data:"): # Handle case with no space after colon
                        data = line[len("data:"):]
                    else: # Should not happen if line starts with "data:"
                        continue # Skip malformed lines

                    # print(f"SSE Extracted Data (No Strip): '{data}'") # Log extracted data WITHOUT strip

                    if data == "[DONE]": # Optional: Handle explicit done signal
                        print("SSE: Received [DONE] signal.")
                        break
                    elif data.startswith("[ERROR]"):
                         print(f"SSE: Received Error: {data}")
                         yield data # Propagate error message
                         break
                    else:
                        yield data # Yield the actual token/message

    except httpx.RequestError as e:
        print(f"SSE Request Error: {e}")
        yield f"[ERROR] Connection failed: {e}"
    except httpx.HTTPStatusError as e:
         print(f"SSE HTTP Status Error: {e.response.status_code}")
         yield f"[ERROR] Connection error: Status {e.response.status_code}"
    except Exception as e:
        print(f"SSE Unexpected Error: {e}")
        yield f"[ERROR] Unexpected error during streaming: {e}"
    finally:
        print(f"SSE: Stream finished or closed for {stream_id}")