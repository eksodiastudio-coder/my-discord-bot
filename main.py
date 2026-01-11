import discord
from discord.ext import commands
import os
import socket
import time
from flask import Flask
from threading import Thread

# 1. Web Server
app = Flask('')
@app.route('/')
def home():
    return "Bot is running!"

def run_web_server():
    app.run(host='0.0.0.0', port=7860)

# 2. Network Checker
def wait_for_internet():
    print("Checking for internet connection...")
    while True:
        try:
            # Try to resolve Google's DNS to see if the network is up
            socket.gethostbyname("www.google.com")
            print("Internet connection detected!")
            return True
        except socket.gaierror:
            print("Network not ready yet. Retrying in 5 seconds...")
            time.sleep(5)

# 3. Bot Setup
TOKEN = os.getenv("DISCORD_TOKEN")
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'Successfully logged into Discord as {bot.user.name}')

@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")

if __name__ == "__main__":
    # Start web server
    t = Thread(target=run_web_server)
    t.daemon = True
    t.start()
    
    # Wait for network
    if wait_for_internet():
        print("Starting Discord Bot...")
        try:
            bot.run(TOKEN)
        except Exception as e:
            print(f"FATAL ERROR: {e}")