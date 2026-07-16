import discord
from discord.ext import commands, tasks
import asyncio
import os
import random
from datetime import datetime, timedelta, timezone
from threading import Thread
from flask import Flask

# --- Flask Webサーバー設定 (Keep Alive) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def start_web_server():
    t = Thread(target=run)
    t.start()


# --- Discord Bot 設定 ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# --- セキュリティ設定・データベース ---
warn_database = {}  # {ユーザーID: 警告回数}
user_message_history = {}
SPAM_LIMIT = 5          # 制限メッセージ数
SPAM_INTERVAL = 5.0     # 制限秒数
BANNED_WORDS = ["荒らし", "あらし", "スパム", "spam"]
SUSPICIOUS_ACCOUNT_DAYS = 7  # 作成から何日以内を「危険・不審」とみなすか


# --- 1. ロールパネル用：ボタンの定義 ---
class RoleButton(discord.ui.Button):
    def __init__(self, label: str, role_id: int, color: discord.ButtonStyle):
        super().__init__(label=label, style=color, custom_id=f"role_{role_id}")
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        # サーバー（ギルド）オブジェクトとメンバーの取得
        guild = interaction.guild
        role = guild.get_role(self.role_id)
        
        if not role:
            await interaction.response.send_message("❌ 設定されたロールが見つかりませんでした。管理者に連絡してください。", ephemeral=True)
            return

        member = interaction.user
        # すでにロールを持っている場合は剥奪、持っていない場合は付与
        if role in member.roles:
            await member.remove_roles(role)
            await interaction.response.send_message(f"✅ ロール「{role.name}」を外しました。", ephemeral=True)
        else:
            await member.add_roles(role)
            await interaction.response.send_message(f"✅ ロール「{role.name}」を付与しました！", ephemeral=True)


# --- ロールパネル全体の「View」定義 ---
class RolePanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # timeout=None にすることでBot再起動後もボタンが動くようにする
        
        # TODO: あなたのサーバーの「ロールID」に書き換えてください（ボタンは複数追加可能）
        # 例: RoleButton(ラベル名, ロールID, ボタンの色)
        # 色の種類: discord.ButtonStyle.primary (青), success (緑), danger (赤), secondary (灰色)
        self.add_item(RoleButton("マイクラ部 ⛏️", 123456789012345678, discord.ButtonStyle.primary))
        self.add_item(RoleButton("Overwatch 2 ⚔️", 876543210987654321, discord.ButtonStyle.success))


# --- イベント: 起動時に実行 ---
@bot.event
async def on_ready():
    print(f"ログインしました: {bot.user.name}")
    # 再起動後もロールパネルのボタンが動くように登録する
    bot.add_view(RolePanelView())
    change_status.start()


# --- タスク: 10秒ごとにステータスを切り替える ---
@tasks.loop(seconds=10)
async def change_status():
    total_members = sum(guild.member_count for guild in bot.guilds)
    statuses = [
        discord.Game(name="スパム監視中 🛡️"),
        discord.Game(name=f"{total_members}人のメンバーを見守り中 👥"),
        discord.Game(name="!help でコマンドを確認 💬"),
        discord.Streaming(name="2時間リマインダー稼働中 ⏰", url="https://www.twitch.tv/discord")
    ]
    status = random.choice(statuses)
    await bot.change_presence(activity=status)


# --- 2. メッセージ削除ログ機能 ---
@bot.event
async def on_message_delete(message):
    if message.author.bot:
        return
    
    # 「送信ログ」という名前のチャンネルを探す
    log_channel = discord.utils.get(message.guild.channels, name="送信ログ")
    if log_channel:
        embed = discord.Embed(title="🗑️ メッセージ削除ログ", color=0xffa500, timestamp=datetime.now(timezone.utc))
        embed.add_field(name="送信者", value=message.author.mention, inline=True)
        embed.add_field(name="チャンネル", value=message.channel.mention, inline=True)
        embed.add_field(name="削除された内容", value=message.content or "[添付ファイルのみ、または取得不可]", inline=False)
        await log_channel.send(embed=embed)


# --- 3. メッセージ編集ログ機能 ---
@bot.event
async def on_message_edit(before, after):
    if before.author.bot or before.content == after.content:
        return
    
    log_channel = discord.utils.get(before.guild.channels, name="送信ログ")
    if log_channel:
        embed = discord.Embed(title="📝 メッセージ編集ログ", color=0x3498db, timestamp=datetime.now(timezone.utc))
        embed.add_field(name="送信者", value=before.author.mention, inline=True)
        embed.add_field(name="チャンネル", value=before.channel.mention, inline=True)
        embed.add_field(name="編集前", value=before.content, inline=False)
        embed.add_field(name="編集後", value=after.content, inline=False)
        await log_channel.send(embed=embed)


