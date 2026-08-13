import discord
import random
import datetime
import io
import asyncio
import os
import aiohttp
from discord.ext import commands, tasks
from discord.ui import Button, View, Modal, TextInput
from flask import Flask, request, jsonify
from threading import Thread
from discord import app_commands

# --- TRANSLATION IMPORTS ---
from deep_translator import GoogleTranslator
from langdetect import detect

# --- KOYEB WEB SERVER SETUP ---
app = Flask('')

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("DISCORD_TOKEN") 
GUILD_ID = 1428466555850719347  
TICKET_CATEGORY_ID = 1537412721975234580 
STAFF_ROLE_ID = 1428466660012200036 
STAFF_LEAD_ROLE_ID = 1459994445121323079
LOG_CHANNEL_ID = 1428478091474505750      

SUPERVISOR_ROLE_ID = 1428489953477922996  
INACTIVITY_ROLE_ID = 1428490017420087478    
COMPLAINT_CATEGORY_ID = 1428497122759671881 
COMPLAINT_LOG_CHANNEL_ID = 1428499253952774176
FEEDBACK_LOG_CHANNEL_ID = 1430296240528294049 

# --- NEXT.JS WEB PORTAL SYNC CONFIG ---
NEXTJS_SYNC_URL = os.getenv("NEXTJS_SYNC_URL", "http://localhost:3000")
WEB_SYNC_SECRET = os.getenv("WEB_SYNC_SECRET", "my_super_secret_key_123")

# --- AUTO-ASSIGNMENT CONFIG ---
TRIAL_MOD_ROLE_ID = 1518663064956702890 
AUTO_ASSIGN_ENABLED = False 
ASSIGNMENT_INDEX = 0 

# --- TRANSLATION & CONCURRENCY LOCK STORES ---
ACTIVE_TRANSLATIONS = {}
CREATING_TICKETS = set()  # Lock set to prevent duplicate creation

INACTIVITY_WARN_AFTER_HOURS = 24
INACTIVITY_CLOSE_AFTER_HOURS = 48
CHECK_INTERVAL_MINUTES = 5

MACROS = { 
    "welcome": "Hello! How can I assist you today?", 
    "game_support_questions": (
        "1. **Appealing Ban please follow the format:**\n"
        "Roblox Username:\n"
        "Date of Ban:\n"
        "Reason of Ban:\n"
        "Appeal(Reasoning on why we should accept the appeal submission):\n\n"
        "2. **Reporting a Player:**\n"
        "Roblox Username(of the player you want to report):\n"
        "Type of Abuse(Hacking, glitching or abusing a bug):\n"
        "Evidence(photos or videos):"
    ), 
    "server_issue_questions": (
        "1. **Appealing a Warning please follow the format:**\n"
        "User/ID:\n"
        "Reason of the warning:\n"
        "Date of the warning:\n"
        "Appeal(Reasoning on why we should accept the appeal submission):\n\n"
        "2. **Appealing a Mute please follow the format:**\n"
        "User/ID:\n"
        "Reason of the mute:\n"
        "Date of the mute:\n"
        "Appeal(Reasoning on why we should accept the appeal submission):\n\n"
        "3. **Appealing a Ban please follow the format:**\n"
        "User/ID:\n"
        "Reason of ban:\n"
        "Date of ban:\n"
        "Appeal(Reasoning on why we should accept the appeal submission):\n\n"
        "4. **Reporting a member** please provide the reason why and any evidence to support your claim."
    ), 
    "closing": "Is there anything else I can help with before closing?" 
}

# --- NEXT.JS SYNC HELPER ---

async def send_to_nextjs(endpoint: str, data: dict):
    """Sends synced ticket/message data to the Next.js Web Portal API."""
    if not NEXTJS_SYNC_URL:
        return
    url = f"{NEXTJS_SYNC_URL.rstrip('/')}{endpoint}"
    headers = {
        "Content-Type": "application/json",
        "x-web-sync-secret": WEB_SYNC_SECRET
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data, headers=headers) as resp:
                if resp.status != 200:
                    print(f"[Web Sync Error] Next.js returned status {resp.status} for {endpoint}")
    except Exception as e:
        print(f"[Web Sync Exception] Could not reach Next.js server: {e}")

# --- HELPERS ---

