import discord
import random
import datetime
import io
import asyncio
import os
from discord.ext import commands, tasks
from discord.ui import Button, View
from flask import Flask
from threading import Thread

# --- KOYEB WEB SERVER SETUP ---
app = Flask('')

@app.route('/')
def home():
    return "Ticket Bot is Online!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.daemon = True
    t.start()

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("DISCORD_TOKEN") 
GUILD_ID = 1428466555850719347  
TICKET_CATEGORY_ID = 1428466916166598818 
STAFF_ROLE_ID = 1428466660012200036 
STAFF_LEAD_ROLE_ID = 1459994445121323079
LOG_CHANNEL_ID = 1428478091474505750      

SUPERVISOR_ROLE_ID = 1428489953477922996  
INACTIVE_ROLE_ID = 1428490017420087478    
COMPLAINT_CATEGORY_ID = 1428497122759671881 
COMPLAINT_LOG_CHANNEL_ID = 1428499253952774176
FEEDBACK_LOG_CHANNEL_ID = 1430296240528294049 

INACTIVITY_WARN_AFTER_HOURS = 24
INACTIVITY_CLOSE_AFTER_HOURS = 48
CHECK_INTERVAL_MINUTES = 5

# --- CANNED RESPONSES ---
MACROS = { 
    "welcome": "Hello! How can I assist you today?", 
    "bug_report_questions": "1. What is the bug?\n2. Where does it happen?\n3. Steps to reproduce?", 
    "server_issue_questions": "Please describe the server issue and provide any screenshots if possible.", 
    "closing": "Is there anything else I can help with before closing?" 
}

# --- BOT SETUP ---
class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(TicketControlPanelView())
        self.add_view(TicketActionView())

bot = MyBot()

# --- HELPER FUNCTIONS ---
def is_staff_or_supervisor(interaction: discord.Interaction) -> bool:
    staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
    staff_lead_role = interaction.guild.get_role(STAFF_LEAD_ROLE_ID)
    supervisor_role = interaction.guild.get_role(SUPERVISOR_ROLE_ID)
    return (staff_role and staff_role in interaction.user.roles) or (supervisor_role and supervisor_role in interaction.user.roles) or (staff_lead_role and staff_lead_role in interaction.user.roles)

# --- LOGGING & CLOSING ---
async def close_and_log_ticket(interaction_or_channel, closer_member, reason="Ticket Closed"):
    channel = interaction_or_channel if isinstance(interaction_or_channel, discord.TextChannel) else interaction_or_channel.channel
    guild = channel.guild
    
    log_channel_id = COMPLAINT_LOG_CHANNEL_ID if channel.category_id == COMPLAINT_CATEGORY_ID else LOG_CHANNEL_ID
    log_channel = guild.get_channel(log_channel_id)

    messages = []
    async for message in channel.history(limit=None, oldest_first=True):
        messages.append(f"[{message.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {message.author}: {message.clean_content}")
    
    full_transcript = "\n".join(messages)
    transcript_file = discord.File(io.StringIO(full_transcript), filename=f"transcript-{channel.name}.txt")
    
    ticket_id = "N/A"
    owner_member = None
    if channel.topic:
        if "| ID: " in channel.topic: 
            ticket_id = channel.topic.split("| ID: ")[1].strip()
        if "Ticket for " in channel.topic:
            try: 
                owner_id = int(channel.topic.split("for ")[1].split(" |")[0].strip())
                owner_member = await guild.fetch_member(owner_id)
            except: pass

    log_embed = discord.Embed(title="Ticket Closed", color=discord.Color.orange(), timestamp=datetime.datetime.utcnow())
    log_embed.add_field(name="Ticket ID", value=f"`{ticket_id}`")
    log_embed.add_field(name="Opened By", value=owner_member.mention if owner_member else "Unknown")
    log_embed.add_field(name="Closed By", value=closer_member.mention)
    
    if log_channel: 
        await log_channel.send(content=f"Ticket ID: `{ticket_id}`", embed=log_embed, file=transcript_file)
    
    if owner_member and channel.category_id != COMPLAINT_CATEGORY_ID:
        try: 
            await owner_member.send(f"Your ticket (`{ticket_id}`) has been closed. Rate your experience:", view=FeedbackRatingView(ticket_id, closer_member))
        except: pass

    await channel.send("This ticket is logged and will be deleted in 5 seconds.")
    await asyncio.sleep(5)
    await channel.delete()

