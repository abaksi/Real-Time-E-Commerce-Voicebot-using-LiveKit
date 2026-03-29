
"""
llm_client.py
----------------
Natural language response engine for the eCommerce VoiceBot.
Handles prompt construction, deterministic responses for common queries, and LLM (OpenAI/Ollama) integration.
All store data is injected into the system prompt for context-rich, accurate answers.

Author notes:
- Utility functions are grouped at the top for clarity.
- Core query logic is separated from LLM backend calls.
- Public API is at the bottom for easy integration.
"""

import os
import json
import logging
import re
import time
import requests
from pathlib import Path
from logging_config import setup_logging

# --- Logging ---
# Set up logger for the LLM client
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logger = setup_logging("voicebot-agent", "llm_client.log", level=log_level)

# --- Utility Functions ---

# Utility: Collapse all whitespace runs to single spaces and strip ends
def squeeze_whitespace(text: str) -> str:
    """
    Collapse all whitespace runs to single spaces and strip ends.
    Args:
        text (str): Input text.
    Returns:
        str: Whitespace-collapsed and stripped text.
    """
    return " ".join((text or "").split())

# ---------------------------------------------------------------------------
# Load store data once at startup and build the system prompt
# ---------------------------------------------------------------------------


# --- Data Loading ---
    import os
_DATA_PATH = Path(__file__).parent.parent / "data" / "product-dataset.json"
try:
    with open(_DATA_PATH) as _f:
        _STORE_DATA = json.load(_f)
    logger.info("[LLM] Store dataset loaded")
except Exception as _e:
    _STORE_DATA = {}
    logger.error(f"[LLM] Failed to load store dataset: {_e}")



_PRODUCTS = _STORE_DATA.get("products", [])
_POLICIES = _STORE_DATA.get("policies", {})
_CATEGORY_INDEX = {}
for _p in _PRODUCTS:
    _category = str(_p.get("category", "")).strip().lower()
    if _category:
        _CATEGORY_INDEX.setdefault(_category, []).append(_p)



def build_system_prompt() -> str:
    """
    Build the system prompt for the LLM, embedding all store data (orders, products, policies).
    Returns:
        str: The full system prompt for the LLM.
    """
    """
    Build the system prompt for the LLM, embedding all store data (orders, products, policies).
    Returns:
        str: The full system prompt for the LLM.
    """
    data = _STORE_DATA
    store    = data.get("store", {})
    orders   = data.get("orders", {})
    products = data.get("products", [])
    policies = data.get("policies", {})

    # Store info lines
    store_lines = []
    if store:
        if store.get("name"):
            store_lines.append(f"  Store Name: {store['name']}")
        if store.get("address"):
            store_lines.append(f"  Address: {store['address']}")
        if store.get("owner"):
            store_lines.append(f"  Owner: {store['owner']}")

    # Build order, product, and policy lines for the prompt
    order_lines = []
    for oid, o in orders.items():
        eta = f", arrives in {o['eta_days']} days" if o.get("eta_days", 0) > 0 else ""
        items = ", ".join(o.get("items", []))
        order_lines.append(f"  Order {oid}: {o['status']}{eta} | items: {items} | total: ${o.get('total','?')}")

    product_lines = [
        f"  {p['name']} — ${p['price']}, stock: {p['stock']}, rating: {p['rating']}, category: {p['category']}"
        for p in products
    ]

    policy_lines = [f"  {k}: {v}" for k, v in policies.items()]

    return (
        "You are Ira, a concise, helpful AI customer support assistant for an e-commerce store. Do NOT greet the customer in every response.\n"
        "Reply in exactly ONE short, direct sentence suitable for text-to-speech.\n"
        "ONLY use the facts listed below. Never invent order IDs, prices, dates, or product details.\n"
        "If the answer is not in the data below, answer as helpfully as possible using the available information.\n"
        "If the user asks about store policies, use the policy details below.\n\n"
        "=== STORE DATA ===\n"
        + ("STORE INFO:\n" + "\n".join(store_lines) + "\n\n" if store_lines else "")
        + "ORDERS:\n" + "\n".join(order_lines) + "\n\n"
        + "PRODUCTS:\n" + "\n".join(product_lines) + "\n\n"
        + "POLICIES:\n" + "\n".join(policy_lines)
    )


_SYSTEM_PROMPT = build_system_prompt()

# ---------------------------------------------------------------------------
# Digit-word normalisation  ("one two three four five" → "12345")
# ---------------------------------------------------------------------------

 # --- Text Normalization ---
# Map digit words to numerals for normalization
_DIGIT_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}




