# file: Backend/algorithm/llm.py
import os
import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    # TextIteratorStreamer, # No longer needed
    BitsAndBytesConfig,
    pipeline # Import pipeline
)


from peft import PeftModel
from dotenv import load_dotenv
# from threading import Thread # No longer needed for generation
from typing import List, Dict, AsyncGenerator
import asyncio
import time

# LangChain Imports
from langchain_huggingface import HuggingFacePipeline # NEW
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage # Import message types
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

load_dotenv()

BASE_MODEL_ID = os.getenv("BASE_MODEL_ID")
ADAPTER_PATH = os.getenv("ADAPTER_PATH")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
USE_QUANTIZATION = False
bnb_config = None

if not BASE_MODEL_ID or not ADAPTER_PATH:
    raise ValueError("LLM configuration missing.")

if USE_QUANTIZATION:
     bnb_config = BitsAndBytesConfig(...) # Your config here

# --- Global Model State ---
# Keep model and tokenizer loaded as before
model = None
tokenizer = None
# Add LangChain LLM object
lc_llm = None

def load_llm():
    """Loads the LLM, tokenizer, and creates LangChain pipeline."""
    global model, tokenizer, lc_llm
    if lc_llm is not None:
        print("LLM and LangChain Pipeline already loaded.")
        return

    # --- Load Tokenizer (same as before) ---
    print(f"LLM - Loading tokenizer: {BASE_MODEL_ID}")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL_ID, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        print("LLM - Set pad_token to eos_token")
    print(f"LLM - Tokenizer EOS: {tokenizer.eos_token_id}, PAD: {tokenizer.pad_token_id}")

    # --- Load Base Model (same as before) ---
    print(f"LLM - Loading base model: {BASE_MODEL_ID} (Quantization: {USE_QUANTIZATION})")
    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL_ID,
        quantization_config=bnb_config if USE_QUANTIZATION else None,
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
        device_map="auto",
        attn_implementation="eager"
    )

    # --- Load Adapter (same as before) ---
    print(f"LLM - Loading LoRA adapter from: {ADAPTER_PATH}")
    if not os.path.exists(ADAPTER_PATH):
        raise FileNotFoundError(f"LLM - Adapter path not found: {ADAPTER_PATH}")
    try:
        # Assign loaded PEFT model to the global 'model' variable
        model = PeftModel.from_pretrained(base_model, ADAPTER_PATH)
        model.eval()
        print("LLM - PEFT Model loaded successfully.")
    except Exception as e:
        print(f"LLM - Error loading PEFT adapter: {e}")
        raise e

    # --- Create Transformers Pipeline ---
    # Ensure the loaded PEFT model is used here
    print("LLM - Creating Transformers pipeline...")
    pipe = pipeline(
        "text-generation",
        model=model, # Use the loaded PEFT model
        tokenizer=tokenizer,
        device_map="auto", # Or specify device if needed
        # --- Set generation parameters here ---
        max_new_tokens=300, # Default max, can be overridden in call
        temperature=0.6,
        top_p=0.9,
        top_k=50,
        repetition_penalty=1.25,
        do_sample=True,
        eos_token_id=tokenizer.eos_token_id,
        pad_token_id=tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id,
    )
    print("LLM - Transformers pipeline created.")

    # --- Create LangChain LLM Wrapper ---
    # Pass pipeline parameters if needed, or rely on pipeline defaults
    lc_llm = HuggingFacePipeline(pipeline=pipe)
    print("LLM - LangChain HuggingFacePipeline initialized.")


def _convert_history_to_lc_messages(chat_history: List[Dict[str, str]]):
    """Converts standard chat history list to LangChain Message objects."""
    messages = []
    for msg in chat_history:
        if msg.get("role") == "user":
            messages.append(HumanMessage(content=msg.get("content", "")))
        elif msg.get("role") == "assistant":
            messages.append(AIMessage(content=msg.get("content", "")))
        # Add handling for 'system' role if you use it
        # elif msg.get("role") == "system":
        #     messages.append(SystemMessage(content=msg.get("content", "")))
    return messages


async def generate_lc_response_stream(chat_history: List[Dict[str, str]]) -> AsyncGenerator[str, None]:
    """Generates response token by token asynchronously using LangChain."""
    global lc_llm # Use the global LangChain LLM object
    if lc_llm is None:
        yield "[ERROR] LangChain LLM not loaded."
        return

    start_time = time.time()
    print("LLM (LC) - Starting response stream generation.")

    try:
        # --- History Truncation (Keep this) ---
        MAX_TURNS = 5
        truncated_history_dicts = chat_history[-MAX_TURNS*2:]
        print(f"LLM (LC) - Truncated history length: {len(truncated_history_dicts)}")

        # --- Convert history to LangChain messages ---
        lc_messages = _convert_history_to_lc_messages(truncated_history_dicts)

        
        # --- Optional: Log the prompt string the model actually sees ---
        # This helps verify if the template adds anything weird.
        try:
            # Note: add_generation_prompt=False prevents adding the usual assistant prompt turn
            # if the template requires explicit roles for generation. Set to True if needed.
            # Set add_special_tokens based on model requirements (usually True for chat)
            formatted_prompt = tokenizer.apply_chat_template(
                lc_messages,
                tokenize=False,
                add_generation_prompt=True # Usually True for generation
            )
            print(f"LLM (LC) - Formatted prompt for model:\n-------\n{formatted_prompt}\n-------")
        except Exception as template_err:
            print(f"LLM (LC) - Warning: Could not apply chat template for logging: {template_err}")
        # --- End Optional Logging ---


        token_count = 0
        async for chunk in lc_llm.astream(lc_messages):
            # chunk is typically a string token when streaming from HF pipeline
            # print(f"LLM (LC) - Yielding chunk: {chunk}") # Verbose debug
            token_count += 1
            yield chunk
            await asyncio.sleep(0.01) # Small sleep remains useful

        end_time = time.time()
        print(f"LLM (LC) - Streaming finished. Tokens yielded: {token_count}. Time: {end_time - start_time:.2f}s")

    except Exception as e:
        print(f"LLM (LC) - Error during LangChain stream generation: {e}")
        import traceback
        traceback.print_exc()
        yield f"[ERROR] Could not generate response via LangChain: {e}"