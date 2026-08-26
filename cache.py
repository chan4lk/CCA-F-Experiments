import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic()

# Generate ~1,500 distinct tokens
policy_text = (
    "Enterprise Security & Data Handling Policy: All data transmitted must be encrypted "
    "using TLS 1.3 at rest and in transit. Customer PII must be scrubbed prior to storage. "
    "API tokens must rotate every 90 days. Unauthenticated endpoints must return HTTP 401. "
    "All SQL queries must use parameterized statements to eliminate injection vectors. "
) * 60

# 1. System prompt with explicit cache breakpoint
system_blocks = [
    {
        "type": "text",
        "text": policy_text,
        "cache_control": {"type": "ephemeral"}
    }
]

# CALL 1: Cache Write
resp1 = client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=100,
    system=system_blocks,
    messages=[{"role": "user", "content": "What is the token rotation policy?"}],
    extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"}  # Compatibility header
)

print("--- CALL 1 ---")
print(f"Tokens Written to Cache : {resp1.usage.cache_creation_input_tokens}")
print(f"Tokens Read from Cache    : {resp1.usage.cache_read_input_tokens}")
print(f"Standard Input Tokens     : {resp1.usage.input_tokens}")

# CALL 2: Cache Read (Hit)
resp2 = client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=100,
    system=system_blocks,
    messages=[{"role": "user", "content": "What encryption standard is required?"}],
    extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"}
)

print("\n--- CALL 2 ---")
print(f"Tokens Written to Cache : {resp2.usage.cache_creation_input_tokens}")
print(f"Tokens Read from Cache    : {resp2.usage.cache_read_input_tokens}")
print(f"Standard Input Tokens     : {resp2.usage.input_tokens}")