def is_staff_or_higher(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    staff_roles = {STAFF_ROLE_ID, STAFF_LEAD_ROLE_ID, SUPERVISOR_ROLE_ID, TRIAL_MOD_ROLE_ID}
    return any(role.id in staff_roles for role in interaction.user.roles)

def is_staff_or_higher_user(user: discord.User | discord.Member) -> bool:
    if not isinstance(user, discord.Member):
        return False
    staff_roles = {STAFF_ROLE_ID, STAFF_LEAD_ROLE_ID, SUPERVISOR_ROLE_ID, TRIAL_MOD_ROLE_ID}
    return any(role.id in staff_roles for role in user.roles)

def is_lead_or_supervisor(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    lead_roles = {STAFF_LEAD_ROLE_ID, SUPERVISOR_ROLE_ID}
    return any(role.id in lead_roles for role in interaction.user.roles)

class MockMember:
    def __init__(self, name):
        self.display_name = name
        self.name = name
        self.mention = f"**{name}**"

async def translate_text(text: str, source: str = 'auto', target: str = 'en') -> str:
    try:
        translator = GoogleTranslator(source=source, target=target)
        translated = await asyncio.to_thread(translator.translate, text)
        return translated
    except Exception as e:
        print(f"Translation Error: {e}")
        return text

async def create_ticket_logic(guild, member, ticket_type, questions, category_id, interaction: discord.Interaction):
    global AUTO_ASSIGN_ENABLED, ASSIGNMENT_INDEX

    # --- LOCK GUARD TO PREVENT DUPLICATE CREATION ---
    if member.id in CREATING_TICKETS:
        try:
            await interaction.followup.send("⚠️ Your ticket is already being created, please wait...", ephemeral=True)
        except Exception:
            pass
        return None

    CREATING_TICKETS.add(member.id)

    try:
        category = guild.get_channel(category_id)
        if not category:
            if interaction and not interaction.response.is_done():
                await interaction.followup.send("Error: Ticket category not found.", ephemeral=True)
            return None

        for channel in category.text_channels:
            if channel.topic and str(member.id) in channel.topic:
                if interaction and not interaction.response.is_done():
                    await interaction.followup.send(f"{member.display_name} already has a ticket open here: {channel.mention}", ephemeral=True)
                return channel

        ticket_id = f"{ticket_type[:3].upper()}-{random.randint(1000, 9999)}-{random.randint(100, 999)}"
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            member: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True, embed_links=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True, manage_permissions=True)
        }
        
        standard_staff_roles = [TRIAL_MOD_ROLE_ID, STAFF_ROLE_ID, STAFF_LEAD_ROLE_ID]
        supervisor_role = guild.get_role(SUPERVISOR_ROLE_ID)

        assigned_trial = None
        if AUTO_ASSIGN_ENABLED and ticket_type != "Complaint":
            trial_role = guild.get_role(TRIAL_MOD_ROLE_ID)
            inactive_role = guild.get_role(INACTIVITY_ROLE_ID)
            if trial_role:
                available_trials = [m for m in trial_role.members if not m.bot and (not inactive_role or inactive_role not in m.roles)]
                available_trials.sort(key=lambda x: x.id)
                if available_trials:
                    assigned_trial = available_trials[ASSIGNMENT_INDEX % len(available_trials)]
                    ASSIGNMENT_INDEX += 1
                    overwrites[assigned_trial] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)

        if ticket_type == "Complaint":
            for role_id in standard_staff_roles:
                role = guild.get_role(role_id)
                if role: overwrites[role] = discord.PermissionOverwrite(read_messages=False)
            if supervisor_role:
                overwrites[supervisor_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)
        else:
            all_ids = standard_staff_roles + [SUPERVISOR_ROLE_ID]
            for role_id in all_ids:
                role = guild.get_role(role_id)
                if role:
                    if assigned_trial:
                        can_talk = (role_id in [STAFF_LEAD_ROLE_ID, SUPERVISOR_ROLE_ID])
                    else:
                        can_talk = (role_id in [STAFF_LEAD_ROLE_ID, SUPERVISOR_ROLE_ID]) or (not AUTO_ASSIGN_ENABLED)
                    overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=can_talk, attach_files=can_talk)

        channel = await category.create_text_channel(
            name=f"{ticket_type.lower()}-{member.name}",
            overwrites=overwrites,
            topic=f"Ticket for {member.id} | ID: {ticket_id}"
        )

        embed = discord.Embed(title=f"{ticket_type} Support Request", description=f"Hello {member.mention}!\n\n{questions}", color=discord.Color.blue())
        view = TicketActionView(show_claim=(ticket_type != "Complaint"))
        
        if assigned_trial:
            embed.add_field(name="Assigned Trial Moderator", value=f"{assigned_trial.mention}\n*Assigned and automatically claimed.*")
            for item in view.children:
                if isinstance(item, Button) and item.custom_id == "claim_ticket":
                    item.disabled = True
                    item.label = f"Claimed by {assigned_trial.display_name}"

        await channel.send(embed=embed, view=view)
        if assigned_trial:
            await channel.send(f"{assigned_trial.mention}, you have been automatically assigned and claimed this ticket.")

        # --- NEXT.JS WEB PORTAL SYNC TRIGGER ---
        asyncio.create_task(send_to_nextjs("/api/support/sync/ticket", {
            "ticketId": ticket_id,
            "channelId": str(channel.id),
            "discordUserId": str(member.id),
            "userName": member.display_name,
            "userAvatar": str(member.display_avatar.url) if member.display_avatar else "",
            "ticketType": ticket_type,
            "subject": f"{ticket_type} Support Request"
        }))

        if interaction:
            try:
                await interaction.followup.send(f"Ticket created: {channel.mention}", ephemeral=True)
            except Exception:
                pass
        return channel
    finally:
        if member.id in CREATING_TICKETS:
            CREATING_TICKETS.remove(member.id)

