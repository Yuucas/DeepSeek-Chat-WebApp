import os
import torch
from typing import List, Dict, AsyncGenerator, Optional
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    # TextIteratorStreamer, # We won't use this directly anymore
    BitsAndBytesConfig,
    StoppingCriteria, # Import StoppingCriteria
    StoppingCriteriaList
)
from peft import PeftModel
from dotenv import load_dotenv
from threading import Thread
from typing import List, Dict, AsyncGenerator
import asyncio
import queue
import traceback

load_dotenv()

BASE_MODEL_ID = os.getenv("BASE_MODEL_ID")
ADAPTER_PATH = os.getenv("ADAPTER_PATH")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
USE_QUANTIZATION = False # Set based on your training/preference
bnb_config = None

if not BASE_MODEL_ID or not ADAPTER_PATH:
    raise ValueError("LLM configuration (BASE_MODEL_ID, ADAPTER_PATH) not found in environment variables.")

if USE_QUANTIZATION:
     bnb_config = BitsAndBytesConfig(
         load_in_4bit=True,
         bnb_4bit_use_double_quant=True,
         bnb_4bit_quant_type="nf4",
         bnb_4bit_compute_dtype=torch.bfloat16
     )

# --- Global Model State ---
model = None
tokenizer = None

def load_llm():
    """Loads the LLM and tokenizer (call once on startup)."""
    global model, tokenizer
    if model is not None and tokenizer is not None:
        print("LLM already loaded.")
        return

    print(f"LLM - Loading tokenizer: {BASE_MODEL_ID}")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL_ID, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        print("LLM - Set pad_token to eos_token")

    print(f"LLM - Loading base model: {BASE_MODEL_ID} (Quantization: {USE_QUANTIZATION})")
    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL_ID,
        quantization_config=bnb_config if USE_QUANTIZATION else None,
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
        device_map="auto"
    )

    print(f"LLM - Loading LoRA adapter from: {ADAPTER_PATH}")
    if not os.path.exists(ADAPTER_PATH):
        raise FileNotFoundError(f"LLM - Adapter path not found: {ADAPTER_PATH}")

    try:
        model = PeftModel.from_pretrained(base_model, ADAPTER_PATH)
        model.eval()
        print("LLM - Model loaded successfully.")
    except Exception as e:
        print(f"LLM - Error loading PEFT adapter: {e}")
        raise e
    
class TokenStreamer(StoppingCriteria):
    def __init__(self, token_queue: queue.Queue, timeout: Optional[float] = None):
        self.queue = token_queue
        self.timeout = timeout # Optional timeout for queue reading

    # __call__ is invoked after each token generation
    def __call__(self, input_ids: torch.LongTensor, scores: torch.FloatTensor, **kwargs) -> bool:
        # Get the last generated token ID from the input_ids sequence
        last_token_id = input_ids[0, -1].item()
        # Put the token ID onto the queue for the main thread to process
        self.queue.put(last_token_id)
        # print(f"DEBUG: Streamer put token ID: {last_token_id}") # Very verbose
        # Return False to continue generation
        return False

# --- Revised generate_response_stream ---
async def generate_response_stream(chat_history: List[Dict[str, str]]) -> AsyncGenerator[str, None]:
    """Generates response token by token asynchronously using manual decoding."""
    global model, tokenizer
    if model is None or tokenizer is None:
        yield "[ERROR] LLM not loaded."
        return

    # Use a queue to get token IDs from the generation thread
    token_queue = queue.Queue()
    streamer = TokenStreamer(token_queue) # Instantiate our custom streamer

    try:
        # --- Prepare Prompt and Inputs (same as before) ---
        MAX_TURNS = 25
        truncated_history = chat_history[-MAX_TURNS*2:]

        print(f"LLM - Truncated history length: {truncated_history}") # Debug

        formatted_prompt = tokenizer.apply_chat_template(
            truncated_history, tokenize=False, add_generation_prompt=True
        )
        print(f"LLM - Formatted prompt: {formatted_prompt}") # Debug

        inputs = tokenizer(formatted_prompt, return_tensors="pt").to(model.device)
        input_length = inputs.input_ids.shape[1] # Get length of prompt tokens

        print(f"Tokenizer Pad Token ID: {tokenizer.pad_token_id}, Eos Token ID: {tokenizer.eos_token_id}") # Debug

        # --- Generation Arguments ---
        generation_kwargs = dict(
            **inputs, # Pass input_ids and attention_mask directly
            stopping_criteria=StoppingCriteriaList([streamer]), # Use our streamer
            max_new_tokens=300,
            pad_token_id=tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
            do_sample=True,
            temperature=0.6,
            top_p=0.9,
            repetition_penalty=1.25
            # streamer=streamer, # REMOVE TextIteratorStreamer argument
        )

        # --- Run Generation in Thread ---
        # Define the target function for the thread
        def generation_thread_func():
            try:
                model.generate(**generation_kwargs)
            except Exception as e:
                print(f"LLM - Error in generation thread: {e}")
                token_queue.put(None) # Signal error with None
            finally:
                # Signal the end of generation by putting a sentinel value (e.g., None)
                token_queue.put(None)

        thread = Thread(target=generation_thread_func)
        thread.start()
        print("LLM - Generation thread started.")

        # --- Process Tokens from Queue and Decode ---
        generated_token_ids = []
        decoded_text = ""
        while True:
            try:
                # Get next token ID from queue (non-blocking with timeout is safer)
                next_token_id = await asyncio.to_thread(token_queue.get, timeout=120) # Use asyncio.to_thread; add timeout
            except queue.Empty:
                print("LLM - Timeout waiting for next token from generation thread.")
                yield "[ERROR] Generation timed out."
                break # Exit loop on timeout

            if next_token_id is None: # Check for sentinel value (end or error)
                print("LLM - Received sentinel (None), generation finished or errored.")
                break # Exit loop

            generated_token_ids.append(next_token_id)

            # --- Decode the *new* token WITH context ---
            # Decode the sequence INCLUDING the new token.
            # This helps handle multi-token characters and proper spacing.
            # Use skip_special_tokens=True here to remove things like <｜end of sentence｜>
            # Adjust decoding parameters if needed (e.g., clean_up_tokenization_spaces)
            new_decoded_text = tokenizer.decode(generated_token_ids,
                                                skip_special_tokens=True,
                                                clean_up_tokenization_spaces=True) # Try adding this

            # --- Yield only the *difference* ---
            # Find what's new compared to the previously decoded text
            new_part = new_decoded_text[len(decoded_text):]
            if new_part: # Only yield if there's actually new text
                 # print(f"LLM - Yielding decoded part: >>{new_part}<<") # Debug
                 yield new_part
                 decoded_text = new_decoded_text # Update the previously decoded text

                 print(f"Decoded Text : {decoded_text}")

            await asyncio.sleep(0.01) # Small yield

        # --- Cleanup ---
        print("LLM - Waiting for generation thread to join...")
        await asyncio.to_thread(thread.join) # Wait for thread to finish completely
        print("LLM - Generation thread joined.")

    except Exception as e:
        print(f"LLM - Error during generate_response_stream: {e}")
        traceback.print_exc() # Print full traceback
        yield f"[ERROR] Could not generate response: {e}"