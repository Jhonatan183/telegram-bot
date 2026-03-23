from telegram.ext import Updater, CommandHandler

TOKEN = "8192711687:AAFYKMnTNFrnYJooUZ6LPRFZ7A1RhElRJ5U"

def start(update, context):
    update.message.reply_text("🔥 BOT FUNCIONANDO")

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))

    print("BOT ENCENDIDO")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