# --- MODALS ---
class CloseTicketModal(Modal, title="Close Ticket"):
    reason = TextInput(label="Reason for Closing", placeholder="Provide a reason for the user...", style=discord.TextStyle.paragraph, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("Processing ticket closure...", ephemeral=True)
        await close_and_log_ticket(interaction.channel, interaction.user, reason=self.reason.value)

# --- LOGGING & CLOSING ---
async def close_and_log_ticket(channel, closer_member, reason="No reason provided"):
    guild = channel.guild
    log_channel_id = COMPLAINT_LOG_CHANNEL_ID if channel.category_id == COMPLAINT_CATEGORY_ID else LOG_CHANNEL_ID
    log_channel = guild.get_channel(log_channel_id)

    if channel.id in ACTIVE_TRANSLATIONS:
        ACTIVE_TRANSLATIONS.pop(channel.id, None)

    messages = []
    async for message in channel.history(limit=None, oldest_first=True):
        messages.append(f"[{message.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {message.author}: {message.clean_content}")
    
    full_transcript = "\n".join(messages)
    transcript_file = discord.File(io.StringIO(full_transcript), filename=f"transcript-{channel.name}.txt")
    
    ticket_id = "N/A"
    owner_member = None
    if channel.topic:
        if "| ID: " in channel.topic: ticket_id = channel.topic.split("| ID: ")[1].strip()
        if "Ticket for " in channel.topic:
            try: 
                owner_id = int(channel.topic.split("for ")[1].split(" |")[0].strip())
                owner_member = await guild.fetch_member(owner_id)
            except: pass

    closer_mention = getattr(closer_member, 'mention', str(closer_member))

    log_embed = discord.Embed(title="Ticket Closed", color=discord.Color.orange(), timestamp=discord.utils.utcnow())
    log_embed.add_field(name="Ticket ID", value=f"`{ticket_id}`", inline=True)
    log_embed.add_field(name="Opened By", value=owner_member.mention if owner_member else "Unknown", inline=True)
    log_embed.add_field(name="Closed By", value=closer_mention, inline=True)
    log_embed.add_field(name="Reason", value=reason, inline=False)
    
    if log_channel: 
        await log_channel.send(content=f"Ticket ID: `{ticket_id}`", embed=log_embed, file=transcript_file)
    
    if owner_member and channel.category_id != COMPLAINT_CATEGORY_ID:
        try: 
            dm_embed = discord.Embed(title="Ticket Closed", description=f"Your ticket (`{ticket_id}`) has been closed.\n**Reason:** {reason}", color=discord.Color.red())
            await owner_member.send(embed=dm_embed, view=FeedbackRatingView(ticket_id, closer_mention))
        except: pass

    await channel.send(f"**Closing Reason:** {reason}\nThis channel will be deleted in 5 seconds.")
    await asyncio.sleep(5)
    await channel.delete()

# --- WEB CLOSE/CLAIM HELPERS ---
async def close_ticket_from_web(channel_id: int, staff_name: str, reason: str = "Resolved via Web Dashboard"):
    channel = bot.get_channel(channel_id)
    if not channel:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception:
            return
    mock_closer = MockMember(staff_name)
    await close_and_log_ticket(channel, mock_closer, reason)

async def claim_ticket_from_web(channel_id: int, staff_name: str):
    channel = bot.get_channel(channel_id)
    if not channel:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception:
            return
    
    staff_role = channel.guild.get_role(STAFF_ROLE_ID)
    trial_role = channel.guild.get_role(TRIAL_MOD_ROLE_ID)
    lead_role = channel.guild.get_role(STAFF_LEAD_ROLE_ID)
    supervisor_role = channel.guild.get_role(SUPERVISOR_ROLE_ID)
    
    if staff_role: await channel.set_permissions(staff_role, read_messages=True, send_messages=False)
    if trial_role: await channel.set_permissions(trial_role, read_messages=True, send_messages=False)
    if lead_role: await channel.set_permissions(lead_role, read_messages=True, send_messages=True)
    if supervisor_role: await channel.set_permissions(supervisor_role, read_messages=True, send_messages=True)

    await channel.send(f"🙋 Ticket claimed via Web Dashboard by **{staff_name}**.")

# --- FLASK ENDPOINTS FOR WEB DASHBOARD SYNC ---
@app.route('/')
def home():
    return "Ticket Bot & Web Sync Engine is Online!"

@app.route('/api/close-ticket', methods=['POST'])
def http_close_ticket():
    secret = request.headers.get("x-web-sync-secret")
    if secret != WEB_SYNC_SECRET:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    channel_id = int(data.get("channelId", 0))
    staff_name = data.get("staffName", "Staff Member")
    reason = data.get("reason", "Resolved via Web Dashboard")
    
    asyncio.run_coroutine_threadsafe(close_ticket_from_web(channel_id, staff_name, reason), bot.loop)
    return jsonify({"success": True}), 200

@app.route('/api/claim-ticket', methods=['POST'])
def http_claim_ticket():
    secret = request.headers.get("x-web-sync-secret")
    if secret != WEB_SYNC_SECRET:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    channel_id = int(data.get("channelId", 0))
    staff_name = data.get("staffName", "Staff Member")
    
    asyncio.run_coroutine_threadsafe(claim_ticket_from_web(channel_id, staff_name), bot.loop)
    return jsonify({"success": True}), 200

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.daemon = True
    t.start()

# --- VIEWS ---
class FeedbackRatingView(View):
    def __init__(self, ticket_id="Unknown", closer_mention="Staff"):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
        self.closer_mention = closer_mention

    async def _process_rating(self, interaction: discord.Interaction, rating: int):
        for item in self.children: item.disabled = True
        await interaction.response.edit_message(content=f"Thank you! You rated this **{rating}/5 stars**.", view=self)
        
        feedback_channel = interaction.client.get_channel(FEEDBACK_LOG_CHANNEL_ID)
        if feedback_channel:
            embed = discord.Embed(title="New Support Feedback", color=discord.Color.gold())
            embed.add_field(name="Rating", value=f"{'⭐' * rating} ({rating}/5)")
            embed.add_field(name="Ticket ID", value=f"`{self.ticket_id}`")
            embed.add_field(name="Handled By", value=self.closer_mention)
            embed.add_field(name="Submitter", value=interaction.user.mention)
            await feedback_channel.send(embed=embed)

    @discord.ui.button(label="1", style=discord.ButtonStyle.danger, custom_id="rate_1")
    async def r1(self, interaction: discord.Interaction, button: Button): await self._process_rating(interaction, 1)
    @discord.ui.button(label="2", style=discord.ButtonStyle.danger, custom_id="rate_2")
    async def r2(self, interaction: discord.Interaction, button: Button): await self._process_rating(interaction, 2)
    @discord.ui.button(label="3", style=discord.ButtonStyle.secondary, custom_id="rate_3")
    async def r3(self, interaction: discord.Interaction, button: Button): await self._process_rating(interaction, 3)
    @discord.ui.button(label="4", style=discord.ButtonStyle.success, custom_id="rate_4")
    async def r4(self, interaction: discord.Interaction, button: Button): await self._process_rating(interaction, 4)
    @discord.ui.button(label="5", style=discord.ButtonStyle.success, custom_id="rate_5")
    async def r5(self, interaction: discord.Interaction, button: Button): await self._process_rating(interaction, 5)

class TicketActionView(View):
    def __init__(self, show_claim: bool = True):
        super().__init__(timeout=None)
        if not show_claim:
            for item in list(self.children):
                if item.custom_id == "claim_ticket": self.remove_item(item)

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success, custom_id="claim_ticket", emoji="🙋")
    async def claim_ticket_button(self, interaction: discord.Interaction, button: Button):
        if not is_staff_or_higher(interaction): 
            return await interaction.response.send_message("Only staff can claim tickets.", ephemeral=True)
        
        button.disabled = True
        button.label = f"Claimed by {interaction.user.display_name}"
        await interaction.response.edit_message(view=self)
        
        staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
        trial_role = interaction.guild.get_role(TRIAL_MOD_ROLE_ID)
        lead_role = interaction.guild.get_role(STAFF_LEAD_ROLE_ID)
        supervisor_role = interaction.guild.get_role(SUPERVISOR_ROLE_ID)
        
        if staff_role: await interaction.channel.set_permissions(staff_role, read_messages=True, send_messages=False)
        if trial_role: await interaction.channel.set_permissions(trial_role, read_messages=True, send_messages=False)
        if lead_role: await interaction.channel.set_permissions(lead_role, read_messages=True, send_messages=True)
        if supervisor_role: await interaction.channel.set_permissions(supervisor_role, read_messages=True, send_messages=True)
        
        await interaction.channel.set_permissions(interaction.user, read_messages=True, send_messages=True, attach_files=True)
        await interaction.followup.send(f"Ticket claimed by {interaction.user.mention}.")

        # --- SYNC CLAIM TO NEXT.JS WEB PORTAL ---
        asyncio.create_task(send_to_nextjs("/api/support/sync/claim", {
            "channelId": str(interaction.channel.id),
            "staffName": interaction.user.display_name
        }))

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, custom_id="close_ticket", emoji="🔒")
    async def close_ticket_button(self, interaction: discord.Interaction, button: Button):
        if not is_staff_or_higher(interaction): 
            return await interaction.response.send_message("Permission denied.", ephemeral=True)
        await interaction.response.send_modal(CloseTicketModal())

