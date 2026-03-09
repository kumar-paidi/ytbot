from pyrogram import Client

# Replace these with your actual values from my.telegram.org
API_ID   = 38717722        # your api_id (number)
API_HASH = "fb977e5833ae894e0848f7e280f10ac7" # your api_hash (string)

with Client("my_account", api_id=API_ID, api_hash=API_HASH) as app:
    print("\n✅ Your session string is:\n")
    print(app.export_session_string())
    print("\n⚠️ Keep this secret! Never share it with anyone.")