# --- イベント: メッセージ受信時 (スパム監視 & Bumpリマインダー) ---
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # --- セキュリティ: 禁止ワードチェック ---
    for word in BANNED_WORDS:
        if word in message.content:
            try:
                await message.delete()
                await message.channel.send(f"{message.author.mention} 警告: 禁止ワードが含まれているため削除しました。", delete_after=5)
                return
            except discord.Forbidden:
                pass

    # --- セキュリティ: スパム検知＆タイムアウト機能 ---
    user_id = message.author.id
    current_time = asyncio.get_event_loop().time()
    if user_id not in user_message_history:
        user_message_history[user_id] = []
    user_message_history[user_id] = [t for t in user_message_history[user_id] if current_time - t < SPAM_INTERVAL]
    user_message_history[user_id].append(current_time)
    
    if len(user_message_history[user_id]) > SPAM_LIMIT:
        try:
            # メッセージを削除
            await message.delete()
            
            # 10分間のタイムアウトを適用
            duration = timedelta(minutes=10)
            await message.author.timeout(duration, reason="スパム行為による自動システム制限")
            
            # チャンネルに通知
            await message.channel.send(f"🚨 {message.author.mention} をスパム行為のため **10分間タイムアウト（ミュート）** にしました。")
            
            # 「送信ログ」にも報告
            log_channel = discord.utils.get(message.guild.channels, name="送信ログ")
            if log_channel:
                await log_channel.send(f"🚨 **スパム処置報告**: {message.author.mention} を10分間タイムアウトにしました。")
            return
        except discord.Forbidden:
            print("タイムアウトまたは削除の権限（メンバーの管理/メッセージの管理）がありません。")

    # --- Bump / Up 2時間リマインダー ---
    content = message.content.lower()
    if content.startswith("!bump") or content.startswith("/bump") or content.startswith("/up") or content == "bump" or content == "up":
        await message.channel.send(f"⏰ **Bump/Upを検知しました！**\n{message.author.mention} さん、2時間後にお知らせします。")
        await asyncio.sleep(7200)
        await message.channel.send(f"🔔 {message.author.mention} **前回の操作から2時間が経過しました！**\n次の `/bump` または `/up` が可能です！")

    await bot.process_commands(message)


# --- 4. 危険なメンバー（捨て垢・不審な垢）の入室警告 ---
@bot.event
async def on_member_join(member):
    log_channel = discord.utils.get(member.guild.channels, name="入退室ログ")
    if not log_channel:
        return

    # アカウント作成日からの経過日数
    now = datetime.now(timezone.utc)
    account_age = now - member.created_at
    
    is_suspicious = False
    warning_reasons = []

    # 警告条件1: 作成から数日以内のアカウント (捨て垢の可能性)
    if account_age.days < SUSPICIOUS_ACCOUNT_DAYS:
        is_suspicious = True
        warning_reasons.append(f"⚠️ **新規作成アカウント** (作成から {account_age.days} 日目)")
        
    # 警告条件2: デフォルトアバター (初期アイコンの荒らし対策)
    if member.avatar is None:
        is_suspicious = True
        warning_reasons.append("⚠️ **初期アバター (デフォルトアイコン)**")

    # ログ送信用の埋め込みメッセージを作成
    embed = discord.Embed(
        title="📥 メンバーが参加しました", 
        description=f"{member.mention} ({member.name})",
        color=0x00ff00 if not is_suspicious else 0xff0000, # 危険な場合は赤色
        timestamp=now
    )
    embed.add_field(name="アカウント作成日時", value=member.created_at.strftime('%Y-%m-%d %H:%M:%S'), inline=False)
    
    if is_suspicious:
        embed.title = "⚠️ 不審なメンバーの参加を検知 ⚠️"
        embed.add_field(name="警告理由", value="\n".join(warning_reasons), inline=False)
        # メンションをつけて管理者に通知を飛ばす
        await log_channel.send(content="⚠️ **管理者への警告アラート**", embed=embed)
    else:
        await log_channel.send(embed=embed)


# --- コマンド：ロールパネル設置 (!rolepanel) ---
@bot.command(name="rolepanel")
@commands.has_permissions(administrator=True) # 管理者のみ実行可能
async def send_role_panel(ctx):
    """ボタン式のロール付与パネルを設置します"""
    embed = discord.Embed(
        title="🎭 ロール（役職）付与パネル",
        description="下のボタンを押すことで、対応するロールを自分でつけたり外したりできます！\n興味のあるものを選択してください。",
        color=0x9b59b6
    )
    # パネルを送信。この時、定義したView（ボタン）を一緒に渡す
    await ctx.send(embed=embed, view=RolePanelView())


# --- 起動処理 ---
start_web_server()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# 無料公開されているプロキシを設定します（例: http://ip:port の形式）
# ※無料プロキシは不安定な場合があるため、動作しない場合はプロキシのアドレスを変更する必要があります
PROXY_URL = "http://discord-proxy.com:80" 

if TOKEN:
    # bot.run() を呼ぶ前に、botオブジェクト内部の HTTP クライアントにプロキシを設定します
    bot.http.proxy = PROXY_URL
    
    try:
        print(f"プロキシ経由でログインを試みます... ({PROXY_URL})")
        bot.run(TOKEN)
    except Exception as e:
        print(f"ログイン中にエラーが発生しました: {e}")
else:
    print("環境変数 'DISCORD_BOT_TOKEN' が見つかりません。")