class TicketControlPanelView(View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="Server Support", style=discord.ButtonStyle.primary, custom_id="btn_server", emoji="🖥️")
    async def server_support(self, interaction: discord.Interaction, button: Button): 
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            return  # Stop if interaction was already handled by another process!
        await create_ticket_logic(interaction.guild, interaction.user, "Server", MACROS["server_issue_questions"], TICKET_CATEGORY_ID, interaction)

    @discord.ui.button(label="Game Support", style=discord.ButtonStyle.success, custom_id="btn_game", emoji="🎮")
    async def game_support(self, interaction: discord.Interaction, button: Button): 
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            return  # Stop if interaction was already handled by another process!
        await create_ticket_logic(interaction.guild, interaction.user, "Game", MACROS["game_support_questions"], TICKET_CATEGORY_ID, interaction)

    @discord.ui.button(label="File a Complaint", style=discord.ButtonStyle.danger, custom_id="btn_complaint", emoji="⚖️")
    async def complaint(self, interaction: discord.Interaction, button: Button): 
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            return  # Stop if interaction was already handled by another process!
        await create_ticket_logic(interaction.guild, interaction.user, "Complaint", "Describe your complaint in detail.", COMPLAINT_CATEGORY_ID, interaction)

# --- BOT SETUP ---
class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(TicketControlPanelView())
        self.add_view(TicketActionView())
        self.add_view(FeedbackRatingView())