# --- VIEWS ---
class FeedbackRatingView(View):
    def __init__(self, ticket_id: str, closer_member: discord.Member):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
        self.closer_member = closer_member

    async def _process_rating(self, i, rating):
        for item in self.children: item.disabled = True
        await i.response.edit_message(content=f"Thank you! You rated this **{rating}/5 stars**.", view=self)
        feedback_channel = i.client.get_channel(FEEDBACK_LOG_CHANNEL_ID)
        if feedback_channel:
            embed = discord.Embed(title="New Support Feedback", color=discord.Color.gold())
            embed.add_field(name="Rating", value=f"{'⭐' * rating} ({rating}/5)")
            embed.add_field(name="Ticket ID", value=f"`{self.ticket_id}`")
            embed.add_field(name="Handled By", value=self.closer_member.mention)
            await feedback_channel.send(embed=embed)

    @discord.ui.button(label="1", style=discord.ButtonStyle.danger)
    async def r1(self, b, i): await self._process_rating(i, 1)
    @discord.ui.button(label="2", style=discord.ButtonStyle.danger)
    async def r2(self, b, i): await self._process_rating(i, 2)
    @discord.ui.button(label="3", style=discord.ButtonStyle.secondary)
    async def r3(self, b, i): await self._process_rating(i, 3)
    @discord.ui.button(label="4", style=discord.ButtonStyle.success)
    async def r4(self, b, i): await self._process_rating(i, 4)
    @discord.ui.button(label="5", style=discord.ButtonStyle.success)
    async def r5(self, b, i): await self._process_rating(i, 5)

class TicketActionView(View):
    def __init__(self, show_claim: bool = True):
        super().__init__(timeout=None)
        if not show_claim:
            for item in self.children:
                if item.custom_id == "claim_ticket":
                    self.remove_item(item)

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success, custom_id="claim_ticket", emoji="🙋")
    async def claim_ticket_button(self, interaction: discord.Interaction, button: Button):
        if not is_staff_or_supervisor(interaction): 
            return await interaction.response.send_message("Only staff can claim tickets.", ephemeral=True)
        button.disabled = True
        button.label = f"Claimed by {interaction.user.display_name}"
        await interaction.message.edit(view=self)
        await interaction.response.send_message(f"Ticket claimed by {interaction.user.mention}")

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, custom_id="close_ticket", emoji="🔒")
    async def close_ticket_button(self, interaction: discord.Interaction, button: Button):
        if not is_staff_or_supervisor(interaction): 
            return await interaction.response.send_message("Permission denied.", ephemeral=True)
        await interaction.response.send_message("Closing ticket...")
        await close_and_log_ticket(interaction, interaction.user)

