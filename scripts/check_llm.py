"""验证 .env 里的 LLM 配置是不是真的能通。"""
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

key  = os.getenv("OPENAI_API_KEY", "")
base = os.getenv("OPENAI_API_BASE", "")
mdl  = os.getenv("DEFAULT_MODEL", "")

print("=" * 60)
print("Env loaded:")
print(f"  OPENAI_API_KEY  : {'***' + key[-6:] if key else '(MISSING)'}  len={len(key)}")
print(f"  OPENAI_API_BASE : {base or '(MISSING)'}")
print(f"  DEFAULT_MODEL   : {mdl or '(MISSING)'}")
print("=" * 60)

if not (key and base and mdl):
    print("❌ 配置不全,先检查 .env")
    raise SystemExit(1)

client = OpenAI(api_key=key, base_url=base)

# Step 1: 列模型(确认 key + base 通)
print("\n[Step 1] 列可用模型(前 20 个):")
try:
    models = client.models.list()
    ids = [m.id for m in models.data]
    for m in ids[:20]:
        marker = " ← 你配的" if m == mdl else ""
        print(f"  - {m}{marker}")
    if mdl not in ids:
        print(f"\n⚠️  你配的 model id `{mdl}` 不在可用列表里!")
        print(f"   含 'claude' 的可选: {[m for m in ids if 'claude' in m.lower()]}")
except Exception as e:
    print(f"❌ 列模型失败: {type(e).__name__}: {e}")
    raise SystemExit(2)

# Step 2: 真发一条 chat 请求
print(f"\n[Step 2] 用 model={mdl} 发一条测试请求:")
try:
    resp = client.chat.completions.create(
        model=mdl,
        messages=[{"role": "user", "content": "Reply with the single word: pong"}],
        max_tokens=10,
    )
    msg = resp.choices[0].message.content
    print(f"✅ 返回: {msg!r}")
    print(f"   usage: prompt={resp.usage.prompt_tokens}  completion={resp.usage.completion_tokens}")
except Exception as e:
    print(f"❌ chat 失败: {type(e).__name__}: {e}")
    raise SystemExit(3)

# Step 3: 测 function calling(挖因子必须用)
print(f"\n[Step 3] 测 function calling 能力(挖因子必备):")
try:
    resp = client.chat.completions.create(
        model=mdl,
        messages=[{"role": "user", "content": "Call the test tool with x=42"}],
        tools=[{
            "type": "function",
            "function": {
                "name": "test_tool",
                "description": "A test tool",
                "parameters": {
                    "type": "object",
                    "properties": {"x": {"type": "integer"}},
                    "required": ["x"],
                },
            },
        }],
        tool_choice="auto",
        max_tokens=100,
    )
    if resp.choices[0].message.tool_calls:
        tc = resp.choices[0].message.tool_calls[0]
        print(f"✅ Tool calling OK: {tc.function.name}({tc.function.arguments})")
    else:
        print(f"⚠️  模型没调工具,返回了纯文本: {resp.choices[0].message.content!r}")
        print(f"   挖因子需要 function calling,这个模型/代理可能不支持。")
except Exception as e:
    print(f"❌ function calling 失败: {type(e).__name__}: {e}")
    raise SystemExit(4)

print("\n🎉 全部通过,可以 `python main.py` 开挖了!")