def normalize_user_text(text: str) -> str:
    """
    Normalize user input for LLM processing:
      - Collapse digit words to numerals (e.g., 'one two three' → '123')
      - Collapse spaced digit runs (e.g., 'order 1 2 3 4 5' → 'order 12345')
    Args:
        text (str): User input text.
    Returns:
        str: Normalized text for LLM input.
    """
    text = " ".join((text or "").strip().split())
    text = " ".join(_DIGIT_WORDS.get(w.lower().strip(".,!?"), w) for w in text.split())
    def _collapse_order(m):
        return m.group(1) + re.sub(r"\D", "", m.group(2))
    text = re.sub(
        r"\b(order(?:\s*(?:id|number|no\.?))?\s*)([\d\s,\-\.]{2,})\b",
        _collapse_order, text, flags=re.IGNORECASE,
    )
    text = re.sub(r"\b(?:\d[\s,\-]*){4,}\d\b", lambda m: re.sub(r"\D", "", m.group()), text)
    return text

def extract_order_id(text: str) -> str | None:
    """
    Extract a 5-10 digit order ID from user text.
    Args:
        text (str): User input text.
    Returns:
        str or None: The extracted order ID, or None if not found.
    """
    """
    Extract a 5-10 digit order ID from user text.
    Returns:
        str | None: The extracted order ID, or None if not found.
    """
    m = re.search(r"\border(?:\s*(?:id|number|no\.?))?\s*(\d{1,10})\b", text, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"\b(\d{5})\b", text)
    return m.group(1) if m else None


def format_money(value) -> str:
    """
    Format a value as a currency string.
    Args:
        value: Value to format as currency.
    Returns:
        str: Formatted currency string or original value as string.
    """
    """
    Format a value as a currency string.
    Returns:
        str: Formatted currency string or original value as string.
    """
    try:
        return f"${float(value):.2f}"
    except Exception:
        return str(value)


# Restored: Query handler for order/product/category logic
def handle_user_query(prompt: str) -> str | None:
    """
    Handles order, product, and category queries for the eCommerce VoiceBot.
    Args:
        prompt (str): User query prompt.
    Returns:
        str or None: A string response if handled, else None.
    """
    """
    Handles order, product, and category queries for the eCommerce VoiceBot.
    Returns:
        str | None: A string response if handled, else None.
    """


    low = (prompt or "").lower()
    _ORDERS = _STORE_DATA.get("orders", {})
    _PRODUCTS = _STORE_DATA.get("products", [])
    order_id = extract_order_id(prompt)
    # Block attempts to enumerate or list all order IDs
    if re.search(r"all order ids|list.*order ids|different order ids|show.*order ids|what.*order ids|order ids in (your|the) store", low):
        return (
            "For your privacy and security, I can only assist with your specific order. "
            "Please provide your 5-digit order ID, or check your email for order details. If you need help, I'm here for you!"
        )
    if order_id:
        if len(order_id) < 5:
            return (
                "Could you please provide the full 5-digit order ID from your order confirmation email or receipt? "
                "This will help me assist you more efficiently."
            )
        order = _ORDERS.get(order_id)
        if order:
            eta_days = int(order.get("eta_days", 0) or 0)
            eta_part = (
                f" and is expected to arrive in {eta_days} day{'s' if eta_days != 1 else ''}"
                if eta_days > 0 else ""
            )
            items = ", ".join(order.get("items", [])) or "no listed items"
            total = format_money(order.get('total', '?'))
            status = order.get('status', 'unknown').capitalize()
            return (
                f"Thank you for your query! Your order {order_id} is currently {status}{eta_part}. "
                f"Items in this order: {items}. The total amount is {total}. "
                f"If you need further assistance, please let me know."
            )
        return (
            f"I'm sorry, but I couldn't find order {order_id}. "
            "Please double-check your order ID, or contact our support team if you need further assistance."
        )

    if "order" in low and not re.search(r"\d", prompt):
        return (
            "No worries at all! If you don't remember your order ID, please check your order confirmation email or your account order history. "
            "If you need more help, just let me know—I'm happy to assist!"
        )

    # Common order-tracking phrasing without explicit "order" token.
    if any(k in low for k in ["track", "where is my package", "where is my parcel", "delivery status"]):
        return (
            "To help you track your package, please provide your 5-digit order ID from your confirmation email. "
            "If you can't find it, just let me know and I'll guide you further."
        )

    # Product info queries
    for product in _PRODUCTS:
        name = str(product.get("name", "")).lower()
        if name and name in low:
            price = format_money(product.get("price", "?"))
            stock = product.get("stock", "?")
            rating = product.get("rating", "?")
            category = product.get("category", "?")
            desc = product.get("description", "")
            return (
                f"Here are the details for {product.get('name')}: {desc} "
                f"Price: {price}, Stock: {stock}, Rating: {rating}, Category: {category}. "
                "If you would like to place an order or need more information, please let me know!"
            )

    # If user asks about a product not found
    if any(word in low for word in ["cost", "price", "stock", "rating", "category", "describe", "details", "tell me about"]):
        return (
            "I'm sorry, I couldn't find that product in our store. "
            "Please check the product name or browse our catalog for available items. If you need help, just ask!"
        )

    for p in _PRODUCTS:
        name = str(p.get("name", "")).strip()
        if name and name.lower() in low:
            return (
                f"Here is what I found for {name}: Price is {format_money(p.get('price'))}, Stock: {p.get('stock')}, "
                f"Rating: {p.get('rating')}, Category: {p.get('category')}, Description: {p.get('description', 'no description')}. "
                "Let me know if you need more details or wish to order!"
            )

    # Category-level product queries (e.g. smartphones, laptops, audio).
    for category, plist in _CATEGORY_INDEX.items():
        if category in low:
            names = ", ".join(str(p.get("name", "")).strip() for p in plist[:3] if p.get("name"))
            return (
                f"We have several {category} items, including {names}. "
                "If you want more options or details, just let me know!"
            )

    # Simple stock/price/rating intent with product name mention.
    if any(k in low for k in ["stock", "available", "price", "cost", "rating"]):
        for p in _PRODUCTS:
            name = str(p.get("name", "")).strip()
            if name and name.lower() in low:
                parts = []
                if "stock" in low or "available" in low:
                    parts.append(f"Stock: {p.get('stock')}")
                if "price" in low or "cost" in low:
                    parts.append(f"Price: {format_money(p.get('price'))}")
                if "rating" in low:
                    parts.append(f"Rating: {p.get('rating')}")
                if parts:
                    return (
                        f"Here is the information for {name}: " + ", ".join(parts) + ". "
                        "If you need more details or want to order, please let me know!"
                    )

    if "return" in low or "refund" in low:
        if _POLICIES.get("return"):
            return (
                f"Here is our return policy: {_POLICIES['return']} "
                "If you have any questions or need help with a return, please let me know!"
            )
    if "shipping" in low or "delivery" in low:
        if _POLICIES.get("shipping"):
            return (
                f"Here is our shipping policy: {_POLICIES['shipping']} "
                "If you need more details or have questions, I'm happy to help!"
            )
    if "warranty" in low:
        if _POLICIES.get("warranty"):
            return (
                f"Here is our warranty policy: {_POLICIES['warranty']} "
                "If you need more information or have concerns, please let me know!"
            )

    return None


