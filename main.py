import discord
from discord.ext import commands
import asyncio
import os
from keep_alive import keep_alive

# Botのインテント（権限）設定
intents = discord.Intents.default()
intents.message_content = True  # メッセージの内容を読み取るために必要
intents.members = True          # セキュリティ機能（メンバー管理など）で必要

bot = commands.Bot(command_prefix="!", intents=intents)

# --- 設定項目 ---
# スパム対策用のメッセージ送信履歴を保存する辞書 {ユーザーID: [送信時間のリスト]}
user_message_history = {}
SPAM_LIMIT = 5          # 制限するメッセージ数
SPAM_INTERVAL = 5.0     # 制限する秒数（5秒間に5回以上でスパムと判定）

# 禁止ワードリスト（必要に応じて追加してください）
BANNED_WORDS = ["荒らし", "あらし", "スパム", "spam"] 


# --- イベント: 起動時に実行 ---
@bot.event
async def on_ready():
    print(f"ログインしました: {bot.user.name} ({bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="Bump & Security 監視中"))


# --- イベント: メッセージ受信時に実行 ---
@bot.event
async def on_message(message):
    # Bot自身のメッセージは無視
    if message.author.bot:
        # ただし、DISBOARD(ボット)やその他のUpボットが「Bump成功」のメッセージを出した時の対策
        # ここでは、ユーザー自身が「bump」「up」と打った場合、または公式Botの成功メッセージに反応する形にします
        pass

    # --- セキュリティ機能 1: 禁止ワードチェック ---
    for word in BANNED_WORDS:
        if word in message.content:
            try:
                await message.delete()
                await message.channel.send(f"{message.author.mention} 警告: 禁止ワードが含まれているためメッセージを削除しました。", delete_after=5)
                return  # 処理を終了
            except discord.Forbidden:
                print("メッセージ削除の権限がありません。")

    # --- セキュリティ機能 2: 簡易スパム検知 ---
    if not message.author.bot:
        user_id = message.author.id
        current_time = asyncio.get_event_loop().time()
        
        if user_id not in user_message_history:
            user_message_history[user_id] = []
        
        # 範囲外の古い履歴を削除
        user_message_history[user_id] = [t for t in user_message_history[user_id] if current_time - t < SPAM_INTERVAL]
        user_message_history[user_id].append(current_time)
        
        if len(user_message_history[user_id]) > SPAM_LIMIT:
            try:
                # 警告メッセージを送信
                await message.channel.send(f"{message.author.mention} スパム行為を検知しました。少し時間を空けて発言してください。", delete_after=10)
                await message.delete()
                return
            except discord.Forbidden:
                pass

    # --- Bump / Up 2時間リマインダー機能 ---
    # 送信されたテキストに「bump」または「up」が含まれている（スラッシュコマンド、通常メッセージ両対応）
    content = message.content.lower()
    
    # DISBOARDなどの公式Botが「表示順位をアップしたよ」などの成功メッセージを出した時に反応させたい場合：
    # if message.author.id == 302050872383242240 (DISBOARDのID) and "表示順位をアップしたよ" in message.embeds... 
    # のような書き方も可能ですが、シンプルにユーザーの発言に反応させます。
    if content.startswith("!bump") or content.startswith("/bump") or content.startswith("/up") or content == "bump" or content == "up":
        await message.channel.send(f"【リマインダー設定】\n{message.author.mention} さん、Bump/Upを検知しました。2時間後（120分後）にお知らせします！")
        
        # 2時間（7200秒）待機
        await asyncio.sleep(7200)
        
        # 2時間後の通知
        await message.channel.send(f"🔔 {message.author.mention} **前回のBump/Upから2時間が経過しました！**\n次のBump/Upが可能です。 `/bump` や `/up` を実行してください！")

    # commandsを使用できるようにするためのおまじない
    await bot.process_commands(message)


# --- セキュリティ機能 3: メンバー参加時の自動アナウンスとロール付与（必要に応じて） ---
@bot.event
async def on_member_join(member):
    # サーバーにログ用チャンネル（例: "入退室ログ" や "log"）があればそこに送信
    channel = discord.utils.get(member.guild.channels, name="入退室ログ")
    if channel:
        await channel.send(f"📥 {member.mention} がサーバーに参加しました。アカウント作成日: {member.created_at.strftime('%Y-%m-%d %H:%M:%S')}")


# --- Webサーバーの起動 ＆ Botの起動 ---
keep_alive()

# Renderの環境変数からトークンを取得して起動
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("エラー: 環境変数 'DISCORD_BOT_TOKEN' が設定されていません。")