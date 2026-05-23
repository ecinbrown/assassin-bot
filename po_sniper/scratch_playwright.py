import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        try:
            print("Testing launch_persistent_context with storage_state...")
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir="./temp_profile",
                storage_state="auth_state.json"
            )
            print("Success!")
            await ctx.close()
        except Exception as e:
            print("Error:", e)

if __name__ == "__main__":
    asyncio.run(main())
