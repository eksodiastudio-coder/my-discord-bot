import discord
from discord.ext import commands
import os
from flask import Flask
from threading import Thread

# 1. Flask Web Server (Required for Koyeb Free Tier)
app = Flask('')

@app.route('/')
def home():
    return "Bot is online!"

def run_web_server():
    # Koyeb gives you a 'PORT' environment variable, usually 8080
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.daemon = True
    t.start()

# 2. Discord Bot Setup
TOKEN = os.getenv("DISCORD_TOKEN")
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')

@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")

# 3. Execution
if __name__ == "__main__":
    keep_alive()  # Start the web server
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("No DISCORD_TOKEN found!")