bot = MyBot()

# --- COMMANDS ---

@bot.tree.command(name="assignon", description="Enable round-robin auto-assignment for Trial Moderators")
async def assignon(interaction: discord.Interaction):
    if not is_lead_or_supervisor(interaction):
        return await interaction.response.send_message("Permission denied. Lead/Supervisor only.", ephemeral=True)
    global AUTO_ASSIGN_ENABLED
    AUTO_ASSIGN_ENABLED = True
    await interaction.response.send_message("✅ **Ticket Auto-Assignment is now ON.**")

@bot.tree.command(name="assignoff", description="Disable auto-assignment for Trial Moderators")
async def assignoff(interaction: discord.Interaction):
    if not is_lead_or_supervisor(interaction):
        return await interaction.response.send_message("Permission denied. Lead/Supervisor only.", ephemeral=True)
    global AUTO_ASSIGN_ENABLED
    AUTO_ASSIGN_ENABLED = False
    await interaction.response.send_message("❌ **Ticket Auto-Assignment is now OFF.**")

# --- TRANSLATION COMMANDS ---

@bot.tree.command(name="translateon", description="Enable automatic language translation inside this ticket")
@app_commands.describe(default_language="Optionally specify member language code manually (e.g. 'es' for Spanish, 'fr' for French)")
async def translateon(interaction: discord.Interaction, default_language: str = None):
    if not is_staff_or_higher(interaction):
        return await interaction.response.send_message("Permission denied.", ephemeral=True)
    
    if not interaction.channel.topic or "Ticket for" not in interaction.channel.topic:
        return await interaction.response.send_message("This command can only be used inside a ticket channel.", ephemeral=True)
    
    try:
        owner_id = int(interaction.channel.topic.split("for ")[1].split(" |")[0].strip())
    except Exception:
        return await interaction.response.send_message("Could not extract the ticket owner's identity from the channel topic.", ephemeral=True)
    
    ACTIVE_TRANSLATIONS[interaction.channel.id] = {
        "member_id": owner_id,
        "member_lang": default_language.lower() if default_language else None
    }
    
    lang_info = f"'{default_language}'" if default_language else "Auto-Detecting"
    await interaction.response.send_message(
        f"🌐 **Translation Services Enabled.**\n"
        f"- Target member language: `{lang_info}`\n"
        f"- Submissions from the member will translate to English.\n"
        f"- Submissions from staff translate to the member's target language."
    )