# ---------------------------------------------------------------------------
# LLM back-ends
# ---------------------------------------------------------------------------
def build_llm_messages(prompt: str, history: list) -> list:
    """
    Build a list of messages for LLM chat completion APIs.
    Args:
        prompt (str): User prompt.
        history (list): Conversation history.
    Returns:
        list: List of message dicts for LLM input.
    """
    """
    Build a list of messages for LLM chat completion APIs.
    Returns:
        list: List of message dicts for LLM input.
    """
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    for turn in (history or [])[-3:]:
        if turn.get("user"):
            messages.append({"role": "user",      "content": turn["user"]})
        if turn.get("assistant"):
            messages.append({"role": "assistant", "content": turn["assistant"]})
    messages.append({"role": "user", "content": prompt})
    return messages


def call_openai_llm(prompt: str, history: list) -> str:
    """
    Call the OpenAI LLM API for a chat completion.
    Handles retries, timeout, and logging.
    Args:
        prompt (str): User prompt.
        history (list): Conversation history.
    Returns:
        str: The LLM's response as a string.
    """
    """
    Call the OpenAI LLM API for a chat completion.
    Returns:
        str: The LLM's response as a string.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    from openai import OpenAI
    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini").strip()
    temperature = float(os.environ.get("OPENAI_TEMPERATURE", "0.2"))
    max_tokens = int(os.environ.get("OPENAI_MAX_TOKENS", "80"))
    timeout = int(os.environ.get("OPENAI_TIMEOUT_SECONDS", "30"))
    retries = int(os.environ.get("OPENAI_RETRIES", "3"))
    backoff = float(os.environ.get("OPENAI_RETRY_BACKOFF", "2.0"))

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = OpenAI(api_key=api_key, timeout=timeout).chat.completions.create(
                model=model,
                messages=build_llm_messages(prompt, history),
                max_tokens=max_tokens,
                temperature=temperature,
            )
            logger.info(f"[LLM] OpenAI model used: {model}")
            return resp.choices[0].message.content.strip()
        except Exception as e:
            last_error = e
            if attempt >= retries:
                break
            logger.warning(f"[LLM] OpenAI attempt {attempt}/{retries} failed ({type(e).__name__}); retrying...")
            if backoff > 0:
                time.sleep(backoff * attempt)
    if last_error:
        raise last_error
    raise RuntimeError("OpenAI call failed without a reported exception")


def call_ollama_llm(prompt: str, history: list) -> str:
    """
    Call the Ollama LLM API for a chat completion.
    Handles retries, timeout, and logging.
    Args:
        prompt (str): User prompt.
        history (list): Conversation history.
    Returns:
        str: The LLM's response as a string.
    """
    """
    Call the Ollama LLM API for a chat completion.
    Returns:
        str: The LLM's response as a string.
    """
    model = os.environ.get("OLLAMA_MODEL", "").strip()
    if not model:
        raise RuntimeError("OLLAMA_MODEL not set")
    logger.info(f"[LLM] Ollama model used: {model}")
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    timeout     = max(10, int(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "12")))
    num_predict = int(os.environ.get("OLLAMA_NUM_PREDICT", "60"))
    attempts    = max(1, int(os.environ.get("OLLAMA_RETRIES", "2")))
    backoff_s   = max(0.0, float(os.environ.get("OLLAMA_RETRY_BACKOFF_SECONDS", "1.0")))

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.post(
                f"{base_url}/api/chat",
                json={
                    "model":   model,
                    "stream":  False,
                    "options": {"temperature": 0.2, "num_predict": num_predict},
                    "messages": build_llm_messages(prompt, history),
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            text = resp.json().get("message", {}).get("content", "").strip()
            if not text:
                raise RuntimeError("Ollama returned empty response")
            return text
        except (requests.exceptions.Timeout, requests.exceptions.RequestException) as e:
            last_error = e
            if attempt >= attempts:
                break
            logger.warning(
                f"[LLM] Ollama attempt {attempt}/{attempts} failed ({type(e).__name__}); retrying..."
            )
            if backoff_s > 0:
                time.sleep(backoff_s * attempt)

    if last_error:
        raise last_error
    raise RuntimeError("Ollama call failed without a reported exception")


def warmup_ollama() -> None:
    """
    Best-effort warmup to reduce first-turn LLM latency.
    Returns:
        None
    """
    """
    Best-effort warmup to reduce first-turn LLM latency.
    """
    model = os.environ.get("OLLAMA_MODEL", "").strip()
    if not model:
        return
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    try:
        requests.post(
            f"{base_url}/api/chat",
            json={"model": model, "stream": False, "options": {"num_predict": 1},
                  "messages": [{"role": "user", "content": "hi"}]},
            timeout=5,
        )
        logger.info("[LLM] Ollama warmup complete")
    except Exception as e:
        logger.warning(f"[LLM] Ollama warmup skipped: {e}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_response(user_text: str, history: list = None) -> str:
    """
    Generate a concise, TTS-friendly response to a user query using the LLM.
    Handles polite fallback and conversational tone.
    Embeds the full store dataset in the system prompt for context.
    Args:
        user_text (str): Raw transcription from STT.
        history (list, optional): List of previous conversation turns.
    Returns:
        str: Short, context-aware response for the user.
    """
    # First, try deterministic handler for order/product/category queries
    deterministic = handle_user_query(user_text)
    if deterministic:
        return deterministic

    prompt = f"{_SYSTEM_PROMPT}\nUser: {user_text}\nAssistant:"

    # Try OpenAI if API key is set
    if os.environ.get("OPENAI_API_KEY", "").strip():
        try:
            result = squeeze_whitespace(call_openai_llm(prompt, history))
            logger.info(f"[LLM] OpenAI → {result[:80]}")
            # Make response more polite and conversational
            if result and not result.endswith(('.', '!', '?')):
                result += '.'
            result = result.replace("I couldn't fetch that right now. Please try again.", "I'm sorry, I couldn't get that information right now. Could you please try again in a moment?")
            return result
        except Exception as e:
            logger.warning(f"[LLM] OpenAI failed: {e}", exc_info=True)

    # Try Ollama if model is set
    if os.environ.get("OLLAMA_MODEL", "").strip():
        try:
            result = squeeze_whitespace(call_ollama_llm(prompt, history))
            logger.info(f"[LLM] Ollama → {result[:80]}")
            # Make response more polite and conversational
            if result and not result.endswith(('.', '!', '?')):
                result += '.'
            result = result.replace("I couldn't fetch that right now. Please try again.", "I'm sorry, I couldn't get that information right now. Could you please try again in a moment?")
            return result
        except Exception as e:
            logger.warning(f"[LLM] Ollama failed: {e}", exc_info=True)
    else:
        logger.warning("[LLM] No LLM configured — set OPENAI_API_KEY or OLLAMA_MODEL in .env")

    # Fallback if no LLM is available
    return "I'm sorry, I couldn't get that information right now. Could you please try again in a moment?"
