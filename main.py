import discord
import random
import datetime
import io
import asyncio
import os
import aiohttp
from discord.ext import commands, tasks
from discord.ui import Button, View, Modal, TextInput
from flask import Flask
from threading import Thread
from discord import app_commands

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
INACTIVITY_ROLE_ID = 1428490017420087478    
COMPLAINT_CATEGORY_ID = 1428497122759671881 
COMPLAINT_LOG_CHANNEL_ID = 1428499253952774176
FEEDBACK_LOG_CHANNEL_ID = 1430296240528294049 

# --- AUTO-ASSIGNMENT CONFIG ---
TRIAL_MOD_ROLE_ID = 1518663064956702890 
AUTO_ASSIGN_ENABLED = False 
ASSIGNMENT_INDEX = 0 

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

# --- HELPERS ---

def is_staff_or_higher(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    staff_roles = {STAFF_ROLE_ID, STAFF_LEAD_ROLE_ID, SUPERVISOR_ROLE_ID, TRIAL_MOD_ROLE_ID}
    return any(role.id in staff_roles for role in interaction.user.roles)

def is_lead_or_supervisor(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    lead_roles = {STAFF_LEAD_ROLE_ID, SUPERVISOR_ROLE_ID}
    return any(role.id in lead_roles for role in interaction.user.roles)

async def create_ticket_logic(guild, member, ticket_type, questions, category_id, interaction: discord.Interaction):
    global AUTO_ASSIGN_ENABLED, ASSIGNMENT_INDEX
    category = guild.get_channel(category_id)
    if not category:
        return await interaction.followup.send("Error: Ticket category not found.", ephemeral=True)

    for channel in category.text_channels:
        if channel.topic and str(member.id) in channel.topic:
            return await interaction.followup.send(f"{member.display_name} already has a ticket open here: {channel.mention}", ephemeral=True)

    ticket_id = f"{ticket_type[:3].upper()}-{random.randint(1000, 9999)}-{random.randint(100, 999)}"
    
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        member: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True, embed_links=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True, manage_permissions=True)
    }
    
    standard_staff_roles = [TRIAL_MOD_ROLE_ID, STAFF_ROLE_ID, STAFF_LEAD_ROLE_ID]
    supervisor_role = guild.get_role(SUPERVISOR_ROLE_ID)

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
                can_talk = (role_id in [STAFF_LEAD_ROLE_ID, SUPERVISOR_ROLE_ID]) or (not AUTO_ASSIGN_ENABLED)
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=can_talk, attach_files=can_talk)

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

    channel = await category.create_text_channel(
        name=f"{ticket_type}-{member.name}",
        overwrites=overwrites,
        topic=f"Ticket for {member.id} | ID: {ticket_id}"
    )

    embed = discord.Embed(title=f"{ticket_type} Support Request", description=f"Hello {member.mention}!\n\n{questions}", color=discord.Color.blue())
    view = TicketActionView(show_claim=(ticket_type != "Complaint"))
    
    if assigned_trial:
        embed.add_field(name="Assigned Trial Moderator", value=f"{assigned_trial.mention}\n*Assigned via round-robin.*")
        for item in view.children:
            if isinstance(item, Button) and item.custom_id == "claim_ticket":
                item.disabled = True
                item.label = f"Assigned: {assigned_trial.display_name}"

    await channel.send(embed=embed, view=view)
    if assigned_trial:
        await channel.send(f"{assigned_trial.mention}, you have been automatically assigned to this ticket.")

    await interaction.followup.send(f"Ticket created: {channel.mention}", ephemeral=True)
    return channel

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

    log_embed = discord.Embed(title="Ticket Closed", color=discord.Color.orange(), timestamp=discord.utils.utcnow())
    log_embed.add_field(name="Ticket ID", value=f"`{ticket_id}`", inline=True)
    log_embed.add_field(name="Opened By", value=owner_member.mention if owner_member else "Unknown", inline=True)
    log_embed.add_field(name="Closed By", value=closer_member.mention, inline=True)
    log_embed.add_field(name="Reason", value=reason, inline=False)
    
    if log_channel: 
        await log_channel.send(content=f"Ticket ID: `{ticket_id}`", embed=log_embed, file=transcript_file)
    
    if owner_member and channel.category_id != COMPLAINT_CATEGORY_ID:
        try: 
            dm_embed = discord.Embed(title="Ticket Closed", description=f"Your ticket (`{ticket_id}`) has been closed.\n**Reason:** {reason}", color=discord.Color.red())
            await owner_member.send(embed=dm_embed, view=FeedbackRatingView(ticket_id, closer_member.mention))
        except: pass

    await channel.send(f"**Closing Reason:** {reason}\nThis channel will be deleted in 5 seconds.")
    await asyncio.sleep(5)
    await channel.delete()

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
            for item in self.children:
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
        
        if staff_role: 
            await interaction.channel.set_permissions(staff_role, read_messages=True, send_messages=False)
        if trial_role: 
            await interaction.channel.set_permissions(trial_role, read_messages=True, send_messages=False)
        if lead_role:
            await interaction.channel.set_permissions(lead_role, read_messages=True, send_messages=True)
        if supervisor_role:
            await interaction.channel.set_permissions(supervisor_role, read_messages=True, send_messages=True)
        
        await interaction.channel.set_permissions(interaction.user, read_messages=True, send_messages=True, attach_files=True)
        await interaction.followup.send(f"Ticket claimed by {interaction.user.mention}.")

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, custom_id="close_ticket", emoji="🔒")
    async def close_ticket_button(self, interaction: discord.Interaction, button: Button):
        if not is_staff_or_higher(interaction): 
            return await interaction.response.send_message("Permission denied.", ephemeral=True)
        await interaction.response.send_modal(CloseTicketModal())