class TicketControlPanelView(View):
    def __init__(self): super().__init__(timeout=None)

    async def _create_ticket(self, interaction, ticket_type, questions, category_id, roles_to_add):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        category = guild.get_channel(category_id)
        
        for channel in category.text_channels:
            if channel.topic and str(interaction.user.id) in channel.topic:
                return await interaction.followup.send(f"You already have a ticket here: {channel.mention}", ephemeral=True)

        ticket_id = f"{ticket_type[:3].upper()}-{random.randint(1000, 9999)}-{random.randint(100, 999)}"
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        for role in roles_to_add:
            if role: overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        channel = await category.create_text_channel(
            name=f"{ticket_type}-{interaction.user.name}",
            overwrites=overwrites,
            topic=f"Ticket for {interaction.user.id} | ID: {ticket_id}"
        )

        embed = discord.Embed(title=f"{ticket_type} Support Request", description=f"Hello {interaction.user.mention}!\n\n**Please provide details:**\n{questions}", color=discord.Color.blue())
        await channel.send(embed=embed, view=TicketActionView(show_claim=(ticket_type != "Complaint")))
        
        # --- FIX: Message is now Ephemeral AND deletes itself after 10 seconds ---
        msg = await interaction.followup.send(f"Ticket created: {channel.mention}", ephemeral=True)
        await asyncio.sleep(10)
        try:
            await msg.delete()
        except:
            pass

    @discord.ui.button(label="Server Support", style=discord.ButtonStyle.primary, custom_id="btn_server", emoji="🖥️")
    async def server_support(self, interaction: discord.Interaction, button: Button): 
        await self._create_ticket(interaction, "Server", MACROS["server_issue_questions"], TICKET_CATEGORY_ID, [interaction.guild.get_role(STAFF_ROLE_ID)], [interaction.guild.get_role(STAFF_LEAD_ROLE_ID)])

    @discord.ui.button(label="Game Support", style=discord.ButtonStyle.success, custom_id="btn_game", emoji="🎮")
    async def game_support(self, interaction: discord.Interaction, button: Button): 
        await self._create_ticket(interaction, "Game", MACROS["bug_report_questions"], TICKET_CATEGORY_ID, [interaction.guild.get_role(STAFF_ROLE_ID)], [interaction.guild.get_role(STAFF_LEAD_ROLE_ID)])

    @discord.ui.button(label="File a Complaint", style=discord.ButtonStyle.danger, custom_id="btn_complaint", emoji="⚖️")
    async def complaint(self, interaction: discord.Interaction, button: Button): 
        await self._create_ticket(interaction, "Complaint", "Describe your complaint in detail.", COMPLAINT_CATEGORY_ID, [interaction.guild.get_role(SUPERVISOR_ROLE_ID)])

# --- TASKS & EVENTS ---
@tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
async def check_inactive_tickets():
    await bot.wait_until_ready()
    guild = bot.get_guild(GUILD_ID)
    if not guild: return
    category = guild.get_channel(TICKET_CATEGORY_ID)
    if not category: return
    now, warn_delta, close_delta = discord.utils.utcnow(), datetime.timedelta(hours=INACTIVITY_WARN_AFTER_HOURS), datetime.timedelta(hours=INACTIVITY_CLOSE_AFTER_HOURS)
    
    for channel in category.text_channels:
        if not channel.topic or "Ticket for" not in channel.topic: continue
        try:
            msgs = [m async for m in channel.history(limit=1)]
            if not msgs: continue
            last_msg = msgs[0]
            if now - last_msg.created_at > close_delta:
                await close_and_log_ticket(channel, bot.user, "Inactivity")
            elif now - last_msg.created_at > warn_delta:
                if not (last_msg.author == bot.user):
                    await channel.send("This ticket is inactive and will be closed soon.")
        except: continue

@bot.event
async def on_ready():
    print(f"--- BOT IS ONLINE AS {bot.user.name} ---")
    bot.add_view(TicketControlPanelView())
    bot.add_view(TicketActionView())

    try:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        print(f"SUCCESS: Synced commands to guild {GUILD_ID}")
    except Exception as e:
        print(f"SYNC ERROR: {e}")

    if not check_inactive_tickets.is_running():
        check_inactive_tickets.start()

# --- PREFIX COMMAND FOR MANUAL SYNC ---
@bot.command()
@commands.has_permissions(administrator=True)
async def sync(ctx):
    try:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        await ctx.send(f"✅ Commands synced!")
    except Exception as e:
        await ctx.send(f"❌ Sync failed: {e}")

# --- SLASH COMMAND ---
# --- FIX: Added default_permissions to hide from non-admins ---
@bot.tree.command(name="setup_tickets", description="Setup the ticket support panel")
@discord.app_commands.default_permissions(administrator=True)
async def setup_tickets(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Support Center", 
        description=(
            "Please select the appropriate category for your support request below. "
            "A private channel will be opened for you to speak with our team.\n\n"
            "🖥️ **Server Support**\nFor issues related to the Discord server itself (roles, channels, members).\n\n"
            "🎮 **Game Support**\nFor bugs, questions, or issues related to the game.\n\n"
            "⚖️ **File a Complaint**\n*Supervisor-Only:* Use this to file a formal complaint about a user or situation."
        ), 
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, view=TicketControlPanelView())

# --- EXECUTION ---
if __name__ == "__main__":
    keep_alive()
    if BOT_TOKEN:
        bot.run(BOT_TOKEN)
    else:
        print("CRITICAL: No DISCORD_TOKEN found!")

