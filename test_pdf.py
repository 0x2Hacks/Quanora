import os
import asyncio
import base64
from dotenv import load_dotenv
from openai import AsyncOpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

async def test_pdf_reading():
    api_key = os.getenv("OPENAI_API_KEY")
    api_base = os.getenv("OPENAI_API_BASE")
    model = os.getenv("DEFAULT_MODEL", "GLM-5.1") # Fallback if not set
    
    print(f"Testing PDF reading with model: {model}")
    print(f"API Base: {api_base}")

    # The Anthropic API expects base URL without the trailing slash or specific endpoint
    # OpenAI client will automatically append /chat/completions
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=api_base,
    )

    pdf_path = "从创新高个股看市场热点.pdf"
    
    if not os.path.exists(pdf_path):
        print(f"Error: Could not find file {pdf_path}")
        return

    try:
        # Read the PDF file and encode it in base64
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
            pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
        
        print(f"Successfully loaded PDF. Base64 length: {len(pdf_base64)}")
        print("Sending request to LLM... (This might take a while)")

        # Construct the message. Note that support for PDF directly in the content array
        # varies significantly between providers. 
        # Some use type: "document" or type: "file"
        
        # Anthropic (which seems to be the target based on API_BASE) supports document type
        # But we are using the OpenAI client wrapper. Let's try the common OpenAI approach first
        # (though OpenAI natively doesn't support PDF directly in chat completions without Assistants API,
        # some proxy/compatible APIs do).
        
        # Since the API_BASE has 'anthropic' in it, it might be a Claude model proxy.
        # Let's try sending it as a document if it's Claude, or as text if we want to just test the endpoint.
        # Anthropic standard:
        # { "type": "document", "source": { "type": "base64", "media_type": "application/pdf", "data": "..." } }
        
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "请阅读这份PDF文件，并用一句话总结它的核心观点。"
                    },
                    # Note: This is an attempt at the Anthropic document format via OpenAI client wrapper.
                    # Behavior depends entirely on how the proxy handles it.
                    {
                        "type": "document", 
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_base64
                        }
                    }
                ]
            }
        ]

        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=1000
        )
        
        print("\n--- Response ---")
        print(response.choices[0].message.content)
        print("----------------")
        
    except Exception as e:
        print(f"\nError occurred while calling the API:")
        print(str(e))
        print("\nPossible reasons:")
        print("1. The API endpoint does not support direct PDF uploading in this format.")
        print("2. The model specified does not support multimodal/document input.")
        print("3. The file is too large for the context window.")

if __name__ == "__main__":
    asyncio.run(test_pdf_reading())