class TicketControlPanelView(View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="Server Support", style=discord.ButtonStyle.primary, custom_id="btn_server", emoji="🖥️")
    async def server_support(self, interaction: discord.Interaction, button: Button): 
        await interaction.response.defer(ephemeral=True)
        await create_ticket_logic(interaction.guild, interaction.user, "Server", MACROS["server_issue_questions"], TICKET_CATEGORY_ID, interaction)

    @discord.ui.button(label="Game Support", style=discord.ButtonStyle.success, custom_id="btn_game", emoji="🎮")
    async def game_support(self, interaction: discord.Interaction, button: Button): 
        await interaction.response.defer(ephemeral=True)
        await create_ticket_logic(interaction.guild, interaction.user, "Game", MACROS["game_support_questions"], TICKET_CATEGORY_ID, interaction)

    @discord.ui.button(label="File a Complaint", style=discord.ButtonStyle.danger, custom_id="btn_complaint", emoji="⚖️")
    async def complaint(self, interaction: discord.Interaction, button: Button): 
        await interaction.response.defer(ephemeral=True)
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

@bot.tree.command(name="removeassign", description="Remove an assigned member from this ticket")
async def removeassign(interaction: discord.Interaction, member: discord.Member = None):
    if not is_lead_or_supervisor(interaction):
        return await interaction.response.send_message("Permission denied. Lead/Supervisor only.", ephemeral=True)
    
    if not interaction.channel.topic or "Ticket for" not in interaction.channel.topic:
        return await interaction.response.send_message("This command can only be used inside a ticket channel.", ephemeral=True)
    
    removed_any = False
    guild = interaction.guild
    trial_role = guild.get_role(TRIAL_MOD_ROLE_ID)
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
        # Scan and update the main bot embed inside the channel to re-enable claiming
        async for msg in interaction.channel.history(limit=30, oldest_first=True):
            if msg.author == bot.user and msg.embeds:
                embed = msg.embeds[0]
                embed.clear_fields()  # Remove assignment fields
                
                # Edit with active TicketActionView containing the active claim button
                await msg.edit(embed=embed, view=TicketActionView(show_claim=True))
                break
                
        await interaction.response.send_message(f"✅ {msg_text} Ticket is now open for claiming by standard staff or trial moderators.")
    else:
        await interaction.response.send_message(msg_text, ephemeral=True)

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
    embed = discord.Embed(title="Support Center", description="Select a category below to open a ticket.", color=discord.Color.blue())
    await interaction.channel.send(embed=embed, view=TicketControlPanelView())
    await interaction.response.send_message("✅ Panel posted!", ephemeral=True)

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
            if now - last_msg.created_at > datetime.timedelta(hours=INACTIVITY_CLOSE_AFTER_HOURS):
                await close_and_log_ticket(channel, bot.user, "Automated closing due to inactivity.")
            elif now - last_msg.created_at > datetime.timedelta(hours=INACTIVITY_WARN_AFTER_HOURS):
                if not (last_msg.author == bot.user):
                    await channel.send("⚠️ This ticket is inactive and will be closed automatically in 24 hours.")
        except: continue

@bot.event
async def on_ready():
    print(f"--- BOT IS ONLINE AS {bot.user.name} ---")
    try:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    except Exception as e: print(f"SYNC ERROR: {e}")
    if not check_inactive_tickets.is_running(): check_inactive_tickets.start()

if __name__ == "__main__":
    keep_alive()
    if BOT_TOKEN: bot.run(BOT_TOKEN)
