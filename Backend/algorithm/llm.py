import os
import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    pipeline
)
from peft import PeftModel
from dotenv import load_dotenv
from typing import List, Dict, AsyncGenerator
import asyncio
import traceback

# LangChain Imports
from langchain_huggingface import HuggingFacePipeline
from langchain_core.messages import HumanMessage, AIMessage


load_dotenv()

BASE_MODEL_ID = os.getenv("BASE_MODEL_ID")
ADAPTER_PATH = os.getenv("ADAPTER_PATH")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

USE_QUANTIZATION = True
bnb_config = None
USE_ADAPTER = False

if not BASE_MODEL_ID or not ADAPTER_PATH:
    raise ValueError("LLM configuration missing.")

if USE_QUANTIZATION:
     bnb_config = BitsAndBytesConfig(load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.bfloat16) 

# --- Global Model State ---
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

    # --- Load Tokenizer ---
    print(f"LLM - Loading tokenizer: {BASE_MODEL_ID}")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL_ID, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        print("LLM - Set pad_token to eos_token")
    print(f"LLM - Tokenizer EOS: {tokenizer.eos_token_id}, PAD: {tokenizer.pad_token_id}")

    # --- Load Base Model ---
    print(f"LLM - Loading base model: {BASE_MODEL_ID} (Quantization: {USE_QUANTIZATION})")
    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL_ID,
        quantization_config=bnb_config if USE_QUANTIZATION else None,
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
        device_map="auto",
        attn_implementation="eager"
    )

    # --- Conditionally Load Adapter ---
    if USE_ADAPTER:
        print(f"LLM - Loading LoRA adapter from: {ADAPTER_PATH}")
        if not os.path.exists(ADAPTER_PATH):
            raise FileNotFoundError(f"LLM - Adapter path not found: {ADAPTER_PATH}")
        try:
            # Assign loaded PEFT model to the global 'model' variable
            print("LLM - Applying PEFT adapter to base model...")
            model = PeftModel.from_pretrained(base_model, ADAPTER_PATH)
            model.eval()
            print("LLM - PEFT Model loaded and assigned successfully.")
        except Exception as e:
            print(f"LLM - Error loading PEFT adapter: {e}")
            raise e
    else:
        # If not using adapter, assign the base model directly to the global model
        print("LLM - Skipping adapter loading. Using BASE MODEL directly.")
        model = base_model 

    # --- Create Transformers Pipeline ---
    print("LLM - Creating Transformers pipeline...")
    pipe = pipeline(
        "text-generation",
        model=model, 
        tokenizer=tokenizer,
        device_map="auto", 
        max_new_tokens=600, 
        temperature=0.4,
        top_p=0.9,
        top_k=50,
        repetition_penalty=1.2,
        do_sample=True,
        eos_token_id=tokenizer.eos_token_id,
        pad_token_id=tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id,
    )
    print("LLM - Transformers pipeline created.")

    # --- LangChain LLM Wrapper ---
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
        else:
            pass
    return messages


async def generate_lc_response_stream(chat_history: List[Dict[str, str]]) -> AsyncGenerator[str, None]:
    """Generates response token by token asynchronously using LangChain."""
    global lc_llm # Use the global LangChain LLM object
    if lc_llm is None:
        yield "[ERROR] LangChain LLM not loaded."
        return

    try:
        # --- History Truncation ---
        MAX_TURNS = 10
        truncated_history_dicts = chat_history[-MAX_TURNS*2:]
        print(f"LLM (LC) - Truncated history length: {len(truncated_history_dicts)}")

        # --- Convert history to LangChain messages ---
        lc_messages = _convert_history_to_lc_messages(truncated_history_dicts)
        
        # --- Log the prompt string the model actually sees ---
        try:
            # Attempt to format using the tokenizer's template logic
            formatted_prompt_for_debug = tokenizer.apply_chat_template(
                conversation=[msg.to_dict() for msg in lc_messages], # Convert LangChain messages back to dicts
                tokenize=False,
                add_generation_prompt=True
            )
            print(f"\n------ LANGCHAIN FORMATTED PROMPT ------\n{formatted_prompt_for_debug}\n-------------------------------------\n")
        except Exception as e:
            print(f"\n------ ERROR APPLYING CHAT TEMPLATE: {e} ------\n")
            # Fallback: Simple manual formatting for debug viewing
            simple_prompt = "\n".join([f"{msg.type.upper()}: {msg.content}" for msg in lc_messages]) + "\nASSISTANT:"
            print(f"\n------ SIMPLE CONCATENATED PROMPT (for debug) ------\n{simple_prompt}\n-------------------------------------\n")


        token_count = 0
        async for chunk in lc_llm.astream(lc_messages):
            token_count += 1
            yield chunk
            await asyncio.sleep(0.01)


        print(f"LLM (LC) - Streaming finished. Tokens yielded: {token_count}.")

    except Exception as e:
        print(f"LLM (LC) - Error during LangChain stream generation: {e}")
        traceback.print_exc()
        yield f"[ERROR] Could not generate response via LangChain: {e}"