@bot.tree.command(name="translateoff", description="Disable automatic language translation inside this ticket")
async def translateoff(interaction: discord.Interaction):
    if not is_staff_or_higher(interaction):
        return await interaction.response.send_message("Permission denied.", ephemeral=True)
    
    if interaction.channel.id in ACTIVE_TRANSLATIONS:
        ACTIVE_TRANSLATIONS.pop(interaction.channel.id, None)
        await interaction.response.send_message("❌ **Translation Services Disabled.**")
    else:
        await interaction.response.send_message("Translation is not active in this channel.", ephemeral=True)

# --- BACKPORTED COMMANDS ---

@bot.tree.command(name="removeassign", description="Remove an assigned member from this ticket")
async def removeassign(interaction: discord.Interaction, member: discord.Member = None):
    await interaction.response.defer()

    if not is_lead_or_supervisor(interaction):
        return await interaction.followup.send("Permission denied. Lead/Supervisor only.", ephemeral=True)
    
    if not interaction.channel.topic or "Ticket for" not in interaction.channel.topic:
        return await interaction.followup.send("This command can only be used inside a ticket channel.", ephemeral=True)
    
    removed_any = False
    guild = interaction.guild
    trial_role = guild.get_role(TRIAL_MOD_ROLE_ID)
    staff_role = guild.get_role(STAFF_ROLE_ID)
    lead_role = guild.get_role(STAFF_LEAD_ROLE_ID)
    supervisor_role = guild.get_role(SUPERVISOR_ROLE_ID)
    msg_text = ""
    
    if member:
        await interaction.channel.set_permissions(member, overwrite=None)
        removed_any = True
        msg_text = f"Removed assignment/permissions for {member.mention}."
    else:
        removed_members = []
        for target in list(interaction.channel.overwrites.keys()):
            if isinstance(target, discord.Member):
                if trial_role and trial_role in target.roles:
                    await interaction.channel.set_permissions(target, overwrite=None)
                    removed_members.append(target.mention)
        
        if removed_members:
            removed_any = True
            msg_text = f"Removed assignment for: {', '.join(removed_members)}."
        else:
            msg_text = "No assigned Trial Moderator with custom permissions found in this channel."

    if removed_any:
        if staff_role:
            await interaction.channel.set_permissions(staff_role, read_messages=True, send_messages=not AUTO_ASSIGN_ENABLED, attach_files=not AUTO_ASSIGN_ENABLED)
        if trial_role:
            await interaction.channel.set_permissions(trial_role, read_messages=True, send_messages=not AUTO_ASSIGN_ENABLED, attach_files=not AUTO_ASSIGN_ENABLED)
        if lead_role:
            await interaction.channel.set_permissions(lead_role, read_messages=True, send_messages=True, attach_files=True)
        if supervisor_role:
            await interaction.channel.set_permissions(supervisor_role, read_messages=True, send_messages=True, attach_files=True)

        async for msg in interaction.channel.history(limit=30, oldest_first=True):
            if msg.author == bot.user and msg.embeds:
                embed = msg.embeds[0]
                embed.clear_fields()
                await msg.edit(embed=embed, view=TicketActionView(show_claim=True))
                break
                
        await interaction.followup.send(f"✅ {msg_text} Ticket has been unclaimed and is now open for other staff or trial moderators to claim.")
    else:
        await interaction.followup.send(msg_text)

