import os
import discord
from datetime import datetime, timezone
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceExistsError as BlobExistsError
from azure.core.exceptions import ResourceNotFoundError as AzureResourceNotFoundError
from azure.cosmos import CosmosClient, PartitionKey
from azure.cosmos.exceptions import CosmosHttpResponseError as CosmosError
from uuid import uuid4
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()
raw_ids = os.getenv("ALLOWED_USERS")
ALLOWED_USERS = {int(uid.strip()) for uid in raw_ids.split(",") if uid.strip().isdigit()}
AZURE_CONNECTION_STRING = os.getenv("AZURE_CONNECTION_STRING")
AZURE_CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME")
#print("AZURE STORAGE:", AZURE_CONNECTION_STRING, AZURE_CONTAINER_NAME)
BOT_TOKEN = os.getenv("PROJO_DISCORD_BOT")

# cosmos db configs
import os
import uuid
from datetime import datetime
from azure.cosmos import CosmosClient, PartitionKey
from dotenv import load_dotenv

load_dotenv()

# Load config
COSMOS_URI = os.getenv("COSMOS_URI")
COSMOS_KEY = os.getenv("COSMOS_KEY")
COSMOS_DB = os.getenv("COSMOS_DB")
COSMOS_CONTAINER = os.getenv("COSMOS_CONTAINER")


blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
container_client = blob_service_client.get_container_client(AZURE_CONTAINER_NAME)

def push_to_blob(file_data, filename):
    try:
        # The filename parameter should already contain the full path (year/month/filename)
        container_client.upload_blob(name=filename, data=file_data)
        return filename
    except BlobExistsError:
        logger.error(f"Blob {filename} already exists")
        raise
    except AzureResourceNotFoundError as e:
        logger.error(f"Azure resource not found: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error uploading to blob storage: {str(e)}")
        raise

# cosmos db configs
# Cosmos setup (global for reuse)
cosmos_client = CosmosClient(COSMOS_URI, credential=COSMOS_KEY)
database = cosmos_client.get_database_client(COSMOS_DB)
container = database.get_container_client(COSMOS_CONTAINER)

def save_note_metadata(
    note_id,
    timestamp,
    user_id,
    blob_url=None,
    blob_path=None,
    filename=None,
    user_caption="",
    text_message=None,
    note_type="image"
):
    try:
        metadata = {
            "id": note_id,
            "user_id": str(user_id),
            "timestamp": timestamp,
            "user_caption": user_caption,
            "ai_description": "",
            "type": note_type,
        }

        if blob_url:
            metadata["blob_url"] = blob_url
        if blob_path:
            metadata["blob_path"] = blob_path
        if filename:
            metadata["filename"] = filename
        if text_message:
            metadata["text_message"] = text_message

        container.create_item(metadata)
        return note_id
    except CosmosError as e:
        logger.error(f"Cosmos DB error: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error saving metadata: {str(e)}")
        raise


intents = discord.Intents.default()
intents.message_content = True  # Needed to read messages
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    try:
        logger.info(f'Bot is online! Logged in as {client.user}')
    except Exception as e:
        logger.error(f"Error in on_ready: {str(e)}")

@client.event
async def on_message(message):
    try:
        if message.author == client.user:
            return
        
        if message.author.id not in ALLOWED_USERS:
            await message.channel.send("🚫 I don't know you. If you think I should, please reach out to the admin.")
            return
        
        if message.content.lower() == "help":
            await message.channel.send("I can save your messages and images. Just send them to me!")
            return
        if message.content.lower() == "ping":
            await message.channel.send("pong")
            return
        if message.content.lower() == "test":   
            await message.channel.send("test")
            return

        now = datetime.now(timezone.utc)
        timestamp = now.isoformat() + "Z"

        # Handle attachments (images)
        if message.attachments:
            for attachment in message.attachments:
                if any(attachment.filename.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                    try:
                        timestamp_str = now.strftime("%Y-%m-%d_%H-%M-%S")
                        year = now.strftime("%Y")
                        month = now.strftime("%m")

                        original_filename = attachment.filename
                        note_id = str(uuid.uuid4())
                        new_filename = f"{timestamp_str}_{note_id}_discord_img{os.path.splitext(original_filename)[1]}"
                        blob_path = f"{year}/{month}/{new_filename}"

                        file_data = await attachment.read()
                        push_to_blob(file_data=file_data, filename=blob_path)

                        blob_url = f"https://{blob_service_client.account_name}.blob.core.windows.net/{AZURE_CONTAINER_NAME}/{blob_path}"

                        save_note_metadata(
                            note_id=note_id,
                            timestamp=timestamp,
                            user_id=message.author.id,
                            blob_url=blob_url,
                            blob_path=blob_path,
                            filename=new_filename,
                            user_caption=message.content if message.content else "",
                            note_type="image"
                        )

                        await message.channel.send("🖼️ Image saved to Blob and metadata recorded!")
                        await message.add_reaction("✅")

                    except (BlobExistsError, AzureResourceNotFoundError, CosmosError) as e:
                        logger.error(f"Error processing attachment: {str(e)}")
                        await message.channel.send("❌ Sorry, there was an error processing your image. Please try again later.")
                        await message.add_reaction("❌")
                    except Exception as e:
                        logger.error(f"Unexpected error processing attachment: {str(e)}")
                        await message.channel.send("❌ An unexpected error occurred. Please try again later.")
                        await message.add_reaction("❌")

        # Handle text-only messages
        elif message.content.strip():
            try:
                note_id = str(uuid.uuid4())
                save_note_metadata(
                    note_id=note_id,
                    timestamp=timestamp,
                    user_id=message.author.id,
                    text_message=message.content,
                    note_type="text-only"
                )
                await message.channel.send("📝 Text message saved to memory!")
                await message.add_reaction("✅")
            except Exception as e:
                logger.error(f"Error saving text-only message: {str(e)}")
                await message.channel.send("❌ Failed to save your message. Try again.")
                await message.add_reaction("❌")

    except discord.Forbidden:
        logger.error("Bot doesn't have required permissions")
    except discord.HTTPException as e:
        logger.error(f"Discord HTTP error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in on_message: {str(e)}")


# run client in production
try:
    client.run(BOT_TOKEN, reconnect=True)
except discord.LoginFailure:
    logger.error("Failed to log in to Discord. Check your bot token.")
except discord.ConnectionClosed:
    logger.error("Connection to Discord closed unexpectedly")
except Exception as e:
    logger.error(f"Unexpected error running bot: {str(e)}")