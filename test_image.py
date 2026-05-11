import os
import asyncio
import base64
from openai import AsyncOpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

async def test_image_reading():
    api_key = os.getenv("OPENAI_API_KEY")
    api_base = os.getenv("OPENAI_API_BASE")
    model = os.getenv("DEFAULT_MODEL", "GLM-5.1")
    
    print(f"Testing Image reading with model: {model}")
    # Try using glm-4v-plus for vision if the default model doesn't support it
    if model == "GLM-5.1":
        model = "glm-4v-plus"
        print(f"Overriding model to {model} because GLM-5.1 may not support vision.")

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=api_base,
    )

    image_path = "1.png"
    
    if not os.path.exists(image_path):
        print(f"Error: Could not find file {image_path}")
        return

    try:
        # Read the image file and encode it in base64
        with open(image_path, "rb") as f:
            image_bytes = f.read()
            image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        
        print(f"Successfully loaded Image. Base64 length: {len(image_base64)}")
        print("Sending request to LLM... (This might take a while)")

        # Standard OpenAI Multimodal payload format
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "请详细描述一下这张图片里的内容，包含色彩、景色和氛围。"
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_base64}",
                            "detail": "high"
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
        print("1. The API endpoint might not support vision inputs.")
        print(f"2. The model '{model}' might not be a multimodal model (try glm-4v).")

if __name__ == "__main__":
    asyncio.run(test_image_reading())