@bot.tree.command(name="createticket", description="Create a ticket on behalf of a member")
@app_commands.choices(ticket_type=[
    app_commands.Choice(name="Server Support", value="Server"),
    app_commands.Choice(name="Game Support", value="Game"),
    app_commands.Choice(name="Complaint", value="Complaint")
])
async def createticket(interaction: discord.Interaction, ticket_type: app_commands.Choice[str], member: discord.Member):
    if not is_staff_or_higher(interaction):
        return await interaction.response.send_message("Permission denied.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    
    cat_id = COMPLAINT_CATEGORY_ID if ticket_type.value == "Complaint" else TICKET_CATEGORY_ID
    msg = "Staff-initiated complaint." if ticket_type.value == "Complaint" else "Staff-initiated support request."
    
    await create_ticket_logic(interaction.guild, member, ticket_type.value, msg, cat_id, interaction)

@bot.tree.command(name="setup_tickets", description="Setup the ticket support panel")
@app_commands.default_permissions(administrator=True)
async def setup_tickets(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Support Center",
        description="Please select the appropriate category for your support request below. A private channel will be opened for you to speak with our team.",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="🖥️ Server Support",
        value="For issues related to the server (mutes, warning, ban or reporting a member).",
        inline=False
    )
    embed.add_field(
        name="🎮 Game Support",
        value="For appealing ban, reporting glitch abusers/hackers, or issues related to the game.",
        inline=False
    )
    embed.add_field(
        name="⚖️ File a Complaint",
        value="*Supervisor-Only:* Use this to file a formal complaint against a staff member.",
        inline=False
    )
    
    await interaction.channel.send(embed=embed, view=TicketControlPanelView())
    
    if not interaction.response.is_done():
        await interaction.response.send_message("✅ Panel posted!", ephemeral=True)
    else:
        await interaction.followup.send("✅ Panel posted!", ephemeral=True)

@bot.tree.command(name="merge", description="Merge this ticket's history including images")
async def merge(interaction: discord.Interaction, target_channel: discord.TextChannel):
    if not is_staff_or_higher(interaction):
        return await interaction.response.send_message("Permission denied.", ephemeral=True)
    
    await interaction.response.send_message(f"Merging content into {target_channel.mention}...")
    
    async for message in interaction.channel.history(limit=100, oldest_first=True):
        if message.author == bot.user and message.embeds: continue
        
        content = f"**[Merged] {message.author.display_name}:** {message.content}"
        
        files = []
        for attachment in message.attachments:
            file_bytes = await attachment.read()
            files.append(discord.File(io.BytesIO(file_bytes), filename=attachment.filename))
        
        if content.strip() or files:
            await target_channel.send(content=content if content.strip() else None, files=files)
            await asyncio.sleep(0.5)

    await interaction.channel.send("Merge complete. Deleting channel in 5 seconds.")
    await asyncio.sleep(5)
    await interaction.channel.delete()

# --- TASKS & EVENTS ---
@tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
async def check_inactive_tickets():
    await bot.wait_until_ready()
    guild = bot.get_guild(GUILD_ID)
    if not guild: return
    category = guild.get_channel(TICKET_CATEGORY_ID)
    if not category: return
    now = discord.utils.utcnow()
    for channel in category.text_channels:
        if not channel.topic or "Ticket for" not in channel.topic: continue
        try:
            msgs = [m async for m in channel.history(limit=1)]
            if not msgs: continue
            last_msg = msgs[0]
            
            is_warning_msg = (last_msg.author == bot.user and "⚠️ This ticket is inactive" in last_msg.content)
            
            if is_warning_msg:
                time_since_warning = now - last_msg.created_at
                remaining_hours = INACTIVITY_CLOSE_AFTER_HOURS - INACTIVITY_WARN_AFTER_HOURS
                if time_since_warning > datetime.timedelta(hours=remaining_hours):
                    await close_and_log_ticket(channel, bot.user, "Automated closing due to inactivity.")
            else:
                time_since_last_msg = now - last_msg.created_at
                if time_since_last_msg > datetime.timedelta(hours=INACTIVITY_WARN_AFTER_HOURS):
                    await channel.send("⚠️ This ticket is inactive and will be closed automatically in 24 hours.")
        except Exception as e: 
            print(f"Error processing inactivity check for channel {channel.name}: {e}")
            continue

@bot.event
async def on_ready():
    print(f"--- BOT IS ONLINE AS {bot.user.name} ---")
    try:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        print(f"✅ Synced {len(synced)} command(s) instantly to guild {GUILD_ID}!")
    except Exception as e:
        print(f"SYNC ERROR: {e}")
        
    if not check_inactive_tickets.is_running():
        check_inactive_tickets.start()

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # --- NEXT.JS MESSAGE SYNC TRIGGER ---
    if message.channel.category_id in [TICKET_CATEGORY_ID, COMPLAINT_CATEGORY_ID]:
        attachments = [att.url for att in message.attachments]
        asyncio.create_task(send_to_nextjs("/api/support/sync/message", {
            "channelId": str(message.channel.id),
            "senderId": str(message.author.id),
            "senderName": message.author.display_name,
            "senderAvatar": str(message.author.display_avatar.url) if message.author.display_avatar else "",
            "content": message.content,
            "attachments": attachments,
            "isStaff": is_staff_or_higher_user(message.author)
        }))

    # Process translation conditions
    if message.channel.id in ACTIVE_TRANSLATIONS:
        session = ACTIVE_TRANSLATIONS[message.channel.id]
        member_id = session["member_id"]
        member_lang = session["member_lang"]
        content = message.content.strip()

        if content:
            if message.author.id == member_id:
                try:
                    detected_lang = await asyncio.to_thread(detect, content)
                except Exception:
                    detected_lang = "en"

                if member_lang is not None:
                    if detected_lang == member_lang:
                        translated = await translate_text(content, source=detected_lang, target="en")
                        if translated and translated.lower() != content.lower():
                            embed = discord.Embed(
                                title="🌐 Translation to English",
                                description=translated,
                                color=discord.Color.blue()
                            )
                            embed.set_footer(text=f"Language: {detected_lang.upper()} (Locked) | Auto-Translation")
                            await message.channel.send(embed=embed)
                else:
                    if detected_lang != "en":
                        session["member_lang"] = detected_lang
                        translated = await translate_text(content, source=detected_lang, target="en")
                        if translated and translated.lower() != content.lower():
                            embed = discord.Embed(
                                title="🌐 Translation to English",
                                description=translated,
                                color=discord.Color.blue()
                            )
                            embed.set_footer(text=f"Detected & Locked: {detected_lang.upper()}")
                            await message.channel.send(embed=embed)
            else:
                if member_lang and member_lang != "en":
                    translated = await translate_text(content, source="en", target=member_lang)
                    if translated and translated.lower() != content.lower():
                        embed = discord.Embed(
                            title=f"🌐 Translation to {member_lang.upper()}",
                            description=translated,
                            color=discord.Color.green()
                        )
                        embed.set_footer(text="Translated automatically for the user")
                        await message.channel.send(embed=embed)

    await bot.process_commands(message)

if __name__ == "__main__":
    keep_alive()
    if BOT_TOKEN: bot.run(BOT_TOKEN)
